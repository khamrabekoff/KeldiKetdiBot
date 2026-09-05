"""Working-day calendar: which days count as work, and how many a month has.

A month's working days are its calendar days minus Sundays minus the official
holidays an admin entered. That count is the divisor behind every monthly
salary, so it lives here instead of being re-derived by each caller.

Separate from settings.py on purpose: those are HH:MM values an admin nudges,
this is calendar arithmetic with its own table behind it.
"""
import calendar
import datetime
import logging

import database as db

logger = logging.getLogger(__name__)

SUNDAY = 6

# Used only when the work-hour settings are nonsense (end before start).
DEFAULT_WORK_START = datetime.time(9, 0)
DEFAULT_WORK_END = datetime.time(18, 0)
DEFAULT_WORKDAY_MINUTES = 540


def work_hours():
    """The paid standard day: (start, end, minutes).

    Taken from the admin's work-hour settings rather than hardcoded, so that
    moving "Ish tugashi" moves the salary maths with it - otherwise the panel
    would promise hours the wage formula ignores.
    """
    import settings as st

    start = st.get_time('work_start')
    end = st.get_time('work_end')
    minutes = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
    if minutes <= 0:
        logger.warning(
            "work_end (%s) is not after work_start (%s); falling back to %s-%s",
            end, start, DEFAULT_WORK_START, DEFAULT_WORK_END,
        )
        return DEFAULT_WORK_START, DEFAULT_WORK_END, DEFAULT_WORKDAY_MINUTES
    return start, end, minutes


def _count_working_days(year, month, holidays):
    days_in_month = calendar.monthrange(year, month)[1]
    count = 0
    for day_number in range(1, days_in_month + 1):
        day = datetime.date(year, month, day_number)
        if day.weekday() == SUNDAY or day in holidays:
            continue
        count += 1
    return count


def working_days_in_month(year, month):
    """30 calendar days - 4 Sundays - 2 official holidays = 24."""
    return _count_working_days(year, month, db.get_holidays_in_month(year, month))


def is_rest_day(day):
    """True for Sundays and for admin-entered official holidays."""
    return day.weekday() == SUNDAY or db.is_holiday(day)


def month_calendar(year, month):
    """Read the month once, return a per-day context builder.

    A month-wide recalculation touches dozens of rows that all share the same
    working-day count; this keeps that a single query instead of one per row.
    """
    holidays = db.get_holidays_in_month(year, month)
    working_days = _count_working_days(year, month, holidays)
    start, end, minutes = work_hours()

    def context_for(day):
        return {
            'working_days': working_days,
            'is_rest_day': day.weekday() == SUNDAY or day in holidays,
            'standard_minutes': minutes,
            'work_start': start,
            'work_end': end,
        }

    return context_for


def month_context(day):
    """Everything the monthly wage formula needs about one day and its month."""
    return month_calendar(day.year, day.month)(day)


def base_rate_per_minute(monthly_salary, context):
    """The per-minute value of a monthly salary in a given month.

    Returns 0 for a month with no working days at all, which would otherwise
    divide by zero - an all-holiday month pays no base, only overtime.
    """
    divisor = context['working_days'] * context['standard_minutes']
    if not monthly_salary or divisor <= 0:
        return 0.0
    return monthly_salary / divisor
