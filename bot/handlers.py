from datetime import datetime, timedelta
import zoneinfo
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from engine.parser import parse_brain_dump
from database.db import save_tasks, get_user_tasks, mark_task_completed, get_all_pending_tasks
from database.scheduler import schedule_reminder

# Define explicit IST timezone
IST_TZ = zoneinfo.ZoneInfo("Asia/Kolkata")

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚡ <b>Welcome to MindDump AI!</b>\n\n"
        "Send your raw text dumps, and I will extract, schedule, and manage your tasks.\n\n"
        "<b>Commands:</b>\n"
        "/tasks - View pending tasks\n"
        "/help - Usage guidance",
        parse_mode="HTML"
    )

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    raw_text = update.message.text

    parsed_data = parse_brain_dump(raw_text)
    tasks = parsed_data.get("tasks", [])

    if not tasks:
        await update.message.reply_text("💬 <i>No actionable tasks detected.</i>", parse_mode="HTML")
        return

    # 1. Save tasks to SQLite first
    save_tasks(user_id, tasks)

    # 2. Retrieve newly inserted DB records to get valid task_ids
    user_db_tasks = get_user_tasks(user_id)
    
    reply_text = "✨ <b>Tasks Extracted & Scheduled:</b>\n\n"
    for i, t in enumerate(tasks, 1):
        remind_time_raw = t.get("remind_at_iso")
        formatted_time = "No time set"
        
        # Match task with DB record to get real task_id
        matched_db_task = next((db_t for db_t in reversed(user_db_tasks) if db_t[2] == t.get("title")), None)
        task_id = matched_db_task[0] if matched_db_task else 0

        if remind_time_raw:
            dt_obj = datetime.fromisoformat(remind_time_raw)
            if dt_obj.tzinfo is None:
                dt_obj = dt_obj.replace(tzinfo=IST_TZ)
            formatted_time = dt_obj.strftime("%I:%M:%S %p | %b %d")
            
            # Pass task_id into scheduler
            schedule_reminder(context.application, user_id, t.get("title"), remind_time_raw, task_id=task_id)

        priority_icon = "🔥" if t.get("priority") == "High" else ("⚡" if t.get("priority") == "Medium" else "💤")

        reply_text += (
            f"<b>{i}. {t.get('title')}</b> {priority_icon}\n"
            f"⏰ <code>{formatted_time}</code>\n"
            f"📝 <i>{t.get('details')}</i>\n\n"
        )

    await update.message.reply_text(reply_text, parse_mode="HTML")

async def tasks_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    rows = get_user_tasks(user_id)

    if not rows:
        await update.message.reply_text("🎉 You have no pending tasks!")
        return

    msg = "📋 <b>Your Pending Tasks:</b>\n\n"
    keyboard = []

    for row in rows:
        task_id, u_id, title, remind_iso, details, priority, status = row
        dt_str = "N/A"
        if remind_iso:
            dt_obj = datetime.fromisoformat(remind_iso)
            if dt_obj.tzinfo is None:
                dt_obj = dt_obj.replace(tzinfo=IST_TZ)
            dt_str = dt_obj.strftime("%I:%M %p | %b %d")
        
        msg += f"• <b>{title}</b> — <code>{dt_str}</code> [{priority}]\n"
        
        keyboard.append([
            InlineKeyboardButton(f"✅ Done #{task_id}", callback_data=f"done_{task_id}"),
            InlineKeyboardButton(f"⏰ Snooze 10m", callback_data=f"snooze_{task_id}_10")
        ])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode="HTML")

async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = query.from_user.id

    if data.startswith("done_"):
        task_id = int(data.split("_")[1])
        if task_id > 0:
            mark_task_completed(task_id)
        await query.edit_message_text("✅ <b>Task marked as completed!</b>", parse_mode="HTML")

    elif data.startswith("snooze_"):
        parts = data.split("_")
        task_id = int(parts[1])
        snooze_mins = int(parts[2])

        # Calculate snooze target explicitly in IST
        new_dt = datetime.now(IST_TZ) + timedelta(minutes=snooze_mins)
        new_iso = new_dt.strftime("%Y-%m-%dT%H:%M:%S")

        schedule_reminder(context.application, user_id, f"Snoozed Task #{task_id}", new_iso, task_id=task_id)
        await query.edit_message_text(
            f"⏰ <b>Task snoozed for {snooze_mins}m!</b>\nNew Reminder: <code>{new_dt.strftime('%I:%M:%S %p')}</code>",
            parse_mode="HTML"
        )
        
async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🤖 <b>MindDump AI — Help & Guide</b>\n\n"
        "<b>How to use:</b>\n"
        "Simply type your raw brain dumps in natural language. I will extract tasks, detect priority, and schedule reminders automatically!\n\n"
        "<b>Examples:</b>\n"
        "• <i>Remind me to call Mom in 30 seconds</i>\n"
        "• <i>Submit Physics assignment tomorrow at 9am and buy groceries at 6pm</i>\n\n"
        "<b>Available Commands:</b>\n"
        "/start - Welcome message and quick start\n"
        "/tasks - View all active pending tasks with interactive controls\n"
        "/help - Display this help manual"
    )
    await update.message.reply_text(help_text, parse_mode="HTML")