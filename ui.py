"""Presentation layer: card text renderers + inline keyboard builders.

Kept separate from handler logic so the wording/layout of every screen lives
in one place. All user-facing text is Uzbek.
"""
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

import database as db
import utils

# ==================== FORMATTING HELPERS ====================

MONTHS_UZ = [
    "yanvar", "fevral", "mart", "aprel", "may", "iyun",
    "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr",
]
WEEKDAYS_UZ = [
    "dushanba", "seshanba", "chorshanba", "payshanba",
    "juma", "shanba", "yakshanba",
]


def fmt_date(d):
    """2 -> '2-sentabr, seshanba'"""
    return f"{d.day}-{MONTHS_UZ[d.month - 1]}, {WEEKDAYS_UZ[d.weekday()]}"


def fmt_month(d):
    """-> 'Sentabr 2026'"""
    return f"{MONTHS_UZ[d.month - 1].capitalize()} {d.year}"


def fmt_money(amount):
    return f"${amount:.2f}"


def fmt_duration(minutes):
    """95 -> '1 soat 35 daq'"""
    minutes = int(minutes)
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return f"{hours} soat {mins} daq"
    if hours:
        return f"{hours} soat"
    return f"{mins} daq"


def fmt_rate(rates):
    """Human-readable rate. Per-minute is the type actually in use, so it gets
    an hourly equivalent alongside it (a bare $/minute figure is hard to judge)."""
    stype = rates.get('salary_type', 'tariff')
    if stype == 'per_minute':
        per_min = rates.get('rate_per_minute', 0)
        return f"${per_min:g}/daq  (~{fmt_money(per_min * 60)}/soat)"
    if stype == 'monthly':
        return f"{fmt_money(rates.get('monthly_salary', 0))}/oy"
    return "Tarif"


def worked_minutes(check_in, check_out):
    if not check_in or not check_out:
        return 0
    return (check_out - check_in).total_seconds() / 60.0


# ==================== EMPLOYEE CARDS ====================

# Employee bottom-keyboard labels. Kept as constants because handlers match on
# the exact text Telegram sends back.
BTN_CHECK_IN = "✅ KELDIM"
BTN_CHECK_OUT = "🚪 KETDIM"
BTN_STATUS = "🏠 Holat"
BTN_MY_STATS = "📊 Hisobim"
BTN_CORRECTION = "📝 Tuzatish"


def employee_keyboard(user_id):
    """Bottom keyboard for employees. The primary button swaps between
    check-in and check-out depending on where they are in the day."""
    primary = BTN_CHECK_OUT if db.is_user_checked_in(user_id) else BTN_CHECK_IN
    return ReplyKeyboardMarkup(
        [
            [primary],
            [BTN_STATUS, BTN_MY_STATS],
            [BTN_CORRECTION],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def employee_status_card(user_id, full_name, note=None):
    """Status card an employee sees on /start, on check-in/out, and on refresh.
    Three states: not yet arrived, currently working, day finished."""
    now = utils.get_now()
    today = now.date()
    row = db.get_daily_attendance_for_user(user_id, today)
    rates = db.get_db_rates(user_id)

    header = (
        f"👤 <b>{full_name}</b>\n"
        f"<i>{fmt_date(now)} · {now.strftime('%H:%M')}</i>\n"
        f"{'━' * 18}\n"
    )

    if not row or not row['check_in']:
        body = (
            "\n⚪️ <b>Bugun hali kelmadingiz</b>\n"
            "\n<i>Ishni boshlaganingizda «✅ KELDIM» tugmasini bosing.</i>"
        )
    elif not row['check_out']:
        check_in = row['check_in']
        mins = worked_minutes(check_in, now)
        live_wage, _, _ = utils.calculate_wage(check_in, now, rates)
        body = (
            "\n🟢 <b>ISHDASIZ</b>\n\n"
            f"📥 Kelgan vaqt: <b>{check_in.strftime('%H:%M')}</b>\n"
            f"⏱ Ishlagan: <b>{fmt_duration(mins)}</b>\n"
            f"💰 Hozircha: <b>{fmt_money(live_wage)}</b>\n"
        )
    else:
        check_in, check_out = row['check_in'], row['check_out']
        mins = worked_minutes(check_in, check_out)
        body = (
            "\n✅ <b>Bugungi ish tugadi</b>\n\n"
            f"📥 Kelish: <b>{check_in.strftime('%H:%M')}</b>\n"
            f"📤 Ketish: <b>{check_out.strftime('%H:%M')}</b>\n"
            f"⏱ Jami: <b>{fmt_duration(mins)}</b>\n"
            f"💰 Bugun: <b>{fmt_money(row['total_wage'] or 0)}</b>\n"
        )

    text = header + body
    if note:
        text += f"\n{note}"
    return text


def employee_stats_card(user_id):
    """Monthly summary + recent days for one employee."""
    now = utils.get_now()
    start = now.replace(day=1).date()
    rows = db.get_user_month_details(user_id, start)

    total_wage = 0.0
    total_mins = 0.0
    days = 0
    for r in rows:
        if r['check_in'] and r['check_out']:
            days += 1
            total_wage += r['total_wage'] or 0
            total_mins += worked_minutes(r['check_in'], r['check_out'])

    text = (
        f"📊 <b>MENING HISOBIM</b>\n"
        f"<i>{fmt_month(now)}</i>\n"
        f"{'━' * 18}\n\n"
        f"📅 Ishlangan kunlar: <b>{days}</b>\n"
        f"⏱ Jami vaqt: <b>{fmt_duration(total_mins)}</b>\n"
        f"💰 Jami ish haqi: <b>{fmt_money(total_wage)}</b>\n"
    )

    recent = [r for r in rows if r['check_in']][-7:]
    if recent:
        text += f"\n{'━' * 18}\n<b>So'nggi kunlar</b>\n"
        for r in reversed(recent):
            ci = r['check_in'].strftime('%H:%M')
            co = r['check_out'].strftime('%H:%M') if r['check_out'] else "—"
            wage = fmt_money(r['total_wage'] or 0)
            text += f"<code>{r['date'].strftime('%d.%m')}  {ci}-{co}  {wage:>7}</code>\n"
    else:
        text += "\n<i>Bu oyda hali ma'lumot yo'q.</i>"

    return text
