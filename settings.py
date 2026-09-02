"""Runtime settings the admin can change from inside the bot.

Distinct from config.py, which holds deployment/environment values (tokens,
paths) that only change on the server. These live in the `settings` table so
they can be edited from the admin panel without touching code.
"""
import logging
from datetime import time

import database as db

logger = logging.getLogger(__name__)

# key -> (default "HH:MM", Uzbek label, short description)
TIME_SETTINGS = {
    'work_start': ("09:00", "🕘 Ish boshlanishi", "Ish kuni necha soatda boshlanadi"),
    'late_after': ("09:15", "⏰ Kechikish chegarasi", "Shu vaqtdan keyin kelish kechikish hisoblanadi"),
    'work_end':   ("18:00", "🕕 Ish tugashi", "Ish kuni necha soatda tugaydi"),
}


def get_time(key):
    """Read a HH:MM setting, falling back to its default if unset or corrupt."""
    default, _, _ = TIME_SETTINGS[key]
    raw = _get_raw(key) or default
    try:
        h, m = raw.split(':')
        return time(int(h), int(m))
    except (ValueError, AttributeError):
        logger.warning(f"Setting '{key}' has invalid value {raw!r}; using default {default}")
        h, m = default.split(':')
        return time(int(h), int(m))


def get_time_str(key):
    t = get_time(key)
    return f"{t.hour:02d}:{t.minute:02d}"


def set_time(key, value):
    """Store a HH:MM value. Returns False if it isn't a valid time."""
    if key not in TIME_SETTINGS:
        return False
    try:
        h, m = value.strip().split(':')
        h, m = int(h), int(m)
        if not (0 <= h <= 23 and 0 <= m <= 59):
            return False
    except (ValueError, AttributeError):
        return False
    db.update_setting(key, f"{h:02d}:{m:02d}")
    return True


def _get_raw(key):
    try:
        conn = db.get_connection()
        c = conn.cursor()
        c.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = c.fetchone()
        conn.close()
        return row['value'] if row else None
    except Exception as e:
        logger.error(f"Error reading setting {key}: {e}")
        return None


def all_times():
    """[(key, label, current_value, description), ...] for rendering."""
    return [
        (key, label, get_time_str(key), desc)
        for key, (_, label, desc) in TIME_SETTINGS.items()
    ]
