import asyncio
import logging
import os
import threading
import urllib.request
import zoneinfo
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    Defaults,
    filters,
)

from config import TELEGRAM_BOT_TOKEN
from bot.handlers import (
    start_handler,
    message_handler,
    tasks_command_handler,
    button_callback_handler,
    help_handler,
)
from database.db import init_db
from database.scheduler import restore_pending_reminders

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Define Indian Standard Time (IST)
IST = zoneinfo.ZoneInfo("Asia/Kolkata")


# Tiny HTTP server for Render health checks / uptime pingers
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def _ok(self, body=True):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        if body:
            self.wfile.write(b"MindDump AI is running!")

    def do_GET(self):
        self._ok()

    def do_HEAD(self):   # many uptime monitors use HEAD
        self._ok(body=False)

    def log_message(self, *args):   # keep the console clean
        pass


def run_dummy_server():
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHTTPRequestHandler)
    server.serve_forever()


def keep_awake():
    """On Render's free tier the service sleeps without inbound traffic. Ping our own public URL."""
    url = os.getenv("RENDER_EXTERNAL_URL")
    if not url:
        return
    import time
    while True:
        time.sleep(600)
        try:
            urllib.request.urlopen(url, timeout=15).read()
        except Exception as e:
            logger.warning("Keep-alive ping failed: %s", e)


async def post_init(application):
    restore_pending_reminders(application)


async def error_handler(update, context):
    logger.error("Unhandled error while processing an update", exc_info=context.error)


def main():
    threading.Thread(target=run_dummy_server, daemon=True).start()
    threading.Thread(target=keep_awake, daemon=True).start()

    init_db()

    defaults = Defaults(tzinfo=IST)

    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .defaults(defaults)
        .post_init(post_init)
        .build()
    )

    if app.job_queue is None:
        raise RuntimeError(
            "JobQueue missing - reminders cannot work. Run: pip install \"python-telegram-bot[job-queue]\""
        )

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("tasks", tasks_command_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CallbackQueryHandler(button_callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_error_handler(error_handler)

    # Newer Python versions (3.14+) no longer create an event loop implicitly
    asyncio.set_event_loop(asyncio.new_event_loop())

    logger.info("MindDump AI is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
