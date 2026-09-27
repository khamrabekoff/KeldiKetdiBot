"""Employee statistics - computation only.

All wording/layout lives in ui.py, so this module returns plain numbers.
"""
import logging
from datetime import timedelta

import database as db
import settings
import utils

logger = logging.getLogger(__name__)


def get_employee_stats(user_id, days=30):
    """Totals for one employee over the trailing `days` days."""
    try:
        user = db.get_user(user_id)
        if not user:
            return None

        now = utils.get_now()
        start_date = now.date() - timedelta(days=days)
        attendance = db.get_user_month_details(user_id, start_date)
        rates = db.get_db_rates(user_id)
        late_after = settings.get_time('late_after')

        stats = {
            'user_id': user_id,
            'name': user['full_name'],
            'phone': user['phone'],
            'days': days,
            'total_minutes': 0.0,
            'total_wage': 0.0,
            'total_base': 0.0,
            'total_overtime': 0.0,
            'days_worked': 0,
            'late_days': 0,
            'avg_wage_per_day': 0.0,
            'avg_minutes_per_day': 0.0,
            'salary_type': rates.get('salary_type', 'tariff'),
            'rates': rates,
        }

        for row in attendance:
            if not (row['check_in'] and row['check_out']):
                continue
            stats['days_worked'] += 1
            stats['total_wage'] += row['total_wage'] or 0
            # Rows predating the stored split carry zeros; count them as base.
            base = row['base_wage'] or 0
            overtime = row['overtime_wage'] or 0
            if not base and not overtime:
                base = row['total_wage'] or 0
            stats['total_base'] += base
            stats['total_overtime'] += overtime
            stats['total_minutes'] += (row['check_out'] - row['check_in']).total_seconds() / 60.0

            cutoff = row['check_in'].replace(
                hour=late_after.hour, minute=late_after.minute, second=0, microsecond=0
            )
            if row['check_in'] > cutoff:
                stats['late_days'] += 1

        # Note: deliberately no "days missed" figure. It used to be
        # (calendar days - days worked), which counted every weekend as a
        # no-show and made everyone look absent half the month.
        if stats['days_worked']:
            stats['avg_wage_per_day'] = stats['total_wage'] / stats['days_worked']
            stats['avg_minutes_per_day'] = stats['total_minutes'] / stats['days_worked']

        return stats
    except Exception as e:
        logger.error(f"Error getting employee stats for {user_id}: {e}")
        return None


def month_payroll(start_date):
    """One calendar month's pay per employee: earned, taken as advances, and
    what the admin still has to pay.

    The bot's monthly report, the Excel and the PDF all read this, so the three
    can never disagree about what anyone is owed. 'rows' and 'advances' are
    handed back as well for the exports' day-by-day and advance listings.
    """
    end_date = utils.next_month(start_date)
    rows = db.get_month_attendance_details(start_date, end_date)
    advances = db.get_advances(start_date, end_date)

    people = {}

    def person(name):
        return people.setdefault(name, {
            'name': name, 'days': 0, 'minutes': 0.0, 'wage': 0.0,
            'base': 0.0, 'overtime': 0.0, 'advance': 0.0,
        })

    for row in rows:
        entry = person(row['full_name'])
        if not (row['check_in'] and row['check_out']):
            continue
        total = row['total_wage'] or 0
        # Rows predating the stored split carry zeros; count them as base.
        base = row['base_wage'] or 0
        overtime = row['overtime_wage'] or 0
        if not base and not overtime:
            base = total
        entry['days'] += 1
        entry['wage'] += total
        entry['base'] += base
        entry['overtime'] += overtime
        entry['minutes'] += (row['check_out'] - row['check_in']).total_seconds() / 60.0

    for advance in advances:
        person(advance['full_name'])['advance'] += advance['amount']

    for entry in people.values():
        entry['to_pay'] = entry['wage'] - entry['advance']

    employees = sorted(people.values(), key=lambda e: -e['wage'])
    totals = {key: sum(e[key] for e in employees)
              for key in ('wage', 'overtime', 'advance', 'to_pay')}
    return {'employees': employees, 'totals': totals, 'rows': rows, 'advances': advances}


def get_all_employees_stats(days=30):
    """Stats for every employee, richest-earning first."""
    try:
        all_stats = []
        for emp in db.get_employees():
            stats = get_employee_stats(emp['id'], days)
            if stats:
                all_stats.append(stats)
        return sorted(all_stats, key=lambda s: s['total_wage'], reverse=True)
    except Exception as e:
        logger.error(f"Error getting all employees stats: {e}")
        return []
