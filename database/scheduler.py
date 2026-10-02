from datetime import datetime
import zoneinfo
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from database.db import get_all_pending_tasks, mark_task_completed

# Define Indian Standard Time (IST)
IST_TZ = zoneinfo.ZoneInfo("Asia/Kolkata")


async def send_reminder_callback(context):
    """Callback function executed by Telegram JobQueue when timer expires."""
    job_data = context.job.data
    user_id = job_data["user_id"]
    title = job_data["title"]
    task_id = job_data.get("task_id", 0)

    # Interactive action buttons on the alert message
    keyboard = [
        [
            InlineKeyboardButton("✅ Done", callback_data=f"done_{task_id}"),
            InlineKeyboardButton("⏰ Snooze 10m", callback_data=f"snooze_{task_id}_10"),
            InlineKeyboardButton("⏰ Snooze 1h", callback_data=f"snooze_{task_id}_60"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Send push notification message
    await context.bot.send_message(
        chat_id=user_id,
        text=f"⏰ <b>MindDump Alert</b>\n\n<b>Task:</b> {title}\n\n<i>Select an action:</i>",
        parse_mode="HTML",
        reply_markup=reply_markup,
    )


def schedule_reminder(app, user_id: int, title: str, remind_at_iso: str, task_id: int = None):
    """Schedules a job in python-telegram-bot JobQueue."""
    try:
        # Parse target execution time
        target_dt = datetime.fromisoformat(remind_at_iso)

        # Force target_dt to be aware in IST
        if target_dt.tzinfo is None:
            target_dt = target_dt.replace(tzinfo=IST_TZ)

        # Get explicit current time in IST
        now = datetime.now(IST_TZ)
        delay = (target_dt - now).total_seconds()

        # If time is already past or execution is immediate (within 1 sec), trigger instantly
        if delay <= 0:
            delay = 1

        app.job_queue.run_once(
            send_reminder_callback,
            when=delay,
            data={"user_id": user_id, "title": title, "task_id": task_id},
        )
    except Exception as e:
        print(f"Scheduling Error: {e}")


def restore_pending_reminders(app):
    """Restores all pending database tasks into JobQueue on startup."""
    pending = get_all_pending_tasks()
    for task in pending:
        task_id, user_id, title, remind_at_iso, details, priority, status = task
        schedule_reminder(app, user_id, title, remind_at_iso, task_id=task_id)