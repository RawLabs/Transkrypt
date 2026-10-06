# Transkrypt

A Telegram bot that downloads video transcripts (via `yt-dlp`), keeps the original timestamps, and also produces a polished paragraph-style summary. Both versions are bundled into a single PDF so users always receive one document containing the raw+human-friendly views.

## Quick start

With the bot running, open its Telegram chat:

1. Send `/skrypt <video-link>`, or reply to a post containing a video link with `/skrypt`.
2. In a private chat, you can also send or forward the link without a command.
3. The bot sends back one PDF containing the timestamped transcript and a
   cleaned paragraph version. Use `/start` for a reminder of the commands.

The video needs captions available through `yt-dlp`. Finished PDFs are also
kept in `output/`. To host your own bot, follow [installation](#installation).

## Installation

You need Python 3.11+ and a Telegram bot token from [BotFather](https://t.me/BotFather).
From the project root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install python-telegram-bot yt-dlp
export TELEGRAM_BOT_TOKEN="your-bot-token-here"
python bot.py
```

The entry point reads the token from the environment. Set it before launching
the process; keep actual tokens out of Git.

## Features

- `/skrypt` command works directly or in reply to a message that contains a link.
- Accepts forwarded posts or direct messages that include a video URL (YouTube and any source supported by `yt-dlp`).
- Automatically cleans caption text, builds timestamped lines, and groups sentences into readable paragraphs.
- Generates a lightweight PDF (no extra dependencies) with metadata, the timestamped transcript, and the polished version.
- Stores generated PDFs inside `output/` so the bot can re-upload or audit transcripts later.

## Customising

- **Preferred languages:** adjust `preferred_langs` in `TranscriptService()` if you need languages other than English.
- **Output directory:** change the `TranscriptPDFBuilder(output_dir=...)` argument in `bot.py`.
- **Formatting:** tweak `_build_paragraphs` inside `transkrypt/transcript_service.py` for different chunk sizes or punctuation rules. The PDF layout lives in `transkrypt/pdf_writer.py`.

## Notes

- The bot relies on transcripts/subtitles exposed via `yt-dlp`. Some videos simply do not ship captions; those requests will return an informative error.
- No third-party PDF engine is required; a small embedded writer (`_SimplePDF`) handles plain-text reports, which keeps the deployment minimal.
