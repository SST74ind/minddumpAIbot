from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from config import TELEGRAM_BOT_TOKEN
from bot.handlers import start_handler, message_handler, tasks_command_handler, button_callback_handler, help_handler
from database.db import init_db
from database.scheduler import restore_pending_reminders

async def post_init(application):
    restore_pending_reminders(application)

def main():
    init_db()
    
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()
    
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