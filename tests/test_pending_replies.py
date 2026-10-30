import os, sys, tempfile

os.environ['BOT_TOKEN'] = 'test:token'
os.environ['ADMIN_SECRET'] = 'test_secret'
os.environ['DATABASE_PATH'] = os.path.join(tempfile.mkdtemp(), 'test.db')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import datetime as dt
import database as db, utils

db.init_db()
failures = []

def check(label, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}")
    if not cond:
        failures.append(label)

db.save_pending_reply(1, "note")
check("a fresh reply waits out the proxy burst", db.get_pending_replies() == [])
due = db.get_pending_replies(min_age_sec=0)
check("it is handed back once old enough", [(r['user_id'], r['note']) for r in due] == [(1, "note")])
db.save_pending_reply(1, "newer")
check("one per user, the latest wins",
      [r['note'] for r in db.get_pending_replies(min_age_sec=0)] == ["newer"])
db.clear_pending_reply(1)
check("cleared once delivered", db.get_pending_replies(min_age_sec=0) == [])
db.save_pending_reply(2, "old")
conn = db.get_connection()
conn.execute("UPDATE pending_replies SET created_at = datetime('now', '-3 hours')")
conn.commit(); conn.close()
check("stale ones are dropped", db.get_pending_replies(min_age_sec=0) == [])

now_utc = dt.datetime.now(dt.timezone.utc)
def off(sent):
    return abs((utils.press_time(sent) - utils.get_now()).total_seconds())
pressed = utils.press_time(now_utc - dt.timedelta(minutes=7))
check("a press processed 7 min late is stamped with the press time",
      abs((utils.get_now() - pressed).total_seconds() - 420) < 5)
check("no message time -> now", off(None) < 5)
check("older than 3 h -> now", off(now_utc - dt.timedelta(hours=5)) < 5)
check("in the future -> now", off(now_utc + dt.timedelta(minutes=30)) < 5)

sys.exit(0 if not failures else 1)
