import os
import logging
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Optional: force a specific Gemini model. Otherwise parser.py tries a list of current models.
GEMINI_MODEL = os.getenv("GEMINI_MODEL")

# Absolute path so the DB is found no matter which folder the bot is started from.
# On Render, point DATABASE_PATH at a persistent disk (e.g. /var/data/minddump.db),
# otherwise the free-tier filesystem is wiped on every restart/redeploy.
DATABASE_PATH = os.getenv("DATABASE_PATH") or os.path.join(BASE_DIR, "minddump.db")

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set!")

if not GEMINI_API_KEY:
    # Not fatal: the built-in local parser still works without Gemini.
    logging.warning("GEMINI_API_KEY is not set - using the basic local parser only.")
