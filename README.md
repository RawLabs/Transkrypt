# Transkrypt

A Telegram bot that downloads video transcripts (via `yt-dlp`), keeps the original timestamps, and also produces a polished paragraph-style summary. Both versions are bundled into a single PDF so users always receive one document containing the raw+human-friendly views.

## Features
- `/skrypt` command works directly or in reply to a message that contains a link.
- Accepts forwarded posts or direct messages that include a video URL (YouTube and any source supported by `yt-dlp`).
- Automatically cleans caption text, builds timestamped lines, and groups sentences into readable paragraphs.
- Generates a lightweight PDF (no extra dependencies) with metadata, the timestamped transcript, and the polished version.
- Stores generated PDFs inside `output/` so the bot can re-upload or audit transcripts later.

## Prerequisites
- Python 3.11+
- Packages already available in the provided environment:  
  `python-telegram-bot`, `yt-dlp`
- Telegram bot token from [BotFather](https://t.me/BotFather).

## Running the bot
1. Export your bot token (or set it in your `.env`):
   ```bash
   export TELEGRAM_BOT_TOKEN=123456789:ABCDEF...
   ```
2. Start the bot from the project root:
   ```bash
   python bot.py
   ```
3. Interact from Telegram:
   - `/start` shows basic instructions.
   - `/skrypt <link>` runs directly in any chat.
   - Reply to a message (or forwarded post) that has a video link with `/skrypt`.
   - Send/forward a link to the bot in a private chat without any command; it will pick it up automatically.

All finished transcripts will be saved as `output/<video-id>-<sanitized-title>.pdf` and sent back to the chat.

## Customising
- **Preferred languages:** adjust `preferred_langs` in `TranscriptService()` if you need languages other than English.
- **Output directory:** change the `TranscriptPDFBuilder(output_dir=...)` argument in `bot.py`.
- **Formatting:** tweak `_build_paragraphs` inside `transkrypt/transcript_service.py` for different chunk sizes or punctuation rules. The PDF layout lives in `transkrypt/pdf_writer.py`.

## Notes
- The bot relies on transcripts/subtitles exposed via `yt-dlp`. Some videos simply do not ship captions; those requests will return an informative error.
- No third-party PDF engine is required; a small embedded writer (`_SimplePDF`) handles plain-text reports, which keeps the deployment minimal.
