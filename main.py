import asyncio
import logging
import signal
import sys
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from config import settings
from core.graph import job_agent_graph
from gateway.bot import build_telegram_application
from ingestion.scrappers import scrape_all_new_jobs

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("Main")


async def run_pipeline_sweep():
  """Executes a single job ingestion, CV tailoring, PDF rendering, and notification cycle."""
  logger.info("=== Starting Automated Job Discovery Sweep ===")

  try:
    # 1. Scrape new target jobs
    new_jobs = await scrape_all_new_jobs()
    if not new_jobs:
      logger.info("No new unique jobs discovered during this sweep.")
      return

    # 2. Process discovered jobs through LangGraph State Machine
    for job in new_jobs:
      url_hash = job["url_hash"]
      logger.info(
          f"Processing workflow for: {job['title']} at {job['company']}"
      )

      initial_state = {
          "job_data": job,
          "url_hash": url_hash,
          "tailored_content": None,
          "pdf_path": None,
          "approval_status": "PENDING",
      }

      # Unique thread config per job run ensures state persistence
      config = {"configurable": {"thread_id": f"job_thread_{url_hash}"}}

      # Execute LangGraph (Pauses before finalize_application at interrupt boundary)
      for event in job_agent_graph.stream(initial_state, config=config):
        logger.debug(f"Graph Event: {event}")

      logger.info(
          f"[✓] Initial state completed for {url_hash}. Awaiting human"
          " Telegram decision."
      )

  except Exception as e:
    logger.error(f"Error during execution sweep: {e}", exc_info=True)


async def main():
  """Main execution setup initializing DB, Telegram listener, and Cron scheduler."""
  logger.info(f"Initializing {settings.APP_NAME} Backend Engine...")

  # 1. Ensure SQLite schemas are initialized
  from data.db_init import init_sqlite_db

  init_sqlite_db()

  # 2. Build and start Telegram Bot polling engine in background
  telegram_app = build_telegram_application()
  await telegram_app.initialize()
  await telegram_app.start()
  await telegram_app.updater.start_polling()
  logger.info("[✓] Telegram Bot Listener initialized and polling.")

  # 3. Initialize background scheduler
  scheduler = AsyncIOScheduler()
  scheduler.add_job(
      run_pipeline_sweep,
      trigger="interval",
      hours=settings.CRON_INTERVAL_HOURS,
      id="job_discovery_job",
      replace_existing=True,
  )
  scheduler.start()
  logger.info(
      f"[✓] Cron Scheduler active: Sweeping every"
      f" {settings.CRON_INTERVAL_HOURS} hours."
  )

  # Trigger immediate execution sweep on startup
  asyncio.create_task(run_pipeline_sweep())

  # 4. Handle Graceful Shutdowns
  stop_event = asyncio.Event()

  def shutdown_signal():
    logger.info("Shutdown signal received. Cleaning up...")
    stop_event.set()

  loop = asyncio.get_running_loop()
  for sig in (signal.SIGINT, signal.SIGTERM):
    try:
      loop.add_signal_handler(sig, shutdown_signal)
    except NotImplementedError:
      pass  # Windows fallback

  await stop_event.wait()

  # Teardown logic
  scheduler.shutdown()
  await telegram_app.updater.stop()
  await telegram_app.stop()
  await telegram_app.shutdown()
  logger.info("System gracefully stopped.")


if __name__ == "__main__":
  try:
    asyncio.run(main())
  except (KeyboardInterrupt, SystemExit):
    logger.info("Program interrupted manually. Exiting...")