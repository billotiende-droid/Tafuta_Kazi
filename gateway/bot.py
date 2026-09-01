import logging
from pathlib import Path
from typing import Optional
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
    """Lightweight state container for the shared Telegram Application instance."""
    app: Optional[Application] = None


_ctx = BotContext()


def set_telegram_app_instance(app: Application) -> None:
    """Registers the running Telegram Application into the BotContext singleton."""
    _ctx.app = app


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Utility handler to retrieve and confirm your Telegram Chat ID."""
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"🤖 *Tafuta Kazi Bot Active*\nYour Chat ID: `{chat_id}`",
        parse_mode="Markdown",
    )


async def send_approval_request(
    pdf_path: str,
    job_title: str,
    company: str,
    job_url: str,
    url_hash: str,
) -> None:
    """Dispatches generated PDF and job metadata to Telegram using the shared bot instance."""
    if _ctx.app is None:
        raise RuntimeError(
            "Telegram app instance not set. Call set_telegram_app_instance() at startup."
        )

    # Path traversal mitigation: resolve and enforce OUTPUT_DIR boundary
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
    reply_markup = InlineKeyboardMarkup(keyboard)

    if resolved_path.exists():
        with open(resolved_path, "rb") as doc:
            await _ctx.app.bot.send_document(
                chat_id=settings.TELEGRAM_CHAT_ID,
                document=doc,
                filename=resolved_path.name,
                caption=caption,
                parse_mode="Markdown",
                reply_markup=reply_markup,
            )
        logger.info(f"[Bot] Dispatched PDF for job hash {url_hash} to Telegram.")
    else:
        logger.error(f"[Bot] Target PDF file missing: {resolved_path}")


async def handle_callback_query(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """Processes Approve/Reject button clicks and resumes the LangGraph workflow."""
    # Import here to avoid circular import at module load time
    from core.graph import job_agent_graph

    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    if user_id != settings.TELEGRAM_CHAT_ID:
        logger.warning(f"Unauthorized interaction attempt from user ID {user_id}")
        return

    action, url_hash = query.data.split(":")
    original_caption = query.message.caption or ""

    if action == "approve":
        status_str = "APPROVED"
        new_caption = (
            f"{original_caption}\n\n✅ *STATUS: APPROVED*\n_Saved to applications record._"
        )
    else:
        status_str = "REJECTED"
        new_caption = (
            f"{original_caption}\n\n❌ *STATUS: REJECTED*\n_Skipped target._"
        )

    thread_config = {"configurable": {"thread_id": f"job_thread_{url_hash}"}}

    # Inject human decision into the checkpointed graph state
    job_agent_graph.update_state(
        thread_config,
        {"approval_status": status_str},
        as_node="send_telegram",
    )

    # Resume graph from interrupt — runs finalize_application_node to completion
    await job_agent_graph.ainvoke(None, config=thread_config)

    # Update Telegram message UI to reflect final decision
    await query.edit_message_caption(
        caption=new_caption, parse_mode="Markdown", reply_markup=None
    )
    logger.info(f"[Bot] Application {url_hash} marked as {status_str} and graph resumed.")


def build_telegram_application() -> Application:
    """Builds, registers the singleton, and attaches event handlers to the Telegram application."""
    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(handle_callback_query))
    set_telegram_app_instance(app)
    return app
