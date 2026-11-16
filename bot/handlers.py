import asyncio
import html
import logging
from datetime import datetime, timedelta
import zoneinfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from engine.parser import parse_brain_dump
from database.db import (
    save_tasks, get_user_tasks, get_task, mark_task_completed, update_remind_time,
)
from database.scheduler import schedule_reminder, cancel_reminder

logger = logging.getLogger(__name__)

IST_TZ = zoneinfo.ZoneInfo("Asia/Kolkata")


def esc(value) -> str:
    """Escape user / AI generated text so Telegram's HTML parser never rejects the message."""
    return html.escape(str(value if value is not None else ""), quote=False)


def format_time(iso: str, with_seconds: bool = False) -> str:
    if not iso:
        return "No time set"
    try:
        dt = datetime.fromisoformat(iso)
        fmt = "%I:%M:%S %p | %b %d" if with_seconds else "%I:%M %p | %b %d"
        return dt.strftime(fmt)
    except Exception:
        return "No time set"


async def reply_chunked(message, text: str, **kwargs):
    """Telegram limits messages to 4096 chars - split on blank lines if needed."""
    while len(text) > 4000:
        cut = text.rfind("\n\n", 0, 4000)
        cut = cut if cut > 0 else 4000
        await message.reply_text(text[:cut], **kwargs)
        text = text[cut:].lstrip("\n")
    await message.reply_text(text, **kwargs)


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "⚡ <b>Welcome to MindDump AI!</b>\n\n"
        "Send your raw text dumps, and I will extract, schedule, and manage your tasks.\n\n"
        "<b>Commands:</b>\n"
        "/tasks - View pending tasks\n"
        "/help - Usage guidance",
        parse_mode="HTML",
    )


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if message is None or not message.text:
        return
    user_id = update.effective_user.id

    try:
        # The parser makes a blocking network call - run it off the event loop so the bot stays responsive
        parsed_data = await asyncio.to_thread(parse_brain_dump, message.text)
    except Exception:
        logger.exception("Parsing failed")
        await message.reply_text("⚠️ Something went wrong while reading that. Please try again.")
        return

    tasks = parsed_data.get("tasks", [])
    if not tasks:
        await message.reply_text("💬 <i>No actionable tasks detected.</i>", parse_mode="HTML")
        return

    # 1. Save first - we get the real task ids back directly (no fragile title matching)
    task_ids = save_tasks(user_id, tasks)

    reply_text = "✨ <b>Tasks Extracted & Scheduled:</b>\n\n"
    for i, (t, task_id) in enumerate(zip(tasks, task_ids), 1):
        remind_iso = t.get("remind_at_iso")
        ok = schedule_reminder(context.application, user_id, t.get("title"), remind_iso, task_id=task_id)
        time_label = format_time(remind_iso, with_seconds=True)
        if remind_iso and not ok:
            time_label += " (reminder could not be scheduled)"

        priority = t.get("priority")
        icon = "🔥" if priority == "High" else ("⚡" if priority == "Medium" else "💤")

        reply_text += (
            f"<b>{i}. {esc(t.get('title'))}</b> {icon}\n"
            f"⏰ <code>{esc(time_label)}</code>\n"
            f"📝 <i>{esc(t.get('details'))}</i>\n\n"
        )

    await reply_chunked(message, reply_text, parse_mode="HTML")


async def tasks_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user_id = update.effective_user.id
    rows = get_user_tasks(user_id)

    if not rows:
        await message.reply_text("🎉 You have no pending tasks!")
        return

    msg = "📋 <b>Your Pending Tasks:</b>\n\n"
    keyboard = []
    for task_id, _uid, title, remind_iso, _details, priority, _status in rows:
        msg += f"• <b>{esc(title)}</b> — <code>{esc(format_time(remind_iso))}</code> [{esc(priority)}]\n"
        keyboard.append([
            InlineKeyboardButton(f"✅ Done #{task_id}", callback_data=f"done_{task_id}"),
            InlineKeyboardButton("⏰ Snooze 10m", callback_data=f"snooze_{task_id}_10"),
        ])

    await message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    user_id = query.from_user.id
    parts = data.split("_")

    try:
        action = parts[0]
        task_id = int(parts[1])
    except (IndexError, ValueError):
        return

    task = get_task(task_id)
    if task is None or task[1] != user_id:
        await query.edit_message_text("⚠️ This task no longer exists.")
        return
    title = task[2]

    if action == "done":
        mark_task_completed(task_id)
        cancel_reminder(context.application, task_id)   # stop any reminder still queued
        await query.edit_message_text(
            f"✅ <b>Done:</b> {esc(title)}", parse_mode="HTML"
        )

    elif action == "snooze":
        try:
            snooze_mins = int(parts[2])
        except (IndexError, ValueError):
            snooze_mins = 10

        new_dt = datetime.now(IST_TZ) + timedelta(minutes=snooze_mins)
        new_iso = new_dt.strftime("%Y-%m-%dT%H:%M:%S")

        update_remind_time(task_id, new_iso)    # persist, so it survives a restart
        schedule_reminder(context.application, user_id, title, new_iso, task_id=task_id)
        await query.edit_message_text(
            f"⏰ <b>{esc(title)}</b> snoozed for {snooze_mins}m!\n"
            f"New reminder: <code>{new_dt.strftime('%I:%M:%S %p')}</code>",
            parse_mode="HTML",
        )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "🤖 <b>MindDump AI — Help & Guide</b>\n\n"
        "<b>How to use:</b>\n"
        "Simply type your raw brain dumps in natural language. I will extract tasks, detect priority, "
        "and schedule reminders automatically!\n\n"
        "<b>Examples:</b>\n"
        "• <i>Remind me to call Mom in 30 seconds</i>\n"
        "• <i>Submit Physics assignment tomorrow at 9am and buy groceries at 6pm</i>\n\n"
        "<b>Available Commands:</b>\n"
        "/start - Welcome message and quick start\n"
        "/tasks - View all active pending tasks with interactive controls\n"
        "/help - Display this help manual",
        parse_mode="HTML",
    )
