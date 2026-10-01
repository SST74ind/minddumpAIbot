import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import zoneinfo
from telegram.ext import (
    ApplicationBuilder, 
    CommandHandler, 
    MessageHandler, 
    CallbackQueryHandler, 
    Defaults, 
    filters
)
from config import TELEGRAM_BOT_TOKEN
from bot.handlers import (
    start_handler, 
    message_handler, 
    tasks_command_handler, 
    button_callback_handler, 
    help_handler
)
from database.db import init_db
from database.scheduler import restore_pending_reminders

# Define Indian Standard Time (IST)
IST = zoneinfo.ZoneInfo("Asia/Kolkata")


# Dummy HTTP server for Render Web Service health checks
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"MindDump AI is running!")


def run_dummy_server():
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHTTPRequestHandler)
    server.serve_forever()


async def post_init(application):
    restore_pending_reminders(application)


def main():
    # Start the dummy web server thread for Render health checks
    threading.Thread(target=run_dummy_server, daemon=True).start()

    # Initialize SQLite database
    init_db()

    # Configure global defaults with Asia/Kolkata timezone attached
    defaults = Defaults(tzinfo=IST)

    # Build Application
    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .defaults(defaults)
        .post_init(post_init)
        .build()
    )

    # Registered Commands
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("tasks", tasks_command_handler))
    app.add_handler(CommandHandler("help", help_handler))

    # Callback & Message Handlers
    app.add_handler(CallbackQueryHandler(button_callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    print("MindDump AI is running...")
    app.run_polling()


if __name__ == "__main__":
    main()