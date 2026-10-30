import sqlite3
import calendar
import datetime
import os
import logging
from config import DATABASE_PATH

logger = logging.getLogger(__name__)

def get_connection():
    try:
        conn = sqlite3.connect(DATABASE_PATH, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA cache_size = -2000;')
        conn.execute('PRAGMA synchronous = NORMAL;')
        return conn
    except sqlite3.OperationalError as e:
        logger.error(f"Database connection error: {e}")
        raise


def init_db():
    """Инициализация БД с проверкой ошибок"""
    try:
        logger.info("🗄️ Initializing database...")
        conn = get_connection()
        c = conn.cursor()
        c.execute('PRAGMA journal_mode=WAL;')

        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                phone TEXT,
                full_name TEXT,
                role TEXT DEFAULT 'employee',
                is_active INTEGER DEFAULT 1
            )
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS pending_users (
                phone TEXT PRIMARY KEY,
                full_name TEXT,
                salary_type TEXT DEFAULT 'tariff',
                rate_n REAL DEFAULT 0,
                rate_m REAL DEFAULT 0,
                rate_k REAL DEFAULT 0,
                rate_overtime REAL DEFAULT 0,
                monthly_salary REAL DEFAULT 0,
                overtime_hourly_rate REAL DEFAULT 0,
                rate_per_minute REAL DEFAULT 0
            )
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS rates (
                user_id INTEGER PRIMARY KEY,
                salary_type TEXT DEFAULT 'tariff',
                rate_n REAL DEFAULT 0,
                rate_m REAL DEFAULT 0,
                rate_k REAL DEFAULT 0,
                rate_overtime REAL DEFAULT 0,
                monthly_salary REAL DEFAULT 0,
                overtime_hourly_rate REAL DEFAULT 0,
                rate_per_minute REAL DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                date DATE,
                check_in TIMESTAMP,
                check_out TIMESTAMP,
                total_wage REAL DEFAULT 0,
                base_wage REAL DEFAULT 0,
                overtime_wage REAL DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')

        c.execute('''CREATE TABLE IF NOT EXISTS correction_requests (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        request_date TEXT,
                        actual_check_in TEXT,
                        actual_check_out TEXT,
                        status TEXT DEFAULT 'PENDING',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY(user_id) REFERENCES users(id)
                    )''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')

        # Official days off the admin declares. Together with Sundays these are
        # the days a monthly salary is NOT divided by.
        c.execute('''
            CREATE TABLE IF NOT EXISTS holidays (
                date DATE PRIMARY KEY,
                note TEXT,
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Cash an employee took ahead of payday. Entered by the employee, and
        # voided rather than deleted when an admin rejects it, so a mistaken
        # entry still leaves a trace of who removed it.
        c.execute('''
            CREATE TABLE IF NOT EXISTS advances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                note TEXT,
                date DATE,
                created_at TIMESTAMP,
                status TEXT DEFAULT 'ACTIVE',
                voided_by INTEGER,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')

        # Salary the admin has paid out for a month. A month with at least one
        # row here counts as settled, and whatever is left of its balance -
        # an advance larger than the pay, or a partial payment - moves into
        # the next month. A zero-amount row settles a month without paying.
        c.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                month DATE,
                amount REAL,
                created_at TIMESTAMP,
                created_by INTEGER,
                status TEXT DEFAULT 'ACTIVE',
                voided_by INTEGER,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')

        # Every copy of a message that went to several admins with buttons on
        # it - a correction request, an advance. Once one admin acts, the
        # other copies are rewritten to say so, instead of staying live.
        c.execute('''
            CREATE TABLE IF NOT EXISTS admin_copies (
                kind TEXT,
                ref INTEGER,
                chat_id INTEGER,
                message_id INTEGER,
                text TEXT,
                PRIMARY KEY (kind, ref, chat_id, message_id)
            )
        ''')

        # Status cards the proxy refused to carry (see send_employee_home); sent
        # again on later traffic.
        c.execute('''
            CREATE TABLE IF NOT EXISTS pending_replies (
                user_id INTEGER PRIMARY KEY,
                note TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        c.execute('CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(date)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_attendance_user_date ON attendance(user_id, date)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_advances_user_date ON advances(user_id, date)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_payments_month_user ON payments(month, user_id)')

        new_cols = [
            ("rates", "salary_type", "TEXT DEFAULT 'tariff'"),
            ("rates", "monthly_salary", "REAL DEFAULT 0"),
            ("rates", "overtime_hourly_rate", "REAL DEFAULT 0"),
            ("rates", "rate_per_minute", "REAL DEFAULT 0"),
            ("pending_users", "salary_type", "TEXT DEFAULT 'tariff'"),
            ("pending_users", "monthly_salary", "REAL DEFAULT 0"),
            ("pending_users", "overtime_hourly_rate", "REAL DEFAULT 0"),
            ("pending_users", "rate_per_minute", "REAL DEFAULT 0"),
            ("pending_users", "rate_overtime", "REAL DEFAULT 0"),
            ("rates", "overtime_per_minute", "REAL DEFAULT 0"),
            ("attendance", "base_wage", "REAL DEFAULT 0"),
            ("attendance", "overtime_wage", "REAL DEFAULT 0"),
            ("pending_users", "overtime_per_minute", "REAL DEFAULT 0"),
            ("advances", "created_by", "INTEGER"),  # admin who entered it; NULL = the employee
            ("attendance", "open_alerted", "INTEGER DEFAULT 0"),  # left open overnight, admins told
        ]
        for table, col, col_def in new_cols:
            try:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")
            except sqlite3.OperationalError:
                pass

        conn.commit()
        conn.close()
        logger.info("✅ Database initialized successfully")
    except Exception as e:
        logger.error(f"❌ Database initialization error: {e}")
        raise


def add_user(telegram_id, phone, full_name, role='employee'):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute('INSERT OR REPLACE INTO users (id, phone, full_name, role, is_active) '
                  'VALUES (?, ?, ?, ?, 1)', (telegram_id, phone, full_name, role))
        if role == 'employee':
            c.execute(
                'INSERT OR IGNORE INTO rates (user_id, salary_type, rate_n, rate_m, rate_k, rate_overtime, monthly_salary, overtime_hourly_rate, rate_per_minute) VALUES (?, ?, 0, 0, 0, 0, 0, 0, 0)',
                (telegram_id, 'tariff')
            )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error adding user {telegram_id}: {e}")
        raise


def add_pending_user(phone, full_name, salary_type,
                     rate_n=0, rate_m=0, rate_k=0, rate_overtime=0,
                     monthly_salary=0, overtime_hourly_rate=0, rate_per_minute=0,
                     overtime_per_minute=0):
    try:
        conn = get_connection()
        c = conn.cursor()
        phone = phone.replace("+", "").replace(" ", "").strip()
        c.execute(
            '''INSERT OR REPLACE INTO pending_users
               (phone, full_name, salary_type, rate_n, rate_m, rate_k, rate_overtime,
                monthly_salary, overtime_hourly_rate, rate_per_minute, overtime_per_minute)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (phone, full_name, salary_type, rate_n, rate_m, rate_k, rate_overtime,
             monthly_salary, overtime_hourly_rate, rate_per_minute, overtime_per_minute)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error adding pending user {phone}: {e}")
        raise


def get_pending_user(phone_suffix):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute('SELECT * FROM pending_users WHERE phone LIKE ?', (f'%{phone_suffix}',))
        row = c.fetchone()
        conn.close()
        return row
    except Exception as e:
        logger.error(f"Error getting pending user: {e}")
        return None


def list_pending_users():
    """Employees the admin has added who haven't opened the bot yet.

    They have no Telegram id until they share their contact, so they cannot
    live in `users` - but the admin still needs to see that they exist, or
    adding someone looks like it did nothing.
    """
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute('SELECT phone, full_name, salary_type FROM pending_users ORDER BY full_name')
        rows = c.fetchall()
        conn.close()
        return rows
    except Exception as e:
        logger.error(f"Error listing pending users: {e}")
        return []


def delete_pending_user(phone):
    """Drop an invitation. The phone is the key, so a typo in it cannot be
    corrected by re-adding - the wrong row has to go."""
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute('DELETE FROM pending_users WHERE phone = ?', (phone,))
        removed = c.rowcount > 0
        conn.commit()
        conn.close()
        return removed
    except Exception as e:
        logger.error(f"Error deleting pending user {phone}: {e}")
        return False


def promote_pending_to_user(telegram_id, full_phone, full_name, pending_row):
    """Also how a deleted employee comes back: invited again and opening the
    bot from the same Telegram account, their row is made active again under
    the same id, so their old days, advances and payments are theirs again.
    The new invitation's rate replaces the old one. From a different account
    they start as a new record - the old one stays deleted, history and all."""
    try:
        conn = get_connection()
        c = conn.cursor()
        keys = pending_row.keys()

        c.execute('INSERT OR REPLACE INTO users (id, phone, full_name, role, is_active) '
                  'VALUES (?, ?, ?, ?, 1)', (telegram_id, full_phone, full_name, 'employee'))

        salary_type = pending_row['salary_type'] if 'salary_type' in keys else 'tariff'
        monthly_salary = pending_row['monthly_salary'] if 'monthly_salary' in keys else 0
        overtime_hourly_rate = pending_row['overtime_hourly_rate'] if 'overtime_hourly_rate' in keys else 0
        rate_per_minute = pending_row['rate_per_minute'] if 'rate_per_minute' in keys else 0
        rate_overtime = pending_row['rate_overtime'] if 'rate_overtime' in keys else 0
        overtime_per_minute = pending_row['overtime_per_minute'] if 'overtime_per_minute' in keys else 0

        c.execute(
            '''INSERT OR REPLACE INTO rates
               (user_id, salary_type, rate_n, rate_m, rate_k, rate_overtime,
                monthly_salary, overtime_hourly_rate, rate_per_minute, overtime_per_minute)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (telegram_id, salary_type,
             pending_row['rate_n'], pending_row['rate_m'], pending_row['rate_k'],
             rate_overtime, monthly_salary, overtime_hourly_rate, rate_per_minute,
             overtime_per_minute)
        )

        c.execute('DELETE FROM pending_users WHERE phone = ?', (pending_row['phone'],))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error promoting pending user: {e}")
        raise


# A deleted employee keeps their users row (is_active = 0): every report
# joins on it, and without it what they earned, took and were paid vanished.
ACTIVE = 'COALESCE(is_active, 1) = 1'

# The report queries' name column: a deleted person is still listed, marked,
# so the balance they left can be seen and paid.
REPORT_NAME = ("u.full_name || CASE WHEN COALESCE(u.is_active, 1) = 0 "
               "THEN ' (o''chirilgan)' ELSE '' END AS full_name, "
               "COALESCE(u.is_active, 1) AS is_active")


def get_user(telegram_id, include_inactive=False):
    """The user, or None. A deleted employee counts as None unless asked
    for - every caller that decides who may do something relies on that."""
    try:
        conn = get_connection()
        c = conn.cursor()
        sql = 'SELECT * FROM users WHERE id = ?'
        if not include_inactive:
            sql += f' AND {ACTIVE}'
        c.execute(sql, (telegram_id,))
        user = c.fetchone()
        conn.close()
        return user
    except Exception as e:
        logger.error(f"Error getting user {telegram_id}: {e}")
        return None


def create_backup(dest_path):
    """Write a consistent snapshot of the live DB to dest_path.

    Uses sqlite3's own backup API rather than copying the file: the DB runs in
    WAL mode, where a plain file copy can miss commits still sitting in the
    -wal sidecar, and can catch a half-written page if the bot writes mid-copy.
    """
    source = get_connection()
    dest = sqlite3.connect(dest_path)
    try:
        with dest:
            source.backup(dest)
    finally:
        dest.close()
        source.close()
    return dest_path


def get_db_stats():
    """Row counts, so a backup's caption can show what's actually inside it."""
    counts = {}
    try:
        conn = get_connection()
        c = conn.cursor()
        for table in ('users', 'attendance', 'rates', 'correction_requests'):
            c.execute(f"SELECT COUNT(*) AS n FROM {table}")  # fixed literals, not user input
            counts[table] = c.fetchone()['n']
        conn.close()
    except Exception as e:
        logger.error(f"Error collecting db stats: {e}")
    return counts


def get_employees():
    """All current employees, alphabetically."""
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute(f"SELECT id, full_name, phone FROM users WHERE role='employee' AND {ACTIVE} "
                  "ORDER BY full_name")
        rows = c.fetchall()
        conn.close()
        return rows
    except Exception as e:
        logger.error(f"Error getting employees: {e}")
        return []


def count_pending_corrections():
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) AS n FROM correction_requests WHERE status='PENDING'")
        n = c.fetchone()['n']
        conn.close()
        return n
    except Exception as e:
        logger.error(f"Error counting pending corrections: {e}")
        return 0


def same_phone(a, b):
    """Whether two numbers are the same line. Two numbers that both carry a
    country code (11+ digits) must match whole - the last 9 digits alone are
    shared by numbers in different countries, e.g. +998 50 170 44 56 and
    +7 950 170 44 56. A number stored without its country code can only be
    compared on those 9 digits."""
    a = ''.join(ch for ch in str(a or '') if ch.isdigit())
    b = ''.join(ch for ch in str(b or '') if ch.isdigit())
    if len(a) < 9 or len(b) < 9:
        return False
    if len(a) >= 11 and len(b) >= 11:
        return a == b
    return a[-9:] == b[-9:]


def get_user_by_phone(phone, role=None):
    """The current user whose stored number is `phone` (see same_phone), or
    None. Admins never match by number - theirs is the placeholder 'AdminPhone'."""
    try:
        conn = get_connection()
        c = conn.cursor()
        sql = f'SELECT * FROM users WHERE phone LIKE ? AND {ACTIVE}'
        params = [f'%{str(phone)[-9:]}']
        if role:
            sql += ' AND role = ?'
            params.append(role)
        c.execute(sql, params)
        rows = c.fetchall()
        conn.close()
        return next((row for row in rows if same_phone(row['phone'], phone)), None)
    except Exception as e:
        logger.error(f"Error getting user by phone: {e}")
        return None


# Every table that points at an employee through user_id
USER_ID_TABLES = ('rates', 'attendance', 'correction_requests', 'advances', 'payments')


def relink_user(old_id, new_id):
    """Move an employee, with all their history, to a new Telegram account.

    Telegram ids never change, so a person who deleted their account and made
    a new one on the same number is a stranger to the bot until this runs.
    Returns False if the old id is gone or the new one is already taken."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('SELECT 1 FROM users WHERE id = ?', (new_id,))
        if c.fetchone():
            return False
        c.execute('UPDATE users SET id = ? WHERE id = ?', (new_id, old_id))
        if c.rowcount == 0:
            return False
        for table in USER_ID_TABLES:  # fixed literals, not user input
            c.execute(f'UPDATE {table} SET user_id = ? WHERE user_id = ?', (new_id, old_id))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"Error relinking user {old_id} -> {new_id}: {e}")
        return False
    finally:
        conn.close()


def get_unreported_open_shifts(before_day):
    """Employees' days before `before_day` that were checked into and never
    out, and that nobody has been told about yet. Such a day earns nothing
    until someone puts the leaving time in."""
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute('''
            SELECT a.id, a.user_id, u.full_name, a.date, a.check_in
            FROM attendance a
            JOIN users u ON a.user_id = u.id
            WHERE u.role = 'employee' AND COALESCE(u.is_active, 1) = 1
              AND a.check_out IS NULL
              AND a.date < ? AND COALESCE(a.open_alerted, 0) = 0
            ORDER BY u.full_name, a.date
        ''', (before_day,))
        rows = c.fetchall()
        conn.close()
        return rows
    except Exception as e:
        logger.error(f"Error getting open shifts: {e}")
        return []


def get_open_days(user_id, before_day):
    """One person's days before `before_day` with a check-in and no check-out,
    oldest first."""
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute('SELECT * FROM attendance WHERE user_id = ? AND check_out IS NULL '
                  'AND check_in IS NOT NULL AND date < ? ORDER BY date', (user_id, before_day))
        rows = c.fetchall()
        conn.close()
        return rows
    except Exception as e:
        logger.error(f"Error getting open days for {user_id}: {e}")
        return []


def mark_open_shifts_reported(attendance_ids):
    if not attendance_ids:
        return
    conn = get_connection()
    try:
        conn.executemany('UPDATE attendance SET open_alerted = 1 WHERE id = ?',
                         [(i,) for i in attendance_ids])
        conn.commit()
    finally:
        conn.close()


def save_pending_reply(user_id, note):
    try:
        conn = get_connection()
        conn.execute('INSERT OR REPLACE INTO pending_replies (user_id, note) VALUES (?, ?)',
                     (user_id, note))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error saving pending reply for {user_id}: {e}")


def clear_pending_reply(user_id):
    try:
        conn = get_connection()
        conn.execute('DELETE FROM pending_replies WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error clearing pending reply for {user_id}: {e}")


def get_pending_replies(min_age_sec=30, max_age_min=120):
    """Replies old enough that the proxy burst has passed, young enough to
    still mean something. Older ones are dropped."""
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM pending_replies WHERE created_at < datetime('now', ?)",
                  (f'-{int(max_age_min)} minutes',))
        c.execute("SELECT user_id, note FROM pending_replies WHERE created_at <= datetime('now', ?)",
                  (f'-{int(min_age_sec)} seconds',))
        rows = c.fetchall()
        conn.commit()
        conn.close()
        return rows
    except Exception as e:
        logger.error(f"Error reading pending replies: {e}")
        return []


def save_admin_copy(kind, ref, chat_id, message_id, text):
    try:
        conn = get_connection()
        conn.execute('INSERT OR REPLACE INTO admin_copies (kind, ref, chat_id, message_id, text) '
                     'VALUES (?, ?, ?, ?, ?)', (kind, ref, chat_id, message_id, text))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error saving admin copy {kind}/{ref}: {e}")


def pop_admin_copies(kind, ref):
    """The copies of one message, forgotten as they are handed back - each
    gets rewritten once."""
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute('SELECT chat_id, message_id, text FROM admin_copies WHERE kind = ? AND ref = ?',
                  (kind, ref))
        rows = c.fetchall()
        c.execute('DELETE FROM admin_copies WHERE kind = ? AND ref = ?', (kind, ref))
        conn.commit()
        conn.close()
        return rows
    except Exception as e:
        logger.error(f"Error reading admin copies {kind}/{ref}: {e}")
        return []


def cancel_pending_corrections(user_id):
    """Mark one person's waiting correction requests CANCELLED; returns their
    ids so the admins' copies can be closed."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT id FROM correction_requests WHERE user_id = ? AND status = 'PENDING'",
                  (user_id,))
        ids = [row['id'] for row in c.fetchall()]
        c.execute("UPDATE correction_requests SET status = 'CANCELLED' "
                  "WHERE user_id = ? AND status = 'PENDING'", (user_id,))
        conn.commit()
        return ids
    finally:
        conn.close()


def get_admin_ids():
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT id FROM users WHERE role='admin'")
        ids = [row['id'] for row in c.fetchall()]
        conn.close()
        return ids
    except Exception as e:
        logger.error(f"Error getting admins: {e}")
        return []


def deactivate_user(user_id):
    """Delete an employee from the bot, not from the books: their row and
    rate stay for the reports, but get_user no longer finds them, so they
    cannot sign in or be picked anywhere current staff are listed."""
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute('UPDATE users SET is_active = 0 WHERE id = ?', (user_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error deactivating user {user_id}: {e}")
        raise


def check_in_user(user_id, timestamp):
    try:
        conn = get_connection()
        c = conn.cursor()
        today = timestamp.date()
        c.execute('SELECT * FROM attendance WHERE user_id = ? AND date = ?', (user_id, today))
        row = c.fetchone()
        if row:
            conn.close()
            if row['check_out']:
                # The day is already closed (usually by an approved correction),
                # so pressing KELDIM again can never succeed - say how to get out.
                return {'success': False, 'message': (
                    "Bugungi ish kuningiz allaqachon yopilgan. "
                    "Vaqt noto'g'ri bo'lsa, «📝 Tuzatish» orqali so'rov yuboring.")}
            return {'success': False, 'message': "Siz bugun allaqachon kelgansiz."}
        c.execute('INSERT INTO attendance (user_id, date, check_in) VALUES (?, ?, ?)',
                  (user_id, today, timestamp))
        conn.commit()
        conn.close()
        return {'success': True}
    except Exception as e:
        logger.error(f"Error checking in user {user_id}: {e}")
        return {'success': False, 'message': f"Xatolik: {str(e)}"}


def is_user_checked_in(user_id):
    try:
        from utils import get_now
        conn = get_connection()
        c = conn.cursor()
        # Tashkent date, as check_in_user writes it - the server runs on UTC,
        # so date.today() is still yesterday until 05:00 local time
        today = get_now().date()
        c.execute('SELECT * FROM attendance WHERE user_id = ? AND date = ? AND check_out IS NULL',
                  (user_id, today))
        row = c.fetchone()
        conn.close()
        return row is not None
    except Exception as e:
        logger.error(f"Error checking if user is checked in: {e}")
        return False


def check_out_user(user_id, timestamp):
    try:
        conn = get_connection()
        c = conn.cursor()
        today = timestamp.date()

        c.execute('SELECT * FROM attendance WHERE user_id = ? AND date = ?', (user_id, today))
        row = c.fetchone()
        if not row:
            conn.close()
            return {'success': False, 'message': "Siz hali kelmagansiz!"}
        if row['check_out']:
            conn.close()
            return {'success': False, 'message': "Siz bugun allaqachon ketgansiz."}

        rates = get_db_rates(user_id)
        from utils import calculate_wage, split_wage
        wage, details, breakdown = calculate_wage(row['check_in'], timestamp, rates)
        base, overtime = split_wage(wage, breakdown)

        c.execute(
            'UPDATE attendance SET check_out = ?, total_wage = ?, base_wage = ?, '
            'overtime_wage = ? WHERE id = ?',
            (timestamp, wage, base, overtime, row['id'])
        )
        conn.commit()
        conn.close()
        return {'success': True, 'wage': wage, 'check_in': row['check_in'], 'details': details}
    except Exception as e:
        logger.error(f"Error checking out user {user_id}: {e}")
        return {'success': False, 'message': f"Xatolik: {str(e)}"}


def get_today_attendance(date_obj):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute('''
            SELECT u.full_name, a.check_in, a.check_out, a.total_wage,
                   r.salary_type, r.rate_n, r.rate_m, r.rate_k, r.rate_overtime,
                   r.monthly_salary, r.overtime_hourly_rate, r.rate_per_minute,
                   r.overtime_per_minute
            FROM attendance a
            JOIN users u ON a.user_id = u.id
            LEFT JOIN rates r ON u.id = r.user_id
            WHERE a.date = ?
        ''', (date_obj,))
        rows = c.fetchall()
        conn.close()
        return rows
    except Exception as e:
        logger.error(f"Error getting today attendance: {e}")
        return []


def get_user_attendance(user_id, limit=30):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute('SELECT * FROM attendance WHERE user_id = ? ORDER BY date DESC LIMIT ?',
                  (user_id, limit))
        rows = c.fetchall()
        conn.close()
        return rows
    except Exception as e:
        logger.error(f"Error getting user attendance: {e}")
        return []


def get_daily_attendance_for_user(user_id, date_obj):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute('SELECT * FROM attendance WHERE user_id = ? AND date = ?', (user_id, date_obj))
        row = c.fetchone()
        conn.close()
        return row
    except Exception as e:
        logger.error(f"Error getting daily attendance: {e}")
        return None


def get_month_attendance_all(start_date):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute('''
            SELECT u.full_name, SUM(a.total_wage) as total_wage
            FROM attendance a
            JOIN users u ON a.user_id = u.id
            WHERE a.date >= ?
            GROUP BY u.id
        ''', (start_date,))
        rows = c.fetchall()
        conn.close()
        return rows
    except Exception as e:
        logger.error(f"Error getting month attendance: {e}")
        return []


def get_month_attendance_details(start_date, end_date=None):
    """Rows with start_date <= date, and date < end_date when one is given.

    A month report must pass its end: without it, August viewed in October
    also counted September and October."""
    try:
        conn = get_connection()
        c = conn.cursor()
        sql = '''
            SELECT a.user_id, {name}, a.date, a.check_in, a.check_out, a.total_wage,
                   a.base_wage, a.overtime_wage,
                   r.salary_type, r.rate_n, r.rate_m, r.rate_k, r.rate_overtime,
                   r.monthly_salary, r.overtime_hourly_rate, r.rate_per_minute,
                   r.overtime_per_minute
            FROM attendance a
            JOIN users u ON a.user_id = u.id
            LEFT JOIN rates r ON u.id = r.user_id
            WHERE a.date >= ?
        '''.format(name=REPORT_NAME)
        params = [start_date]
        if end_date is not None:
            sql += 'AND a.date < ? '
            params.append(end_date)
        sql += 'ORDER BY u.full_name, a.date'
        c.execute(sql, params)
        rows = c.fetchall()
        conn.close()
        return rows
    except Exception as e:
        logger.error(f"Error getting month attendance details: {e}")
        return []


def get_user_month_details(user_id, start_date):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute('''
            SELECT date, check_in, check_out, total_wage, base_wage, overtime_wage
            FROM attendance
            WHERE user_id = ? AND date >= ?
            ORDER BY date ASC
        ''', (user_id, start_date))
        rows = c.fetchall()
        conn.close()
        return rows
    except Exception as e:
        logger.error(f"Error getting user month details: {e}")
        return []


def get_user_month_wage(user_id, start_date):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute('''
            SELECT SUM(total_wage) as total
            FROM attendance
            WHERE user_id = ? AND date >= ?
        ''', (user_id, start_date))
        result = c.fetchone()
        conn.close()
        return round(result['total'], 2) if result and result['total'] else 0
    except Exception as e:
        logger.error(f"Error getting user month wage: {e}")
        return 0


def update_setting(key, value):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error updating setting {key}: {e}")
        raise


def update_rates(user_id, salary_type,
                 rate_n=0, rate_m=0, rate_k=0, rate_overtime=0,
                 monthly_salary=0, overtime_hourly_rate=0, rate_per_minute=0,
                 overtime_per_minute=0):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            '''UPDATE rates SET
                   salary_type=?, rate_n=?, rate_m=?, rate_k=?, rate_overtime=?,
                   monthly_salary=?, overtime_hourly_rate=?, rate_per_minute=?,
                   overtime_per_minute=?
               WHERE user_id=?''',
            (salary_type, rate_n, rate_m, rate_k, rate_overtime,
             monthly_salary, overtime_hourly_rate, rate_per_minute,
             overtime_per_minute, user_id)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error updating rates for user {user_id}: {e}")
        raise


def update_attendance_manual(user_id, date_obj, check_in_dt, check_out_dt, wage, breakdown=None):
    """`breakdown` is the third value from calculate_wage; without it the whole
    wage is recorded as base, which is what a wage with no overtime part is."""
    from utils import split_wage
    base, overtime = split_wage(wage, breakdown or {})
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute('SELECT id FROM attendance WHERE user_id = ? AND date = ?', (user_id, date_obj))
        row = c.fetchone()
        if row:
            c.execute('''UPDATE attendance SET check_in=?, check_out=?, total_wage=?,
                                base_wage=?, overtime_wage=? WHERE id=?''',
                      (check_in_dt, check_out_dt, wage, base, overtime, row['id']))
        else:
            c.execute('''INSERT INTO attendance (user_id, date, check_in, check_out,
                                                 total_wage, base_wage, overtime_wage)
                         VALUES (?, ?, ?, ?, ?, ?, ?)''',
                      (user_id, date_obj, check_in_dt, check_out_dt, wage, base, overtime))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error updating attendance manually: {e}")
        raise


def get_employee_summary(user_id, start_date):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute('''
            SELECT count(*) as days_count, SUM(total_wage) as total_earned
            FROM attendance
            WHERE user_id = ? AND date >= ?
        ''', (user_id, start_date))
        row = c.fetchone()
        conn.close()
        days = row['days_count'] if row['days_count'] else 0
        earned = row['total_earned'] if row['total_earned'] else 0
        return {'days': days, 'earned': earned}
    except Exception as e:
        logger.error(f"Error getting employee summary: {e}")
        return {'days': 0, 'earned': 0}


def get_db_rates(user_id):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute('SELECT * FROM rates WHERE user_id = ?', (user_id,))
        rates = c.fetchone()
        conn.close()
        if not rates:
            return {'salary_type': 'tariff', 'rate_n': 0, 'rate_m': 0, 'rate_k': 0,
                    'rate_overtime': 0, 'monthly_salary': 0,
                    'overtime_hourly_rate': 0, 'rate_per_minute': 0,
                    'overtime_per_minute': 0}
        keys = rates.keys()
        return {
            'salary_type': rates['salary_type'] if 'salary_type' in keys else 'tariff',
            'rate_n': rates['rate_n'],
            'rate_m': rates['rate_m'],
            'rate_k': rates['rate_k'],
            'rate_overtime': rates['rate_overtime'] if 'rate_overtime' in keys else 0,
            'monthly_salary': rates['monthly_salary'] if 'monthly_salary' in keys else 0,
            'overtime_hourly_rate': rates['overtime_hourly_rate'] if 'overtime_hourly_rate' in keys else 0,
            'rate_per_minute': rates['rate_per_minute'] if 'rate_per_minute' in keys else 0,
            'overtime_per_minute': rates['overtime_per_minute'] if 'overtime_per_minute' in keys else 0,
        }
    except Exception as e:
        logger.error(f"Error getting rates for user {user_id}: {e}")
        return {'salary_type': 'tariff', 'rate_n': 0, 'rate_m': 0, 'rate_k': 0,
                'rate_overtime': 0, 'monthly_salary': 0,
                'overtime_hourly_rate': 0, 'rate_per_minute': 0,
                'overtime_per_minute': 0}


def create_correction_request(user_id, date_str, check_in, check_out):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            "INSERT INTO correction_requests (user_id, request_date, actual_check_in, actual_check_out) VALUES (?, ?, ?, ?)",
            (user_id, date_str, check_in, check_out)
        )
        req_id = c.lastrowid
        conn.commit()
        conn.close()
        return req_id
    except Exception as e:
        logger.error(f"Error creating correction request: {e}")
        raise


def get_correction_request(req_id):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM correction_requests WHERE id = ?", (req_id,))
        row = c.fetchone()
        conn.close()
        if row:
            return {
                'id': row['id'],
                'user_id': row['user_id'],
                'request_date': row['request_date'],
                'actual_check_in': row['actual_check_in'],
                'actual_check_out': row['actual_check_out'],
                'status': row['status'],
                'created_at': row['created_at'],
            }
        return None
    except Exception as e:
        logger.error(f"Error getting correction request: {e}")
        return None


def update_correction_request_status(req_id, status):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("UPDATE correction_requests SET status = ? WHERE id = ?", (status, req_id))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error updating correction request status: {e}")
        raise


def get_pending_correction_requests():
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute('''
            SELECT cr.*, u.full_name
            FROM correction_requests cr
            JOIN users u ON cr.user_id = u.id
            WHERE cr.status = 'PENDING' AND COALESCE(u.is_active, 1) = 1
            ORDER BY cr.created_at DESC
        ''')
        rows = c.fetchall()
        conn.close()
        return rows
    except Exception as e:
        logger.error(f"Error getting pending correction requests: {e}")
        return []


# ==================== ADVANCES ====================
# Cash taken before payday. Only ACTIVE rows count towards anything; a voided
# one stays in the table as a record of the mistake.

def add_advance(user_id, amount, note, created_at, created_by=None):
    """created_at is Tashkent time; its date decides which month the advance
    comes out of. created_by is set when an admin enters it for the employee."""
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            'INSERT INTO advances (user_id, amount, note, date, created_at, created_by) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (user_id, amount, note, created_at.date(), created_at, created_by)
        )
        advance_id = c.lastrowid
        conn.commit()
        conn.close()
        return advance_id
    except Exception as e:
        logger.error(f"Error adding advance for user {user_id}: {e}")
        raise


def get_advance(advance_id):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute('''
            SELECT a.*, u.full_name, cb.full_name AS created_by_name
            FROM advances a
            LEFT JOIN users u ON a.user_id = u.id
            LEFT JOIN users cb ON a.created_by = cb.id
            WHERE a.id = ?
        ''', (advance_id,))
        row = c.fetchone()
        conn.close()
        return row
    except Exception as e:
        logger.error(f"Error getting advance {advance_id}: {e}")
        return None


def void_advance(advance_id, admin_id):
    """Returns False if it was already voided (or never existed), so a second
    admin pressing the same button doesn't void it twice."""
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("UPDATE advances SET status = 'VOID', voided_by = ? WHERE id = ? AND status = 'ACTIVE'",
                  (admin_id, advance_id))
        voided = c.rowcount > 0
        conn.commit()
        conn.close()
        return voided
    except Exception as e:
        logger.error(f"Error voiding advance {advance_id}: {e}")
        raise


def get_advances(start_date, end_date, user_id=None):
    """Active advances with start_date <= date < end_date, oldest first."""
    try:
        conn = get_connection()
        c = conn.cursor()
        sql = f'''SELECT a.id, a.user_id, a.amount, a.note, a.date, a.created_at, {REPORT_NAME}
                 FROM advances a
                 JOIN users u ON a.user_id = u.id
                 WHERE a.status = 'ACTIVE' AND a.date >= ? AND a.date < ? '''
        params = [start_date, end_date]
        if user_id is not None:
            sql += 'AND a.user_id = ? '
            params.append(user_id)
        sql += 'ORDER BY a.created_at'
        c.execute(sql, params)
        rows = c.fetchall()
        conn.close()
        return rows
    except Exception as e:
        logger.error(f"Error getting advances: {e}")
        return []


# ==================== PAYMENTS ====================
# Salary paid out, per employee per month. Like advances, a mistaken row is
# voided rather than deleted.

def add_payment(user_id, month, amount, created_by, created_at):
    """month is the first day of the month the pay is for."""
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            'INSERT INTO payments (user_id, month, amount, created_at, created_by) VALUES (?, ?, ?, ?, ?)',
            (user_id, month, amount, created_at, created_by)
        )
        payment_id = c.lastrowid
        conn.commit()
        conn.close()
        return payment_id
    except Exception as e:
        logger.error(f"Error adding payment for user {user_id}: {e}")
        raise


def get_payment(payment_id):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute('''
            SELECT p.*, u.full_name
            FROM payments p
            LEFT JOIN users u ON p.user_id = u.id
            WHERE p.id = ?
        ''', (payment_id,))
        row = c.fetchone()
        conn.close()
        return row
    except Exception as e:
        logger.error(f"Error getting payment {payment_id}: {e}")
        return None


def void_payment(payment_id, admin_id):
    """Returns False if it was already voided (or never existed)."""
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("UPDATE payments SET status = 'VOID', voided_by = ? WHERE id = ? AND status = 'ACTIVE'",
                  (admin_id, payment_id))
        voided = c.rowcount > 0
        conn.commit()
        conn.close()
        return voided
    except Exception as e:
        logger.error(f"Error voiding payment {payment_id}: {e}")
        raise


def get_payments(month, user_id=None):
    """Active payments made for `month` (its first day), oldest first."""
    try:
        conn = get_connection()
        c = conn.cursor()
        sql = f'''SELECT p.id, p.user_id, p.month, p.amount, p.created_at, {REPORT_NAME}
                 FROM payments p
                 JOIN users u ON p.user_id = u.id
                 WHERE p.status = 'ACTIVE' AND p.month = ? '''
        params = [month]
        if user_id is not None:
            sql += 'AND p.user_id = ? '
            params.append(user_id)
        sql += 'ORDER BY p.created_at'
        c.execute(sql, params)
        rows = c.fetchall()
        conn.close()
        return rows
    except Exception as e:
        logger.error(f"Error getting payments: {e}")
        return []


# ==================== HOLIDAYS ====================
# Official days off. A monthly salary is divided by the month's working days,
# so every row here changes what a day of that month is worth.

def is_holiday(day):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute('SELECT 1 FROM holidays WHERE date = ?', (day,))
        found = c.fetchone() is not None
        conn.close()
        return found
    except Exception as e:
        logger.error(f"Error checking holiday {day}: {e}")
        return False


def get_holidays_in_month(year, month):
    """Set of dates, for cheap membership tests while walking a month."""
    try:
        first = datetime.date(year, month, 1)
        last = datetime.date(year, month, calendar.monthrange(year, month)[1])
        conn = get_connection()
        c = conn.cursor()
        c.execute('SELECT date FROM holidays WHERE date BETWEEN ? AND ?', (first, last))
        days = {row['date'] for row in c.fetchall()}
        conn.close()
        return days
    except Exception as e:
        logger.error(f"Error getting holidays for {year}-{month}: {e}")
        return set()


def list_holidays(year, month):
    """Rows (date, note) for the admin panel, oldest first."""
    try:
        first = datetime.date(year, month, 1)
        last = datetime.date(year, month, calendar.monthrange(year, month)[1])
        conn = get_connection()
        c = conn.cursor()
        c.execute('SELECT date, note FROM holidays WHERE date BETWEEN ? AND ? ORDER BY date',
                  (first, last))
        rows = c.fetchall()
        conn.close()
        return rows
    except Exception as e:
        logger.error(f"Error listing holidays for {year}-{month}: {e}")
        return []


def add_holiday(day, note=None, created_by=None):
    """Returns False if the day was already marked."""
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute('INSERT OR IGNORE INTO holidays (date, note, created_by) VALUES (?, ?, ?)',
                  (day, note, created_by))
        added = c.rowcount > 0
        conn.commit()
        conn.close()
        return added
    except Exception as e:
        logger.error(f"Error adding holiday {day}: {e}")
        raise


def remove_holiday(day):
    """Returns False if the day was not marked in the first place."""
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute('DELETE FROM holidays WHERE date = ?', (day,))
        removed = c.rowcount > 0
        conn.commit()
        conn.close()
        return removed
    except Exception as e:
        logger.error(f"Error removing holiday {day}: {e}")
        raise


def recalculate_month_wages(year, month, user_id=None):
    """Rewrite the stored day wages of a month for monthly-salary employees.

    Their day rate is the salary divided by the month's working days, so
    declaring a holiday on the 20th changes what the 3rd was worth. Wages are
    stored per day when an employee checks out, so those rows have to be
    rewritten rather than recomputed on read - every report reads the stored
    figure. Returns how many rows changed.
    """
    from utils import calculate_wage, split_wage
    import workdays

    try:
        first = datetime.date(year, month, 1)
        last = datetime.date(year, month, calendar.monthrange(year, month)[1])

        conn = get_connection()
        c = conn.cursor()
        sql = '''SELECT a.id, a.user_id, a.date, a.check_in, a.check_out
                 FROM attendance a
                 JOIN rates r ON r.user_id = a.user_id
                 WHERE a.date BETWEEN ? AND ?
                   AND a.check_out IS NOT NULL
                   AND r.salary_type = 'monthly' '''
        params = [first, last]
        if user_id is not None:
            sql += 'AND a.user_id = ? '
            params.append(user_id)
        rows = c.execute(sql, params).fetchall()

        if not rows:
            conn.close()
            return 0

        # Rates and the month calendar are read before the first write, so the
        # loop below is not opening fresh connections while holding the lock.
        rates_by_user = {uid: get_db_rates(uid) for uid in {row['user_id'] for row in rows}}
        context_for = workdays.month_calendar(year, month)

        updated = 0
        for row in rows:
            wage, _, breakdown = calculate_wage(
                row['check_in'], row['check_out'], rates_by_user[row['user_id']],
                month_ctx=context_for(row['date'])
            )
            base, overtime = split_wage(wage, breakdown)
            c.execute(
                'UPDATE attendance SET total_wage = ?, base_wage = ?, overtime_wage = ? '
                'WHERE id = ?',
                (wage, base, overtime, row['id'])
            )
            updated += 1

        conn.commit()
        conn.close()
        logger.info(f"Recalculated {updated} wage rows for {year}-{month:02d}")
        return updated
    except Exception as e:
        logger.error(f"Error recalculating wages for {year}-{month}: {e}")
        raise
