import json
import re
import logging
from datetime import datetime, timedelta
import zoneinfo

from pydantic import BaseModel, Field
from google import genai
from google.genai import types

from config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)

# Define Indian Standard Time (IST) timezone
IST_TZ = zoneinfo.ZoneInfo("Asia/Kolkata")

# Tried in order until one works (older models get retired; a 404 just moves on to the next).
# Set GEMINI_MODEL in .env to force a specific one.
MODEL_CANDIDATES = [m for m in [
    GEMINI_MODEL,
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash",
] if m]
_working_model = None

TASK_VERBS = [
    "remind", "bring", "buy", "call", "finish", "complete", "submit", "pay", "clean",
    "pick", "drop", "meet", "send", "write", "eat", "go", "have", "take", "check",
    "attend", "study", "prep", "prepare", "get", "make", "book", "visit", "read",
    "wash", "fill", "sleep", "wake", "revise", "practice", "charge", "print", "return",
    "cook", "renew", "water", "exercise", "walk", "message", "email", "text", "order",
    "fix", "update", "do",
]
_VERB_ALT = "|".join(sorted(set(TASK_VERBS), key=len, reverse=True))
_VERB_RE = re.compile(rf"\b(?:{_VERB_ALT})\b", re.IGNORECASE)
# split "A and buy B", "A then B", "A; B", "A, call B" - but not "Mom and Dad" or "tomorrow, 9am"
_SPLIT_RE = re.compile(
    rf"\s+(?:and\s+then|then|also)\s+|\s+and\s+(?=(?:{_VERB_ALT})\b)|\s*;\s*|,\s*(?=(?:{_VERB_ALT})\b)",
    re.IGNORECASE,
)


class TaskItem(BaseModel):
    title: str = Field(description="Clear title of the action item")
    remind_at_iso: str = Field(description="Exact ISO 8601 string (YYYY-MM-DDTHH:MM:SS) calculated relative to reference time")
    details: str = Field(description="Original context snippet")
    priority: str = Field(description="High, Medium, or Low")


class TaskList(BaseModel):
    tasks: list[TaskItem]


# ---------------------------------------------------------------- local fallback parser

def _find_relative_time(segment: str, now: datetime):
    s = segment.lower()

    m = re.search(r"\b(\d+)\s*(?:seconds?|secs?)\b|\b(\d+)s\b", s)
    if m:
        return now + timedelta(seconds=int(m.group(1) or m.group(2)))

    if re.search(r"\bhalf an hour\b|\bhalf hour\b", s):
        return now + timedelta(minutes=30)

    m = re.search(r"\b(\d+)\s*(?:minutes?|mins?)\b|\b(\d+)m\b", s)
    if m:
        return now + timedelta(minutes=int(m.group(1) or m.group(2)))

    if re.search(r"\b(?:in|after)\s+an?\s+hour\b", s):
        return now + timedelta(hours=1)
    m = re.search(r"\b(\d+)\s*(?:hours?|hrs?)\b|\b(\d+)h\b", s)
    if m:
        return now + timedelta(hours=int(m.group(1) or m.group(2)))

    m = re.search(r"\b(?:in|after)\s+(\d+)\s*days?\b", s)
    if m:
        return now + timedelta(days=int(m.group(1)))
    return None


def _find_clock_time(segment: str, now: datetime):
    s = segment.lower()
    hr = mn = None

    m = re.search(r"\b(\d{1,2})(?:[:.\s](\d{2}))?\s*(am|pm)\b", s)
    if m:
        hr = int(m.group(1))
        mn = int(m.group(2)) if m.group(2) else 0
        period = m.group(3)
        if hr < 1 or hr > 12 or mn > 59:
            return None
        if period == "pm" and hr < 12:
            hr += 12
        elif period == "am" and hr == 12:
            hr = 0
    else:
        m = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", s)   # 24h style: 17:30
        if m:
            hr, mn = int(m.group(1)), int(m.group(2))

    if hr is None:
        # No clock time. Handle "tonight" / bare "tomorrow"
        if "tonight" in s:
            return now.replace(hour=21, minute=0, second=0, microsecond=0)
        if "tomorrow" in s:
            return (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        return None

    target_date = now.date()
    if "tomorrow" in s:
        target_date += timedelta(days=1)
    remind_time = datetime(target_date.year, target_date.month, target_date.day, hr, mn, tzinfo=IST_TZ)

    # If today's time already passed, push to tomorrow (unless the user explicitly said "today")
    if remind_time <= now and "today" not in s and "tomorrow" not in s:
        remind_time += timedelta(days=1)
    return remind_time


def parse_single_segment(segment: str, now: datetime) -> dict:
    remind_time = _find_relative_time(segment, now) or _find_clock_time(segment, now)
    if not remind_time:
        remind_time = now + timedelta(hours=2)   # no time mentioned -> default

    # Clean the task title
    title = segment
    title = re.sub(r"(?i)\bremind\s+me\s+(?:to|about)\b", "", title)
    title = re.sub(r"(?i)\b(?:in|after)\s+(?:an?|half an?|\d+)\s*(?:seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|hour)\b", "", title)
    title = re.sub(r"(?i)\b(?:at|by)\s*\d{1,2}(?:[:.\s]\d{2})?\s*(?:am|pm)?\b", "", title)
    title = re.sub(r"(?i)\b\d{1,2}(?:[:.\s]\d{2})?\s*(?:am|pm)\b", "", title)
    title = re.sub(r"(?i)\b(?:today|tomorrow|tonight)\b", "", title)
    title = re.sub(r"\s+", " ", title).strip(" ,.;:-")
    title = (title[0].upper() + title[1:]) if title else "Task"

    low = segment.lower()
    high_words = ["submit", "assignment", "urgent", "exam", "test", "physics", "lab", "deadline", "asap", "important"]
    priority = "High" if any(w in low for w in high_words) else "Medium"

    return {
        "title": title,
        "remind_at_iso": remind_time.strftime("%Y-%m-%dT%H:%M:%S"),
        "details": segment.strip(" ,;"),
        "priority": priority,
    }


def parse_local_fallback(raw_text: str) -> dict:
    text = raw_text.strip()
    if not text or text.endswith("?") or not _VERB_RE.search(text):
        return {"tasks": []}

    now = datetime.now(IST_TZ)
    segments = [s for s in _SPLIT_RE.split(text) if s and s.strip()]
    return {"tasks": [parse_single_segment(seg, now) for seg in segments]}


# ---------------------------------------------------------------- Gemini parser

def _call_gemini(prompt: str):
    """Try the configured models in order; move on if a model is retired (404) or rate limited (429)."""
    global _working_model
    client = genai.Client(api_key=GEMINI_API_KEY, http_options=types.HttpOptions(timeout=20000))

    models = list(MODEL_CANDIDATES)
    if _working_model in models:
        models.remove(_working_model)
        models.insert(0, _working_model)

    last_error = None
    for model in models:
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=TaskList,
                ),
            )
            if not response.text:
                raise ValueError("Empty response from Gemini")
            _working_model = model
            return response
        except Exception as e:
            last_error = e
            msg = str(e)
            if any(k in msg for k in ("404", "NOT_FOUND", "no longer available", "429", "RESOURCE_EXHAUSTED")):
                logger.warning("Gemini model %s unavailable (%s) - trying next", model, msg[:120])
                continue
            raise
    raise last_error


def _normalise_task(t: dict, now: datetime) -> dict:
    """Make sure every field exists, the time is IST-naive ISO, and it is in the future."""
    title = str(t.get("title") or "Task").strip() or "Task"
    details = str(t.get("details") or title).strip()
    priority = str(t.get("priority") or "Medium").strip().capitalize()
    if priority not in ("High", "Medium", "Low"):
        priority = "Medium"

    try:
        dt = datetime.fromisoformat(str(t.get("remind_at_iso")))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST_TZ)
        else:
            dt = dt.astimezone(IST_TZ)
    except Exception:
        dt = now + timedelta(hours=2)

    if dt <= now:
        if (now - dt).total_seconds() <= 120:
            dt = now + timedelta(seconds=10)    # tiny lag from the API call
        else:
            # The model picked a time that has already passed (e.g. wrong day) -> next occurrence
            while dt <= now:
                dt += timedelta(days=1)

    return {
        "title": title,
        "remind_at_iso": dt.strftime("%Y-%m-%dT%H:%M:%S"),
        "details": details,
        "priority": priority,
    }


def parse_brain_dump(raw_text: str) -> dict:
    now = datetime.now(IST_TZ)
    now_str = now.strftime("%A, %Y-%m-%d %H:%M:%S")

    if not GEMINI_API_KEY or GEMINI_API_KEY == "YOUR_GEMINI_KEY":
        return parse_local_fallback(raw_text)

    prompt = f"""
    Current Reference Time: {now_str} (IST - Asia/Kolkata)
    Input Text: {json.dumps(raw_text)}

    If the text is casual conversation or a question with no action to do, return {{"tasks": []}}.
    Otherwise extract all actionable tasks and compute future ISO timestamps (YYYY-MM-DDTHH:MM:SS, IST, no timezone suffix)
    for remind_at_iso based strictly on the reference time above.
    If a requested clock time today has already passed, set the timestamp for that time tomorrow.
    If no time is given for a task, use 2 hours after the reference time.
    priority must be exactly one of: High, Medium, Low.
    """

    try:
        response = _call_gemini(prompt)
        parsed = json.loads(response.text.strip())
        tasks = parsed.get("tasks") or []
        if not tasks:
            return {"tasks": []}   # Gemini decided it's just chat - trust it
        return {"tasks": [_normalise_task(t, now) for t in tasks]}
    except Exception as e:
        logger.error("Gemini unavailable, using local parser instead: %s", e)
        return parse_local_fallback(raw_text)
