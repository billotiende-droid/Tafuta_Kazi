import logging
from pathlib import Path
from typing import Optional

from aiohttp import web
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from config import settings
from ingestion.deduplicator import deduplicator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BotContext:
    """Holds the single shared Telegram Application instance.

    Using a class attribute instead of a module-level global avoids the
    'global' keyword and the static-analysis warnings that come with it.
    """
    app: Optional[Application] = None


_ctx = BotContext()


def set_telegram_app_instance(app: Application) -> None:
    """Registers the running Telegram Application into the BotContext singleton."""
    _ctx.app = app


# ---------------------------------------------------------------------------
# Telegram command handlers
# ---------------------------------------------------------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Utility handler — replies with the chat ID so you can confirm TELEGRAM_CHAT_ID."""
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"🤖 *Tafuta Kazi Bot Active*\nYour Chat ID: `{chat_id}`",
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------------------
# Outbound: send PDF + approve/reject buttons to Telegram
# ---------------------------------------------------------------------------

async def send_approval_request(
    pdf_path: str,
    job_title: str,
    company: str,
    job_url: str,
    url_hash: str,
) -> None:
    """Dispatches the tailored CV PDF to Telegram with inline Approve/Reject buttons."""
    if _ctx.app is None:
        raise RuntimeError(
            "Telegram app instance not set. Call set_telegram_app_instance() at startup."
        )

    # CWE-22 path traversal mitigation: resolve the path and confirm it sits
    # inside OUTPUT_DIR before opening the file descriptor.
    resolved_path = Path(pdf_path).resolve()
    allowed_dir = settings.OUTPUT_DIR.resolve()

    if not resolved_path.is_relative_to(allowed_dir):
        logger.error(
            f"[Bot] Rejected unsafe pdf_path outside OUTPUT_DIR: {resolved_path}"
        )
        return

    caption = (
        f"🎯 *New Job Target Discovered*\n\n"
        f"*Role:* {job_title}\n"
        f"*Company:* {company}\n"
        f"*Link:* [View Job Posting]({job_url})\n\n"
        f"Review the attached CV below:"
    )

    keyboard = [[
        InlineKeyboardButton("✅ Approve", callback_data=f"approve:{url_hash}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"reject:{url_hash}"),
    ]]

    if resolved_path.exists():
        with open(resolved_path, "rb") as doc:
            await _ctx.app.bot.send_document(
                chat_id=settings.TELEGRAM_CHAT_ID,
                document=doc,
                filename=resolved_path.name,
                caption=caption,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        logger.info(f"[Bot] Dispatched PDF for job hash {url_hash} to Telegram.")
    else:
        logger.error(f"[Bot] Target PDF file missing: {resolved_path}")


# ---------------------------------------------------------------------------
# Inbound: handle Approve / Reject button presses
# ---------------------------------------------------------------------------

async def handle_callback_query(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """Processes Approve/Reject button clicks and resumes the LangGraph workflow.

    Deferred local import of job_agent_graph breaks the circular import:
      graph.py  imports  bot.py  at module level
      bot.py    imports  graph.py  only here, at call time
    """
    from core.graph import job_agent_graph

    query = update.callback_query
    await query.answer()

    # Auth guard — only the owner's Telegram account can approve applications
    user_id = update.effective_user.id
    if user_id != settings.TELEGRAM_CHAT_ID:
        logger.warning(f"Unauthorized interaction attempt from user ID {user_id}")
        return

    action, url_hash = query.data.split(":")
    original_caption = query.message.caption or ""

    if action == "approve":
        status_str = "APPROVED"
        new_caption = f"{original_caption}\n\n✅ *STATUS: APPROVED*\n_Saved to applications record._"
    else:
        status_str = "REJECTED"
        new_caption = f"{original_caption}\n\n❌ *STATUS: REJECTED*\n_Skipped target._"

    thread_config = {"configurable": {"thread_id": f"job_thread_{url_hash}"}}

    # Guard against stale callbacks from a previous container instance.
    # SqliteSaver persists checkpoints across restarts, so this should rarely
    # trigger — but if the DB was wiped or the job was never processed, we
    # handle it gracefully instead of crashing.
    existing_state = job_agent_graph.get_state(thread_config)
    if not existing_state.values or "url_hash" not in existing_state.values:
        logger.warning(
            f"[Bot] No checkpoint found for thread job_thread_{url_hash}. "
            "DB may have been reset. Marking REJECTED."
        )
        deduplicator.update_application_status(url_hash=url_hash, status="REJECTED")
        await query.edit_message_caption(
            caption=f"{original_caption}\n\n⚠️ *Session expired — decision could not be applied.*",
            parse_mode="Markdown",
            reply_markup=None,
        )
        return

    # Inject the human decision into the persisted checkpoint as if it came
    # from the send_telegram node, then resume the graph. LangGraph will run
    # finalize_application_node and reach END.
    job_agent_graph.update_state(
        thread_config,
        {"approval_status": status_str},
        as_node="send_telegram",
    )
    await job_agent_graph.ainvoke(None, config=thread_config)

    await query.edit_message_caption(
        caption=new_caption, parse_mode="Markdown", reply_markup=None
    )
    logger.info(f"[Bot] Application {url_hash} marked as {status_str} and graph resumed.")


# ---------------------------------------------------------------------------
# aiohttp HTTP handlers (webhook mode / Cloud Run only)
# ---------------------------------------------------------------------------

async def telegram_webhook_handler(request: web.Request) -> web.Response:
    """Receives Telegram update payloads pushed to POST /webhook.

    In webhook mode Telegram calls this endpoint instead of the bot polling.
    Cloud Run wakes the container on each incoming request, processes it,
    and the container may then be scaled down.
    """
    if _ctx.app is None:
        return web.Response(status=503, text="Bot not initialised")

    data = await request.json()
    update = Update.de_json(data, _ctx.app.bot)

    # Feed the update into the PTB dispatcher so all registered handlers fire
    await _ctx.app.process_update(update)
    return web.Response(status=200, text="ok")


async def sweep_handler(request: web.Request) -> web.Response:
    """Triggered by Cloud Scheduler (POST /sweep) to run a job discovery sweep.

    In polling mode the sweep is driven by APScheduler inside the process.
    In webhook mode APScheduler is removed and Cloud Scheduler calls this
    endpoint on the configured cron, keeping the container stateless.
    """
    # Import here to avoid a circular dependency at module load time
    from ingestion.scrappers import scrape_all_new_jobs
    from core.graph import job_agent_graph

    logger.info("[Sweep] Cloud Scheduler triggered sweep via HTTP.")
    try:
        new_jobs = await scrape_all_new_jobs()
        if not new_jobs:
            logger.info("[Sweep] No new jobs found.")
            return web.Response(status=200, text="no new jobs")

        for job in new_jobs:
            url_hash = job["url_hash"]
            initial_state = {
                "job_data": job,
                "url_hash": url_hash,
                "tailored_content": None,
                "pdf_path": None,
                "approval_status": "PENDING",
            }
            config = {"configurable": {"thread_id": f"job_thread_{url_hash}"}}
            try:
                await job_agent_graph.ainvoke(initial_state, config=config)
            except Exception as e:
                logger.error(f"[Sweep] Job {url_hash} failed: {e}")
                continue

        return web.Response(status=200, text=f"processed {len(new_jobs)} jobs")

    except Exception as e:
        logger.error(f"[Sweep] Sweep handler error: {e}", exc_info=True)
        return web.Response(status=500, text="sweep failed")


async def health_handler(request: web.Request) -> web.Response:
    """GET /health — used by Cloud Run to confirm the container is alive."""
    return web.Response(status=200, text="ok")


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def build_telegram_application() -> Application:
    """Builds the PTB Application, registers handlers, and stores the singleton."""
    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(handle_callback_query))
    set_telegram_app_instance(app)
    return app


def build_web_app() -> web.Application:
    """Builds the aiohttp web application used in webhook / Cloud Run mode.

    Routes:
      POST /webhook  — Telegram update payloads
      POST /sweep    — Cloud Scheduler job discovery trigger
      GET  /health   — Cloud Run liveness probe
    """
    web_app = web.Application()
    web_app.router.add_post("/webhook", telegram_webhook_handler)
    web_app.router.add_post("/sweep", sweep_handler)
    web_app.router.add_get("/health", health_handler)
    return web_app
