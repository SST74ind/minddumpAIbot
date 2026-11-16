import html
import logging
from datetime import datetime
import zoneinfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from database.db import get_all_pending_tasks, get_task, mark_reminded

logger = logging.getLogger(__name__)

IST_TZ = zoneinfo.ZoneInfo("Asia/Kolkata")


def _job_name(task_id: int) -> str:
    return f"reminder_{task_id}"


def cancel_reminder(app, task_id: int):
    """Remove any scheduled reminder jobs for this task (used on Done / Snooze / reschedule)."""
    if not task_id or app.job_queue is None:
        return
    for job in app.job_queue.get_jobs_by_name(_job_name(task_id)):
        job.schedule_removal()


async def send_reminder_callback(context):
    """Executed by Telegram JobQueue when the timer expires."""
    job_data = context.job.data
    user_id = job_data["user_id"]
    title = job_data["title"]
    task_id = job_data.get("task_id", 0)

    # Skip if the task was completed (or deleted) after this job was scheduled
    if task_id:
        task = get_task(task_id)
        if task is None or task[6] != "pending":
            return
        title = task[2] or title

    keyboard = [[
        InlineKeyboardButton("✅ Done", callback_data=f"done_{task_id}"),
        InlineKeyboardButton("⏰ Snooze 10m", callback_data=f"snooze_{task_id}_10"),
        InlineKeyboardButton("⏰ Snooze 1h", callback_data=f"snooze_{task_id}_60"),
    ]]

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                f"⏰ <b>MindDump Alert</b>\n\n<b>Task:</b> {html.escape(str(title))}\n\n"
                "<i>Select an action:</i>"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    except Exception:
        logger.exception("Could not send reminder for task %s", task_id)
        return

    if task_id:
        mark_reminded(task_id)


def schedule_reminder(app, user_id: int, title: str, remind_at_iso: str,
                      task_id: int = 0, min_delay: float = 1) -> bool:
    """Schedules a job in python-telegram-bot's JobQueue. Returns True on success."""
    if app.job_queue is None:
        logger.error(
            "JobQueue is not available - install with: pip install \"python-telegram-bot[job-queue]\""
        )
        return False
    if not remind_at_iso:
        return False
    try:
        target_dt = datetime.fromisoformat(remind_at_iso)
        if target_dt.tzinfo is None:
            target_dt = target_dt.replace(tzinfo=IST_TZ)

        delay = (target_dt - datetime.now(IST_TZ)).total_seconds()
        if delay < min_delay:
            delay = min_delay

        # Never keep two jobs for the same task (e.g. snooze while the original is still pending)
        cancel_reminder(app, task_id)

        app.job_queue.run_once(
            send_reminder_callback,
            when=delay,
            name=_job_name(task_id) if task_id else None,
            data={"user_id": user_id, "title": title, "task_id": task_id},
        )
        return True
    except Exception:
        logger.exception("Scheduling error for task %s", task_id)
        return False


def restore_pending_reminders(app):
    """Re-creates JobQueue jobs for tasks that are still waiting for their reminder (runs on startup)."""
    pending = get_all_pending_tasks()
    overdue = 0
    for task_id, user_id, title, remind_at_iso, details, priority, status in pending:
        try:
            dt = datetime.fromisoformat(remind_at_iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=IST_TZ)
            is_overdue = dt <= datetime.now(IST_TZ)
        except Exception:
            continue
        if is_overdue:
            overdue += 1
            delay = 3 + overdue * 2   # stagger so a long outage doesn't flood the chat
        else:
            delay = 1
        schedule_reminder(app, user_id, title, remind_at_iso, task_id=task_id, min_delay=delay)
    logger.info("Restored %d pending reminder(s) (%d overdue).", len(pending), overdue)
