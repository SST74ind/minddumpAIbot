import json
import re
import logging
from datetime import datetime, timedelta
import zoneinfo
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from config import GEMINI_API_KEY

# Define Indian Standard Time (IST) timezone
IST_TZ = zoneinfo.ZoneInfo("Asia/Kolkata")

# Expanded verbs list to catch more natural task phrasings
TASK_VERBS = [
    "remind", "bring", "buy", "call", "do", "finish", "complete", 
    "submit", "pay", "clean", "pick", "drop", "meet", "send", "write", 
    "eat", "go", "have", "take", "check", "attend", "study", "prep", "prepare"
]

class TaskItem(BaseModel):
    title: str = Field(description="Clear title of the action item")
    remind_at_iso: str = Field(description="Exact ISO 8601 string (YYYY-MM-DDTHH:MM:SS) calculated relative to reference time")
    details: str = Field(description="Original context snippet")
    priority: str = Field(description="High, Medium, or Low")

class TaskList(BaseModel):
    tasks: list[TaskItem]

def parse_single_segment(segment: str, now: datetime) -> dict:
    remind_time = None
    
    # 1. Match relative seconds
    sec_match = re.search(r"\b(\d+)\s*(?:seconds?|secs?|s)\b", segment, re.IGNORECASE)
    if sec_match:
        remind_time = now + timedelta(seconds=int(sec_match.group(1)))

    # 2. Match relative minutes
    if not remind_time:
        min_match = re.search(r"\b(\d+)\s*(?:minutes?|mins?|m)\b", segment, re.IGNORECASE)
        if min_match:
            remind_time = now + timedelta(minutes=int(min_match.group(1)))

    # 3. Match relative hours
    if not remind_time:
        hr_match = re.search(r"\b(\d+)\s*(?:hours?|hrs?|h)\b", segment, re.IGNORECASE)
        if hr_match:
            remind_time = now + timedelta(hours=int(hr_match.group(1)))

    # 4. Match clock times (handles "11:30 pm", "11 30 pm", "9am", "9 am")
    if not remind_time:
        time_match = re.search(r"\b(\d{1,2})(?:[:\s](\d{2}))?\s*(am|pm)\b", segment, re.IGNORECASE)
        if time_match:
            hr = int(time_match.group(1))
            mn = int(time_match.group(2)) if time_match.group(2) else 0
            period = time_match.group(3).lower()
            if period == "pm" and hr < 12:
                hr += 12
            elif period == "am" and hr == 12:
                hr = 0
            
            target_date = now.date()
            if "tomorrow" in segment.lower():
                target_date += timedelta(days=1)
                
            remind_time = datetime.combine(target_date, datetime.min.time()).replace(hour=hr, minute=mn, tzinfo=IST_TZ)
            
            # If calculated time for today already passed, push to tomorrow automatically
            if remind_time <= now and "today" not in segment.lower():
                remind_time += timedelta(days=1)

    # Fallback default if no explicit time offset matched
    if not remind_time:
        remind_time = now + timedelta(hours=2)

    # Clean task title
    title = segment
    title = re.sub(r"(?i)\bremind\s+me\s+to\b", "", title)
    title = re.sub(r"(?i)\b(?:in|after)\s*\d+\s*(?:seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h)\b", "", title)
    title = re.sub(r"(?i)\b(?:at|by)\s*\d+(?:[:\s]\d+)?\s*(?:am|pm)\b", "", title)
    title = re.sub(r"(?i)\b(?:today|tomorrow)\b", "", title)
    title = title.strip(" ,.")

    priority = "High" if any(w in segment.lower() for w in ["submit", "assignment", "urgent", "exam", "test", "physics", "lab"]) else "Medium"

    return {
        "title": title.capitalize() if title else "Task",
        "remind_at_iso": remind_time.strftime("%Y-%m-%dT%H:%M:%S"),
        "details": segment.strip(),
        "priority": priority
    }

def parse_local_fallback(raw_text: str) -> dict:
    text_lower = raw_text.lower().strip()
    
    has_verb = any(verb in text_lower for verb in TASK_VERBS)
    has_time = any(kw in text_lower for kw in ["in ", "after ", "tomorrow", "tonight", "today", "at ", "sec", "min", "hour", "day", "am", "pm"])
    
    if not (has_verb or has_time):
        return {"tasks": []}

    now = datetime.now(IST_TZ)
    segments = re.split(r"\s+(?:and|then|also)\s+|,\s*", raw_text, flags=re.IGNORECASE)
    tasks = [parse_single_segment(seg, now) for seg in segments if seg.strip()]

    return {"tasks": tasks}

def parse_brain_dump(raw_text: str) -> dict:
    # Use explicit IST current time
    now = datetime.now(IST_TZ)
    now_str = now.strftime("%A, %Y-%m-%d %H:%M:%S")

    prompt = f"""
    Current Reference Time: {now_str} (IST - Asia/Kolkata)
    Input Text: "{raw_text}"

    If the text is casual conversation, return {{"tasks": []}}.
    Otherwise extract all actionable tasks and compute future ISO timestamps (YYYY-MM-DDTHH:MM:SS) for remind_at_iso based strictly on the reference time above.
    If a requested clock time today has already passed, set the timestamp for that time tomorrow.
    """

    try:
        if not GEMINI_API_KEY or GEMINI_API_KEY == "YOUR_GEMINI_KEY":
            return parse_local_fallback(raw_text)

        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=TaskList
            )
        )
        parsed = json.loads(response.text.strip())
        if not parsed.get("tasks"):
            return parse_local_fallback(raw_text)
            
        # Post-process past or tight timestamps to prevent silent failures
        for t in parsed["tasks"]:
            try:
                # Parse output ISO string and enforce IST comparison
                dt = datetime.fromisoformat(t["remind_at_iso"])
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=IST_TZ)

                if dt <= now:
                    # Provide a 10-second buffer if target time passed due to execution latency
                    t["remind_at_iso"] = (now + timedelta(seconds=10)).strftime("%Y-%m-%dT%H:%M:%S")
            except Exception:
                continue

        return parsed

    except Exception as e:
        logging.error(f"Fallback active due to Gemini API issue: {e}")
        return parse_local_fallback(raw_text)