"""Presentation layer: card text renderers + inline keyboard builders.

Kept separate from handler logic so the wording/layout of every screen lives
in one place. All user-facing text is Uzbek.
"""
import calendar
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

import database as db
import utils
import workdays

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


def fmt_money(amount, unit=True):
    """5231481.42 -> "5 231 481 so'm"

    Wages here run to seven digits, so the group separators carry the meaning
    while the fraction never did - nothing is priced below one so'm. unit=False
    drops the suffix inside the fixed-width <code> columns, where five more
    characters wrap the line on a phone.
    """
    grouped = f"{round(amount or 0):,}".replace(',', ' ')
    return f"{grouped} so'm" if unit else grouped


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
    an hourly equivalent alongside it (a bare per-minute figure is hard to judge)."""
    stype = rates.get('salary_type', 'tariff')
    if stype == 'per_minute':
        per_min = rates.get('rate_per_minute', 0)
        return f"{per_min:g} so'm/daq  (~{fmt_money(per_min * 60)}/soat)"
    if stype == 'monthly':
        label = f"{fmt_money(rates.get('monthly_salary', 0))}/oy"
        override = rates.get('overtime_per_minute') or 0
        if override:
            label += f"  (qo'shimcha {override:g} so'm/daq)"
        return label
    return "Tarif"


def wage_parts(row):
    """(base, overtime) for one attendance row.

    Rows written before the split was stored carry two zeros; their whole total
    counts as base, which is what it actually was for the per-minute employees
    who produced them.
    """
    total = row['total_wage'] or 0
    base = row['base_wage'] or 0
    overtime = row['overtime_wage'] or 0
    if not base and not overtime:
        return total, 0.0
    return base, overtime


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
    total_base = 0.0
    total_overtime = 0.0
    total_mins = 0.0
    days = 0
    for r in rows:
        if r['check_in'] and r['check_out']:
            days += 1
            total_wage += r['total_wage'] or 0
            base, overtime = wage_parts(r)
            total_base += base
            total_overtime += overtime
            total_mins += worked_minutes(r['check_in'], r['check_out'])

    # On a monthly salary the month's working-day count is the figure the pay
    # is divided by, so showing days worked without it says little.
    rates = db.get_db_rates(user_id)
    if rates.get('salary_type') == 'monthly':
        expected = workdays.working_days_in_month(now.year, now.month)
        days_line = f"📅 Ishlangan kunlar: <b>{days}</b> / {expected}\n"
    else:
        days_line = f"📅 Ishlangan kunlar: <b>{days}</b>\n"

    text = (
        f"📊 <b>MENING HISOBIM</b>\n"
        f"<i>{fmt_month(now)}</i>\n"
        f"{'━' * 18}\n\n"
        f"{days_line}"
        f"⏱ Jami vaqt: <b>{fmt_duration(total_mins)}</b>\n"
    )
    if total_overtime:
        text += (
            f"\n💼 Asosiy: <b>{fmt_money(total_base)}</b>\n"
            f"⭐ Qo'shimcha: <b>{fmt_money(total_overtime)}</b>\n"
            f"💰 Jami: <b>{fmt_money(total_wage)}</b>\n"
        )
    else:
        text += f"💰 Jami ish haqi: <b>{fmt_money(total_wage)}</b>\n"

    recent = [r for r in rows if r['check_in']][-7:]
    if recent:
        text += f"\n{'━' * 18}\n<b>So'nggi kunlar</b>\n"
        for r in reversed(recent):
            ci = r['check_in'].strftime('%H:%M')
            co = r['check_out'].strftime('%H:%M') if r['check_out'] else "—"
            wage = fmt_money(r['total_wage'] or 0, unit=False)
            text += f"<code>{r['date'].strftime('%d.%m')}  {ci}-{co}  {wage:>9}</code>\n"
    else:
        text += "\n<i>Bu oyda hali ma'lumot yo'q.</i>"

    return text


# ==================== ADMIN ====================

BTN_ADMIN_TODAY = "🏠 Bugun"
BTN_ADMIN_REPORT = "📊 Hisobot"
BTN_ADMIN_EMPLOYEES = "👥 Xodimlar"
BTN_ADMIN_CORRECTIONS = "🔔 Tuzatishlar"
BTN_ADMIN_SETTINGS = "⚙️ Sozlamalar"


def admin_keyboard():
    return ReplyKeyboardMarkup(
        [
            [BTN_ADMIN_TODAY, BTN_ADMIN_REPORT],
            [BTN_ADMIN_EMPLOYEES, BTN_ADMIN_CORRECTIONS],
            [BTN_ADMIN_SETTINGS],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def settings_card():
    """Current work-hour settings + a button per editable value."""
    import settings as st

    text = (
        f"⚙️ <b>SOZLAMALAR</b>\n"
        f"{'━' * 18}\n\n"
        f"<i>O'zgartirish uchun pastdagi tugmani bosing.</i>\n\n"
    )
    keyboard = []
    for key, label, value, desc in st.all_times():
        text += f"{label}: <b>{value}</b>\n<i>  {desc}</i>\n\n"
        keyboard.append([InlineKeyboardButton(f"{label} — {value}", callback_data=f"set:{key}")])

    keyboard.append([InlineKeyboardButton("📅 Rasmiy dam olish kunlari", callback_data="hol:open")])

    return text, InlineKeyboardMarkup(keyboard)


def holidays_card(year, month):
    """Official days off for one month, and the working-day count they drive.

    The count is spelled out (days - Sundays - holidays) because it is the
    divisor behind every monthly salary: an admin who marks a day should see
    straight away what it did to the month.
    """
    first = datetime(year, month, 1)
    rows = db.list_holidays(year, month)
    days_in_month = calendar.monthrange(year, month)[1]
    sundays = sum(
        1 for day in range(1, days_in_month + 1)
        if datetime(year, month, day).weekday() == 6
    )

    text = (
        f"📅 <b>RASMIY DAM OLISH KUNLARI</b>\n"
        f"<i>{fmt_month(first)}</i>\n"
        f"{'━' * 18}\n\n"
        f"Ish kunlari: <b>{workdays.working_days_in_month(year, month)}</b>\n"
        f"<i>{days_in_month} kun − {sundays} yakshanba − {len(rows)} bayram</i>\n\n"
    )
    if rows:
        text += "<b>Belgilangan kunlar:</b>\n"
        for row in rows:
            note = f" — {row['note']}" if row['note'] else ""
            text += f"• {fmt_date(row['date'])}{note}\n"
        text += "\n"
    else:
        text += "<i>Bu oyda bayram kunlari belgilanmagan.</i>\n\n"
    text += "<i>Oylik maosh shu ish kunlariga bo'linadi.</i>"

    keyboard = [[InlineKeyboardButton(
        "➕ Kun qo'shish", callback_data=f"hol:add:{year}-{month:02d}"
    )]]
    for row in rows:
        keyboard.append([InlineKeyboardButton(
            f"🗑 {fmt_date(row['date'])}",
            callback_data=f"hol:del:{row['date'].isoformat()}"
        )])

    prev_year, prev_month = (year, month - 1) if month > 1 else (year - 1, 12)
    next_year, next_month = (year, month + 1) if month < 12 else (year + 1, 1)
    keyboard.append([
        InlineKeyboardButton(f"◀ {MONTHS_UZ[prev_month - 1].capitalize()}",
                             callback_data=f"hol:m:{prev_year}-{prev_month:02d}"),
        InlineKeyboardButton(f"{MONTHS_UZ[next_month - 1].capitalize()} ▶",
                             callback_data=f"hol:m:{next_year}-{next_month:02d}"),
    ])

    return text, InlineKeyboardMarkup(keyboard)


def admin_dashboard_card():
    """Live 'who is working right now' view - the admin's home screen."""
    now = utils.get_now()
    today = now.date()
    employees = db.get_employees()

    working, done, absent = [], [], []
    day_total = 0.0

    for emp in employees:
        row = db.get_daily_attendance_for_user(emp['id'], today)
        if not row or not row['check_in']:
            absent.append(emp['full_name'])
            continue
        if row['check_out']:
            wage = row['total_wage'] or 0
            done.append((emp['full_name'], row['check_in'], row['check_out'], wage))
        else:
            rates = db.get_db_rates(emp['id'])
            wage, _, _ = utils.calculate_wage(row['check_in'], now, rates)
            working.append((emp['full_name'], row['check_in'], wage))
        day_total += wage

    text = (
        f"🛠 <b>BOSHQARUV PANELI</b>\n"
        f"<i>{fmt_date(now)} · {now.strftime('%H:%M')}</i>\n"
        f"{'━' * 18}\n"
    )

    if working:
        text += f"\n🟢 <b>Ishlayapti ({len(working)})</b>\n"
        for name, ci, wage in working:
            text += f"<code>{name[:12]:<12} {ci.strftime('%H:%M')}  {fmt_money(wage, unit=False):>9}</code>\n"

    if done:
        text += f"\n✅ <b>Ish tugatgan ({len(done)})</b>\n"
        for name, ci, co, wage in done:
            span = f"{ci.strftime('%H:%M')}-{co.strftime('%H:%M')}"
            text += f"<code>{name[:12]:<12} {span}  {fmt_money(wage, unit=False):>9}</code>\n"

    if absent:
        text += f"\n⚪️ <b>Kelmagan ({len(absent)})</b>\n"
        text += "".join(f"<code>{n}</code>\n" for n in absent)

    if not employees:
        text += "\n<i>Hali xodimlar qo'shilmagan.</i>\n"

    text += f"\n{'━' * 18}\n💵 <b>Bugun jami: {fmt_money(day_total)}</b>"

    pending = db.count_pending_corrections()
    if pending:
        text += f"\n🔔 <b>Yangi so'rovlar: {pending}</b>"

    return text


def admin_employee_list():
    """Employee picker with a live status dot on each name.

    'Add employee' is an inline button here rather than a bottom-keyboard one,
    so opening this screen doesn't replace the admin's main menu (which used to
    force a trip through an 'Ortga' button to get back)."""
    employees = db.get_employees()
    add_button = [InlineKeyboardButton("➕ Yangi xodim", callback_data="addemp")]

    if not employees:
        return (
            "👥 <b>XODIMLAR</b>\n\n<i>Hali xodimlar qo'shilmagan.</i>",
            InlineKeyboardMarkup([add_button]),
        )

    text = f"👥 <b>XODIMLAR ({len(employees)})</b>\n<i>Batafsil ko'rish uchun tanlang:</i>"
    keyboard = []
    for emp in employees:
        dot = "🟢" if db.is_user_checked_in(emp['id']) else "⚪️"
        keyboard.append([InlineKeyboardButton(
            f"{dot}  {emp['full_name']}", callback_data=f"edit_{emp['id']}"
        )])
    keyboard.append(add_button)
    return text, InlineKeyboardMarkup(keyboard)


def admin_employee_card(emp_id):
    """Detail card for one employee: contact, rate, live status, month totals."""
    emp = db.get_user(emp_id)
    if not emp:
        return "❌ Xodim topilmadi."

    now = utils.get_now()
    rates = db.get_db_rates(emp_id)
    row = db.get_daily_attendance_for_user(emp_id, now.date())

    if row and row['check_in'] and not row['check_out']:
        status = f"🟢 Hozir ishlayapti — <b>{row['check_in'].strftime('%H:%M')}</b> dan"
    elif row and row['check_out']:
        status = f"✅ Bugun ish tugatgan — {row['check_in'].strftime('%H:%M')}-{row['check_out'].strftime('%H:%M')}"
    else:
        status = "⚪️ Bugun kelmagan"

    month_rows = db.get_user_month_details(emp_id, now.replace(day=1).date())
    days = total_wage = total_mins = 0
    total_base = total_overtime = 0.0
    for r in month_rows:
        if r['check_in'] and r['check_out']:
            days += 1
            total_wage += r['total_wage'] or 0
            base, overtime = wage_parts(r)
            total_base += base
            total_overtime += overtime
            total_mins += worked_minutes(r['check_in'], r['check_out'])

    if rates.get('salary_type') == 'monthly':
        expected = workdays.working_days_in_month(now.year, now.month)
        days_line = f"<code>Kunlar:  {days} / {expected}</code>\n"
    else:
        days_line = f"<code>Kunlar:  {days}</code>\n"

    money_lines = f"<code>Hisob:   {fmt_money(total_wage)}</code>"
    if total_overtime:
        money_lines = (
            f"<code>Asosiy:  {fmt_money(total_base)}</code>\n"
            f"<code>Qo'shim: {fmt_money(total_overtime)}</code>\n"
            f"<code>Jami:    {fmt_money(total_wage)}</code>"
        )

    return (
        f"👤 <b>{emp['full_name'].upper()}</b>\n"
        f"{'━' * 18}\n\n"
        f"📞 <code>{emp['phone']}</code>\n"
        f"💵 Stavka: <b>{fmt_rate(rates)}</b>\n"
        f"{status}\n\n"
        f"📊 <b>{fmt_month(now)}</b>\n"
        f"{days_line}"
        f"<code>Vaqt:    {fmt_duration(total_mins)}</code>\n"
        f"{money_lines}"
    )


def analytics_card(all_stats, days=30):
    """Team-wide analytics: totals plus earnings and punctuality rankings."""
    if not all_stats:
        return f"📈 <b>TAHLIL</b>\n\n<i>Hali ma'lumot yo'q.</i>"

    total_wage = sum(s['total_wage'] for s in all_stats)
    total_mins = sum(s['total_minutes'] for s in all_stats)
    total_days = sum(s['days_worked'] for s in all_stats)

    text = (
        f"📈 <b>TAHLIL</b>\n"
        f"<i>So'nggi {days} kun</i>\n"
        f"{'━' * 18}\n\n"
        f"👥 Xodimlar: <b>{len(all_stats)}</b>\n"
        f"📅 Ishlangan kunlar: <b>{total_days}</b>\n"
        f"⏱ Jami vaqt: <b>{fmt_duration(total_mins)}</b>\n"
        f"💰 Jami ish haqi: <b>{fmt_money(total_wage)}</b>\n"
    )

    text += f"\n{'━' * 18}\n💵 <b>Ish haqi bo'yicha</b>\n"
    for i, s in enumerate(all_stats, 1):
        text += f"<code>{i}. {s['name'][:12]:<12} {fmt_money(s['total_wage'], unit=False):>9}</code>\n"

    punctual = sorted(all_stats, key=lambda s: (s['late_days'], -s['days_worked']))
    text += f"\n{'━' * 18}\n⏰ <b>Vaqtida kelish bo'yicha</b>\n"
    for i, s in enumerate(punctual, 1):
        label = "kechikishsiz" if s['late_days'] == 0 else f"{s['late_days']} marta kechikkan"
        text += f"<code>{i}. {s['name'][:12]:<12}</code> <i>{label}</i>\n"

    return text


def employee_analytics_card(stats):
    """Deep-dive card for a single employee."""
    if not stats:
        return "❌ Xodim topilmadi."

    text = (
        f"📈 <b>{stats['name'].upper()}</b>\n"
        f"<i>So'nggi {stats['days']} kun</i>\n"
        f"{'━' * 18}\n\n"
        f"📞 <code>{stats['phone']}</code>\n"
        f"💵 Stavka: <b>{fmt_rate(stats['rates'])}</b>\n\n"
        f"📅 Ishlangan kunlar: <b>{stats['days_worked']}</b>\n"
        f"⏱ Jami vaqt: <b>{fmt_duration(stats['total_minutes'])}</b>\n"
        f"💰 Jami ish haqi: <b>{fmt_money(stats['total_wage'])}</b>\n"
    )

    if stats['days_worked']:
        text += (
            f"\n{'━' * 18}\n<b>Kunlik o'rtacha</b>\n"
            f"⏱ Vaqt: <b>{fmt_duration(stats['avg_minutes_per_day'])}</b>\n"
            f"💰 Ish haqi: <b>{fmt_money(stats['avg_wage_per_day'])}</b>\n"
        )

    if stats['late_days']:
        text += f"\n⚠️ Kechikkan kunlar: <b>{stats['late_days']}</b>"
    else:
        text += f"\n✅ <b>Hech qachon kechikmagan</b>"

    return text


def admin_month_report_card(start_date):
    """Per-employee monthly totals with a grand total."""
    rows = db.get_month_attendance_details(start_date)
    if not rows:
        return f"📊 <b>{fmt_month(start_date)}</b>\n\n<i>Bu oyda ma'lumot yo'q.</i>"

    per_employee = {}
    for r in rows:
        name = r['full_name']
        bucket = per_employee.setdefault(
            name, {'wage': 0.0, 'days': 0, 'mins': 0.0, 'base': 0.0, 'overtime': 0.0}
        )
        if r['check_in'] and r['check_out']:
            bucket['days'] += 1
            bucket['wage'] += r['total_wage'] or 0
            base, overtime = wage_parts(r)
            bucket['base'] += base
            bucket['overtime'] += overtime
            bucket['mins'] += worked_minutes(r['check_in'], r['check_out'])

    text = (
        f"📊 <b>OYLIK HISOBOT</b>\n"
        f"<i>{fmt_month(start_date)}</i>\n"
        f"{'━' * 18}\n\n"
    )
    grand = 0.0
    grand_overtime = 0.0
    for name, b in sorted(per_employee.items(), key=lambda kv: -kv[1]['wage']):
        grand += b['wage']
        grand_overtime += b['overtime']
        text += (
            f"👤 <b>{name}</b>\n"
            f"<code>  {b['days']} kun · {fmt_duration(b['mins'])}</code>\n"
        )
        if b['overtime']:
            text += (
                f"<code>  {fmt_money(b['base'], unit=False)} + {fmt_money(b['overtime'], unit=False)} qo'shimcha</code>\n"
                f"<code>  = {fmt_money(b['wage'])}</code>\n\n"
            )
        else:
            text += f"<code>  {fmt_money(b['wage'])}</code>\n\n"

    text += f"{'━' * 18}\n"
    if grand_overtime:
        text += f"⭐ <b>Qo'shimcha: {fmt_money(grand_overtime)}</b>\n"
    text += f"💵 <b>JAMI: {fmt_money(grand)}</b>"
    return text
