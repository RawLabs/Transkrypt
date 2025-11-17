from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Iterable, Optional

from telegram import Message, MessageEntity, Update
from telegram.constants import MessageEntityType
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from transkrypt import TranscriptError, TranscriptPDFBuilder, TranscriptService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

URL_PATTERN = re.compile(r"((?:https?://|www\.)[^\s]+)", re.IGNORECASE)


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Please export TELEGRAM_BOT_TOKEN before running the bot.")

    service = TranscriptService()
    pdf_builder = TranscriptPDFBuilder(output_dir="output")

    application: Application = ApplicationBuilder().token(token).build()
    application.bot_data["transcript_service"] = service
    application.bot_data["pdf_builder"] = pdf_builder

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("skrypt", skrypt))

    link_filter = (filters.TEXT | filters.CAPTION) & ~filters.COMMAND
    application.add_handler(MessageHandler(link_filter, direct_link_handler))

    logger.info("Bot is running. Waiting for updates...")
    application.run_polling(drop_pending_updates=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = (
        "Send me a link to a supported video or reply with /skrypt to a post that has one. "
        "I'll fetch the transcript, send you the timestamped version, and a polished paragraph view "
        "as a single PDF."
    )
    await update.effective_message.reply_text(message)


async def skrypt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    url = extract_url(update, context)
    if not url:
        await update.effective_message.reply_text(
            "I did not see a link. Use /skrypt <url> or reply to a message that contains one."
        )
        return
    await process_transcript_request(update, context, url)


async def direct_link_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    url = extract_url(update, context)
    if not url:
        return
    if update.message and update.message.text and update.message.text.startswith("/"):
        return
    await process_transcript_request(update, context, url)


async def process_transcript_request(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str) -> None:
    message = update.effective_message
    if message is None:
        return
    status = await message.reply_text("Fetching transcript… this can take a moment.")
    service: TranscriptService = context.application.bot_data["transcript_service"]
    pdf_builder: TranscriptPDFBuilder = context.application.bot_data["pdf_builder"]
    loop = asyncio.get_running_loop()

    try:
        summary = await loop.run_in_executor(None, lambda: service.fetch(url))
        pdf_path = await loop.run_in_executor(None, lambda: pdf_builder.build(summary))
    except TranscriptError as exc:
        await status.edit_text(f"Sorry, I couldn't fetch the transcript: {exc}")
        return
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Unexpected transcript failure")
        await status.edit_text("An unexpected error occurred while building the transcript.")
        return

    await status.edit_text("Transcript ready. Uploading the PDF…")
    caption = f"{summary.title}\nDuration: {summary.human_duration}\nSource: {summary.url}"
    with pdf_path.open("rb") as handle:
        await message.reply_document(document=handle, filename=pdf_path.name, caption=caption[:1024])
    await status.edit_text("Done ✅")


def extract_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    args = context.args if context.args else []
    if args:
        candidate = args[0]
        normalized = _normalize_url(candidate)
        if normalized.startswith("http"):
            return normalized

    message = update.effective_message
    url = _first_url_from_message(message)
    if url:
        return _normalize_url(url)
    if message and message.reply_to_message:
        replied = _first_url_from_message(message.reply_to_message)
        if replied:
            return _normalize_url(replied)
    return None


def _first_url_from_message(message: Optional[Message]) -> Optional[str]:
    if message is None:
        return None
    for entity, text in message.parse_entities(types=_URL_ENTITIES).items():
        if entity.type == MessageEntityType.TEXT_LINK and entity.url:
            return entity.url
        if text.startswith("http"):
            return text
    if message.caption:
        caption_entities = message.parse_caption_entities(types=_URL_ENTITIES)
        for entity, text in caption_entities.items():
            if entity.type == MessageEntityType.TEXT_LINK and entity.url:
                return entity.url
            if text.startswith("http"):
                return text
    text_sources = filter(None, [message.text, message.caption])
    for source in text_sources:
        match = URL_PATTERN.search(source)
        if match:
            return match.group(1)
    return None


def _normalize_url(value: str) -> str:
    value = value.strip().strip("[]()<>{}\"'.,")
    if value.startswith("www."):
        return f"https://{value}"
    return value


_URL_ENTITIES: Iterable[MessageEntityType] = (
    MessageEntityType.URL,
    MessageEntityType.TEXT_LINK,
)


if __name__ == "__main__":
    main()
