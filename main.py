import asyncio
import logging
import signal

from aiohttp import web

from config import settings
from gateway.bot import build_telegram_application, build_web_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("Main")


# ---------------------------------------------------------------------------
# Shared pipeline sweep — called by both modes
# ---------------------------------------------------------------------------

async def run_pipeline_sweep():
    """Executes one full job discovery, tailoring, PDF, and Telegram dispatch cycle.

    In polling mode this is called by APScheduler on the configured interval.
    In webhook mode this is called by the /sweep HTTP handler triggered by
    Cloud Scheduler — the logic is identical, only the trigger differs.
    """
    from core.graph import job_agent_graph
    from ingestion.scrappers import scrape_all_new_jobs

    logger.info("=== Starting Automated Job Discovery Sweep ===")
    try:
        new_jobs = await scrape_all_new_jobs()
        if not new_jobs:
            logger.info("No new unique jobs discovered during this sweep.")
            return

        for job in new_jobs:
            url_hash = job["url_hash"]
            logger.info(f"Processing: {job['title']} at {job['company']}")

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
                logger.info(
                    f"[✓] Sweep complete for {url_hash}. Awaiting Telegram decision."
                )
            except Exception as e:
                # Per-job isolation: one failure must not abort the rest of the batch
                logger.error(f"[✗] Job {url_hash} failed and was skipped: {e}")
                continue

    except Exception as e:
        logger.error(f"Sweep error: {e}", exc_info=True)


# ---------------------------------------------------------------------------
# Mode A: Webhook (Cloud Run)
# ---------------------------------------------------------------------------

async def run_webhook_mode():
    """Starts the aiohttp HTTP server and registers the Telegram webhook.

    Cloud Run lifecycle:
      1. Container starts → this function runs
      2. aiohttp listens on 0.0.0.0:PORT (Cloud Run injects PORT)
      3. Telegram pushes updates to POST /webhook
      4. Cloud Scheduler calls POST /sweep every N hours
      5. Cloud Run scales the container down when idle

    No APScheduler is used here — Cloud Scheduler is the external cron.
    No polling loop is started — Telegram pushes updates instead.
    """
    logger.info(f"[Mode: Webhook] Starting on port {settings.PORT}")

    if not settings.WEBHOOK_URL:
        raise ValueError(
            "WEBHOOK_URL must be set in webhook mode. "
            "Set it to your Cloud Run service URL, e.g. "
            "https://tafuta-kazi-abc123-uc.a.run.app"
        )

    # Build and initialise the PTB application (no polling started)
    telegram_app = build_telegram_application()
    await telegram_app.initialize()
    await telegram_app.start()

    # Register the webhook URL with Telegram so it knows where to push updates.
    # Telegram will POST each update to {WEBHOOK_URL}/webhook.
    webhook_url = f"{settings.WEBHOOK_URL.rstrip('/')}/webhook"
    await telegram_app.bot.set_webhook(url=webhook_url)
    logger.info(f"[✓] Telegram webhook registered at {webhook_url}")

    # Build the aiohttp web app and run it on the Cloud Run injected PORT
    web_app = build_web_app()
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=settings.PORT)
    await site.start()
    logger.info(f"[✓] HTTP server listening on 0.0.0.0:{settings.PORT}")

    # Block until a shutdown signal is received
    stop_event = asyncio.Event()
    _register_signal_handlers(stop_event)
    await stop_event.wait()

    # Graceful teardown
    logger.info("Shutting down webhook mode...")
    await telegram_app.bot.delete_webhook()
    await runner.cleanup()
    await telegram_app.stop()
    await telegram_app.shutdown()
    logger.info("Webhook mode stopped cleanly.")


# ---------------------------------------------------------------------------
# Mode B: Polling (local development)
# ---------------------------------------------------------------------------

async def run_polling_mode():
    """Starts long-polling and APScheduler for local development.

    Nothing here requires an open port or a public URL — ideal for running
    on a laptop or a private server without a domain name.
    """
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    logger.info("[Mode: Polling] Starting local development mode.")

    # Initialise DB schemas on first run
    from data.db_init import init_sqlite_db
    init_sqlite_db()

    # Build and start the Telegram bot in polling mode.
    # Must be initialised before the first sweep fires so send_telegram_node
    # has a live bot instance to dispatch PDFs through.
    telegram_app = build_telegram_application()
    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.updater.start_polling()
    logger.info("[✓] Telegram bot polling started.")

    # APScheduler drives the sweep on the configured interval.
    # In webhook mode this is replaced by Cloud Scheduler + POST /sweep.
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_pipeline_sweep,
        trigger="interval",
        hours=settings.CRON_INTERVAL_HOURS,
        id="job_discovery_sweep",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        f"[✓] Scheduler active: sweeping every {settings.CRON_INTERVAL_HOURS} hours."
    )

    # Fire an immediate sweep on startup so you don't wait N hours for the first run
    asyncio.create_task(run_pipeline_sweep())

    stop_event = asyncio.Event()
    _register_signal_handlers(stop_event)
    await stop_event.wait()

    # Graceful teardown
    logger.info("Shutting down polling mode...")
    scheduler.shutdown()
    await telegram_app.updater.stop()
    await telegram_app.stop()
    await telegram_app.shutdown()
    logger.info("Polling mode stopped cleanly.")


# ---------------------------------------------------------------------------
# Signal handler helper
# ---------------------------------------------------------------------------

def _register_signal_handlers(stop_event: asyncio.Event) -> None:
    """Registers SIGINT/SIGTERM handlers to set the stop event for clean shutdown.

    NotImplementedError is caught for Windows, which does not support
    add_signal_handler on the asyncio event loop.
    """
    def _handle():
        logger.info("Shutdown signal received.")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle)
        except NotImplementedError:
            pass  # Windows fallback — KeyboardInterrupt will still work


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    logger.info(f"Initialising {settings.APP_NAME} [{settings.DEPLOYMENT_MODE} mode]...")

    if settings.DEPLOYMENT_MODE == "webhook":
        await run_webhook_mode()
    else:
        await run_polling_mode()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Process interrupted. Exiting.")
