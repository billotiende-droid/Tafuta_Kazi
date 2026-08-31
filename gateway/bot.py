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
  """Dispatches generated PDF and job metadata to your Telegram chat with inline action buttons."""
  app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
  await app.initialize()

  caption = (
      f"🎯 *New Job Target Discovered*\n\n"
      f"*Role:* {job_title}\n"
      f"*Company:* {company}\n"
      f"*Link:* [View Job Posting]({job_url})\n\n"
      f"Review the attached CV below:"
  )

  # Attach hash to callback data for state mapping
  keyboard = [[
      InlineKeyboardButton(
          "✅ Approve", callback_data=f"approve:{url_hash}"
      ),
      InlineKeyboardButton("❌ Reject", callback_data=f"reject:{url_hash}"),
  ]]
  reply_markup = InlineKeyboardMarkup(keyboard)

  if Path(pdf_path).exists():
    with open(pdf_path, "rb") as doc:
      await app.bot.send_document(
          chat_id=settings.TELEGRAM_CHAT_ID,
          document=doc,
          filename=Path(pdf_path).name,
          caption=caption,
          parse_mode="Markdown",
          reply_markup=reply_markup,
      )
    logger.info(f"[Bot] Dispatched PDF for job hash {url_hash} to Telegram.")
  else:
    logger.error(f"[Bot] Target PDF file missing: {pdf_path}")

  await app.shutdown()


async def handle_callback_query(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
  """Processes clicks on Approve / Reject buttons."""
  query = update.callback_query
  await query.answer()

  user_id = update.effective_user.id
  if user_id != settings.TELEGRAM_CHAT_ID:
    logger.warning(f"Unauthorized interaction attempt from user ID {user_id}")
    return

  data = query.data
  action, url_hash = data.split(":")
  original_caption = query.message.caption or ""

  if action == "approve":
    status_str = "APPROVED"
    new_caption = (
        f"{original_caption}\n\n✅ *STATUS: APPROVED*\n_Saved to applications"
        " record._"
    )
  else:
    status_str = "REJECTED"
    new_caption = (
        f"{original_caption}\n\n❌ *STATUS: REJECTED*\n_Skipped target._"
    )

  # Persist decision directly to SQLite
  deduplicator.update_application_status(url_hash=url_hash, status=status_str)

  # Freeze message UI and update text
  await query.edit_message_caption(
      caption=new_caption, parse_mode="Markdown", reply_markup=None
  )
  logger.info(
      f"[Bot] Application {url_hash} marked as {status_str} by user action."
  )


def build_telegram_application() -> Application:
  """Builds and attaches event handlers to Telegram application instance."""
  app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
  app.add_handler(CommandHandler("start", start_command))
  app.add_handler(CallbackQueryHandler(handle_callback_query))
  return app