import sqlite3
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

        c.execute('CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(date)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_attendance_user_date ON attendance(user_id, date)')

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
        c.execute('INSERT OR REPLACE INTO users (id, phone, full_name, role) VALUES (?, ?, ?, ?)',
                  (telegram_id, phone, full_name, role))
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
                     monthly_salary=0, overtime_hourly_rate=0, rate_per_minute=0):
    try:
        conn = get_connection()
        c = conn.cursor()
        phone = phone.replace("+", "").replace(" ", "").strip()
        c.execute(
            '''INSERT OR REPLACE INTO pending_users
               (phone, full_name, salary_type, rate_n, rate_m, rate_k, rate_overtime,
                monthly_salary, overtime_hourly_rate, rate_per_minute)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (phone, full_name, salary_type, rate_n, rate_m, rate_k, rate_overtime,
             monthly_salary, overtime_hourly_rate, rate_per_minute)
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


def promote_pending_to_user(telegram_id, full_phone, full_name, pending_row):
    try:
        conn = get_connection()
        c = conn.cursor()
        keys = pending_row.keys()

        c.execute('INSERT OR REPLACE INTO users (id, phone, full_name, role) VALUES (?, ?, ?, ?)',
                  (telegram_id, full_phone, full_name, 'employee'))

        salary_type = pending_row['salary_type'] if 'salary_type' in keys else 'tariff'
        monthly_salary = pending_row['monthly_salary'] if 'monthly_salary' in keys else 0
        overtime_hourly_rate = pending_row['overtime_hourly_rate'] if 'overtime_hourly_rate' in keys else 0
        rate_per_minute = pending_row['rate_per_minute'] if 'rate_per_minute' in keys else 0
        rate_overtime = pending_row['rate_overtime'] if 'rate_overtime' in keys else 0

        c.execute(
            '''INSERT OR REPLACE INTO rates
               (user_id, salary_type, rate_n, rate_m, rate_k, rate_overtime,
                monthly_salary, overtime_hourly_rate, rate_per_minute)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (telegram_id, salary_type,
             pending_row['rate_n'], pending_row['rate_m'], pending_row['rate_k'],
             rate_overtime, monthly_salary, overtime_hourly_rate, rate_per_minute)
        )

        c.execute('DELETE FROM pending_users WHERE phone = ?', (pending_row['phone'],))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error promoting pending user: {e}")
        raise


def get_user(telegram_id):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute('SELECT * FROM users WHERE id = ?', (telegram_id,))
        user = c.fetchone()
        conn.close()
        return user
    except Exception as e:
        logger.error(f"Error getting user {telegram_id}: {e}")
        return None


def get_employees():
    """All employees, alphabetically."""
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT id, full_name, phone FROM users WHERE role='employee' ORDER BY full_name")
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


def get_user_by_phone(phone):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute('SELECT * FROM users WHERE phone LIKE ?', (f'%{phone[-9:]}',))
        user = c.fetchone()
        conn.close()
        return user
    except Exception as e:
        logger.error(f"Error getting user by phone: {e}")
        return None


def delete_user(user_id):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute('DELETE FROM rates WHERE user_id = ?', (user_id,))
        c.execute('DELETE FROM users WHERE id = ?', (user_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error deleting user {user_id}: {e}")
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
        conn = get_connection()
        c = conn.cursor()
        today = datetime.date.today()
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
        from utils import calculate_wage
        wage, details, _ = calculate_wage(row['check_in'], timestamp, rates)

        c.execute('UPDATE attendance SET check_out = ?, total_wage = ? WHERE id = ?',
                  (timestamp, wage, row['id']))
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
                   r.monthly_salary, r.overtime_hourly_rate, r.rate_per_minute
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


def get_month_attendance_details(start_date):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute('''
            SELECT u.full_name, a.date, a.check_in, a.check_out, a.total_wage,
                   r.salary_type, r.rate_n, r.rate_m, r.rate_k, r.rate_overtime,
                   r.monthly_salary, r.overtime_hourly_rate, r.rate_per_minute
            FROM attendance a
            JOIN users u ON a.user_id = u.id
            LEFT JOIN rates r ON u.id = r.user_id
            WHERE a.date >= ?
            ORDER BY u.full_name, a.date
        ''', (start_date,))
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
            SELECT date, check_in, check_out, total_wage
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
                 monthly_salary=0, overtime_hourly_rate=0, rate_per_minute=0):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            '''UPDATE rates SET
                   salary_type=?, rate_n=?, rate_m=?, rate_k=?, rate_overtime=?,
                   monthly_salary=?, overtime_hourly_rate=?, rate_per_minute=?
               WHERE user_id=?''',
            (salary_type, rate_n, rate_m, rate_k, rate_overtime,
             monthly_salary, overtime_hourly_rate, rate_per_minute, user_id)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error updating rates for user {user_id}: {e}")
        raise


def update_attendance_manual(user_id, date_obj, check_in_dt, check_out_dt, wage):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute('SELECT id FROM attendance WHERE user_id = ? AND date = ?', (user_id, date_obj))
        row = c.fetchone()
        if row:
            c.execute('''UPDATE attendance SET check_in=?, check_out=?, total_wage=? WHERE id=?''',
                      (check_in_dt, check_out_dt, wage, row['id']))
        else:
            c.execute('''INSERT INTO attendance (user_id, date, check_in, check_out, total_wage)
                         VALUES (?, ?, ?, ?, ?)''',
                      (user_id, date_obj, check_in_dt, check_out_dt, wage))
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
                    'overtime_hourly_rate': 0, 'rate_per_minute': 0}
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
        }
    except Exception as e:
        logger.error(f"Error getting rates for user {user_id}: {e}")
        return {'salary_type': 'tariff', 'rate_n': 0, 'rate_m': 0, 'rate_k': 0,
                'rate_overtime': 0, 'monthly_salary': 0,
                'overtime_hourly_rate': 0, 'rate_per_minute': 0}


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
            WHERE cr.status = 'PENDING'
            ORDER BY cr.created_at DESC
        ''')
        rows = c.fetchall()
        conn.close()
        return rows
    except Exception as e:
        logger.error(f"Error getting pending correction requests: {e}")
        return []
