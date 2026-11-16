# MindDump AI (Telegram bot)

Send a messy text dump -> the bot extracts tasks, sets reminders (IST), and lets you mark Done / Snooze.

## Setup
1. `pip install -r requirements.txt`  (must include `python-telegram-bot[job-queue]`, otherwise reminders can't fire)
2. Copy `.env.example` to `.env` and fill in `TELEGRAM_BOT_TOKEN` and `GEMINI_API_KEY`
3. `python main.py`

## Render notes
- Run only ONE instance of the bot (local + Render at the same time causes Telegram "Conflict" errors).
- Free-tier disk is wiped on restart/redeploy: tasks are lost. Attach a persistent disk and set
  `DATABASE_PATH=/var/data/minddump.db`.
- Free web services sleep when idle; the bot self-pings `RENDER_EXTERNAL_URL` (set automatically by Render),
  and you can also point UptimeRobot at the service URL.
- `GEMINI_MODEL` (optional) forces a model; otherwise newer models are tried first and retired ones are skipped.
