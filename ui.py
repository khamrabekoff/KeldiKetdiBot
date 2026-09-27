"""Presentation layer: card text renderers + inline keyboard builders.

Kept separate from handler logic so the wording/layout of every screen lives
in one place. All user-facing text is Uzbek.
"""
import calendar
import html
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

import analytics
import database as db
import messages as msg
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
    """Money as the bot writes it. The formatting itself lives in utils, so
    the Excel and PDF exports spell amounts the same way this screen does."""
    return utils.format_money(amount, unit)


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
        return f"{utils.format_rate(per_min)}/daq  (~{fmt_money(per_min * 60)}/soat)"
    if stype == 'monthly':
        label = f"{fmt_money(rates.get('monthly_salary', 0))}/oy"
        override = rates.get('overtime_per_minute') or 0
        if override:
            label += f"  (qo'shimcha {utils.format_rate(override)}/daq)"
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


def esc(text):
    """Typed-in text goes into HTML messages; a stray '<' would otherwise
    make Telegram reject the whole message."""
    return html.escape(text or '', quote=False)


def month_advances(user_id, day):
    """Active advances of one employee in the month containing `day`."""
    start = day.replace(day=1)
    return db.get_advances(start, utils.next_month(start), user_id)


def advance_lines(advances, limit=10):
    """'20.09      300.00 note' per advance, newest last."""
    lines = ""
    hidden = len(advances) - limit
    if hidden > 0:
        lines += f"<i>… yana {hidden} ta</i>\n"
    for a in advances[-limit:]:
        note = f" <i>{esc(a['note'])}</i>" if a['note'] else ""
        lines += f"<code>{a['date'].strftime('%d.%m')}  {fmt_money(a['amount'], unit=False):>10}</code>{note}\n"
    return lines


# ==================== EMPLOYEE CARDS ====================

# Employee bottom-keyboard labels. Kept as constants because handlers match on
# the exact text Telegram sends back.
BTN_CHECK_IN = "✅ KELDIM"
BTN_CHECK_OUT = "🚪 KETDIM"
BTN_STATUS = "🏠 Holat"
BTN_MY_STATS = "📊 Hisobim"
BTN_CORRECTION = "📝 Tuzatish"
BTN_ADVANCE = "💸 Avans"


def employee_keyboard(user_id):
    """Bottom keyboard for employees. The primary button swaps between
    check-in and check-out depending on where they are in the day."""
    primary = BTN_CHECK_OUT if db.is_user_checked_in(user_id) else BTN_CHECK_IN
    return ReplyKeyboardMarkup(
        [
            [primary],
            [BTN_STATUS, BTN_MY_STATS],
            [BTN_CORRECTION, BTN_ADVANCE],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def employee_status_card(user_id, full_name, note=None):
    """Status card an employee sees on /start, on check-in/out, and on refresh.
    Three states: not yet arrived, currently working, day finished."""
    import settings as st

    now = utils.get_now()
    today = now.date()
    row = db.get_daily_attendance_for_user(user_id, today)
    show_earnings = st.get_bool('show_employee_earnings')

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
        body = (
            "\n🟢 <b>ISHDASIZ</b>\n\n"
            f"📥 Kelgan vaqt: <b>{check_in.strftime('%H:%M')}</b>\n"
            f"⏱ Ishlagan: <b>{fmt_duration(mins)}</b>\n"
        )
        if show_earnings:
            live_wage, _, _ = utils.calculate_wage(check_in, now, db.get_db_rates(user_id))
            body += f"💰 Hozircha: <b>{fmt_money(live_wage)}</b>\n"
    else:
        check_in, check_out = row['check_in'], row['check_out']
        mins = worked_minutes(check_in, check_out)
        body = (
            "\n✅ <b>Bugungi ish tugadi</b>\n\n"
            f"📥 Kelish: <b>{check_in.strftime('%H:%M')}</b>\n"
            f"📤 Ketish: <b>{check_out.strftime('%H:%M')}</b>\n"
            f"⏱ Jami: <b>{fmt_duration(mins)}</b>\n"
        )
        if show_earnings:
            body += f"💰 Bugun: <b>{fmt_money(row['total_wage'] or 0)}</b>\n"

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
    import settings as st

    # Where the client keeps pay to itself, this card stays a plain time sheet.
    show_earnings = st.get_bool('show_employee_earnings')
    if show_earnings and total_overtime:
        text += (
            f"\n💼 Asosiy: <b>{fmt_money(total_base)}</b>\n"
            f"⭐ Qo'shimcha: <b>{fmt_money(total_overtime)}</b>\n"
            f"💰 Jami: <b>{fmt_money(total_wage)}</b>\n"
        )
    elif show_earnings:
        text += f"💰 Jami ish haqi: <b>{fmt_money(total_wage)}</b>\n"

    # Advances are the employee's own record, so they see them even where pay
    # is hidden. Carry, payments and the balance would reveal the pay.
    advances = month_advances(user_id, start)
    balance = analytics.employee_month(user_id, start)
    if balance and (balance['advance'] or balance['carry_in'] or balance['paid']):
        if show_earnings and balance['carry_in']:
            text += f"↪️ O'tgan oydan: <b>{fmt_money(balance['carry_in'])}</b>\n"
        if balance['advance']:
            text += f"💸 Avans: <b>{fmt_money(balance['advance'])}</b>\n"
        if show_earnings and balance['paid']:
            text += f"✅ To'langan: <b>{fmt_money(balance['paid'])}</b>\n"
        if show_earnings:
            text += f"💵 Qoldiq: <b>{fmt_money(balance['to_pay'])}</b>\n"

    recent = [r for r in rows if r['check_in']][-7:]
    if recent:
        text += f"\n{'━' * 18}\n<b>So'nggi kunlar</b>\n"
        for r in reversed(recent):
            ci = r['check_in'].strftime('%H:%M')
            co = r['check_out'].strftime('%H:%M') if r['check_out'] else "—"
            wage = fmt_money(r['total_wage'] or 0, unit=False)
            tail = f"  {wage:>10}" if show_earnings else ""
            text += f"<code>{r['date'].strftime('%d.%m')}  {ci}-{co}{tail}</code>\n"
    else:
        text += "\n<i>Bu oyda hali ma'lumot yo'q.</i>"

    if advances:
        text += f"\n{'━' * 18}\n<b>Avanslar</b>\n" + advance_lines(advances)

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

    for key, label, value, desc in st.all_flags():
        state = "✅ Ha" if value else "🚫 Yo'q"
        text += f"{label}: <b>{state}</b>\n<i>  {desc}</i>\n\n"
        keyboard.append([InlineKeyboardButton(f"{label} — {state}", callback_data=f"flag:{key}")])

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
            text += f"<code>{name[:12]:<12} {ci.strftime('%H:%M')}  {fmt_money(wage, unit=False):>10}</code>\n"

    if done:
        text += f"\n✅ <b>Ish tugatgan ({len(done)})</b>\n"
        for name, ci, co, wage in done:
            span = f"{ci.strftime('%H:%M')}-{co.strftime('%H:%M')}"
            text += f"<code>{name[:12]:<12} {span}  {fmt_money(wage, unit=False):>10}</code>\n"

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
    force a trip through an 'Ortga' button to get back).

    People the admin has added but who haven't opened the bot yet are listed
    separately. They hold no Telegram id, so they are not in `users` at all -
    and leaving them off this screen made adding an employee look like it had
    silently failed."""
    employees = db.get_employees()
    pending = db.list_pending_users()
    add_button = [InlineKeyboardButton("➕ Yangi xodim", callback_data="addemp")]

    if not employees and not pending:
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

    if pending:
        text += (
            f"\n\n⏳ <b>Kutilmoqda ({len(pending)})</b>\n"
            f"<i>Botni ochib, o'z raqamlarini yuborishlari kerak:</i>\n"
        )
        for row in pending:
            text += f"<code>{row['full_name']} · +{row['phone']}</code>\n"
            keyboard.append([InlineKeyboardButton(
                f"🗑  {row['full_name']} — bekor qilish", callback_data=f"pdel:{row['phone']}"
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

    balance = analytics.employee_month(emp_id, now.date())
    if balance and (balance['advance'] or balance['carry_in'] or balance['paid']):
        if balance['carry_in']:
            money_lines += f"\n<code>O'tgan:  {fmt_money(balance['carry_in'])}</code>"
        if balance['advance']:
            money_lines += f"\n<code>Avans:   {fmt_money(balance['advance'])}</code>"
        if balance['paid']:
            money_lines += f"\n<code>To'lov:  {fmt_money(balance['paid'])}</code>"
        money_lines += f"\n<code>Qoldiq:  {fmt_money(balance['to_pay'])}</code>"
    advances = month_advances(emp_id, now.date())
    if advances:
        money_lines += f"\n\n💸 <b>Avanslar</b>\n" + advance_lines(advances).rstrip('\n')

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
        text += f"<code>{i}. {s['name'][:12]:<12} {fmt_money(s['total_wage'], unit=False):>10}</code>\n"

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
    """Per-employee monthly totals, advances, and what the admin still has to
    pay - per person and in total."""
    payroll = analytics.month_payroll(start_date)
    if not payroll['employees']:
        return f"📊 <b>{fmt_month(start_date)}</b>\n\n<i>Bu oyda ma'lumot yo'q.</i>"

    text = (
        f"📊 <b>OYLIK HISOBOT</b>\n"
        f"<i>{fmt_month(start_date)}</i>\n"
        f"{'━' * 18}\n\n"
    )
    for p in payroll['employees']:
        text += (
            f"👤 <b>{p['name']}</b>\n"
            f"<code>  {p['days']} kun · {fmt_duration(p['minutes'])}</code>\n"
        )
        if p['overtime']:
            text += (
                f"<code>  {fmt_money(p['base'], unit=False)} + {fmt_money(p['overtime'], unit=False)} qo'shimcha</code>\n"
                f"<code>  = {fmt_money(p['wage'])}</code>\n"
            )
        else:
            text += f"<code>  {fmt_money(p['wage'])}</code>\n"
        text += balance_lines(p)
        text += "\n"

    totals = payroll['totals']
    text += f"{'━' * 18}\n"
    if totals['overtime']:
        text += f"⭐ <b>Qo'shimcha: {fmt_money(totals['overtime'])}</b>\n"
    text += f"💵 <b>JAMI: {fmt_money(totals['wage'])}</b>"
    if totals['carry_in']:
        text += f"\n↪️ <b>O'tgan oydan: {fmt_money(totals['carry_in'])}</b>"
    if totals['advance']:
        text += f"\n💸 <b>Avans: {fmt_money(totals['advance'])}</b>"
    if totals['paid']:
        text += f"\n✅ <b>To'langan: {fmt_money(totals['paid'])}</b>"
    text += f"\n💰 <b>TO'LASH KERAK: {fmt_money(totals['to_pay'])}</b>"
    return text


def is_paid_off(entry):
    return entry['settled'] and round(entry['to_pay'], 2) == 0


def balance_lines(entry):
    """What turns the wage into 'to pay' for one employee, one <code> line per
    step - empty when nothing does, so a plain month reads as it always did."""
    if not (entry['carry_in'] or entry['advance'] or entry['paid']):
        return ""
    lines = ""
    if entry['carry_in']:
        sign = '+' if entry['carry_in'] > 0 else '−'
        lines += f"<code>  {sign} {fmt_money(abs(entry['carry_in']), unit=False)} o'tgan oydan</code>\n"
    if entry['advance']:
        lines += f"<code>  − {fmt_money(entry['advance'], unit=False)} avans</code>\n"
    if entry['paid']:
        lines += f"<code>  − {fmt_money(entry['paid'], unit=False)} to'langan</code>\n"
    mark = " ✅" if is_paid_off(entry) else ""
    lines += f"<code>  = {fmt_money(entry['to_pay'])} to'lash kerak</code>{mark}\n"
    return lines


def admin_report_keyboard(ym):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📥 Excel", callback_data=f"repx:xls:{ym}"),
            InlineKeyboardButton("📄 PDF", callback_data=f"repx:pdf:{ym}"),
        ],
        [InlineKeyboardButton("💰 To'lov", callback_data=f"pay:list:{ym}")],
    ])


# ==================== PAYMENTS ====================
# The admin marks salary as paid, per employee per month, from the monthly
# report. A settled month passes whatever is left of its balance on to the next.

def payment_list_card(start_date):
    """Who still has to be paid for a month, one button per employee."""
    payroll = analytics.month_payroll(start_date)
    ym = start_date.strftime('%Y-%m')
    text = (
        f"💰 <b>TO'LOV</b>\n"
        f"<i>{fmt_month(start_date)}</i>\n"
        f"{'━' * 18}\n\n"
    )
    keyboard = []
    if not payroll['employees']:
        text += "<i>Bu oyda ma'lumot yo'q.</i>"
    else:
        text += (
            "Kimga to'laysiz? Xodimni tanlang.\n\n"
            f"💰 Jami to'lash kerak: <b>{fmt_money(payroll['totals']['to_pay'])}</b>"
        )
        for entry in payroll['employees']:
            mark = "✅" if is_paid_off(entry) else "💰"
            keyboard.append([InlineKeyboardButton(
                f"{mark} {entry['name']} · {fmt_money(entry['to_pay'])}",
                callback_data=f"pay:emp:{entry['user_id']}:{ym}",
            )])
    keyboard.append([InlineKeyboardButton("◀ Hisobot", callback_data=f"rep:{ym}")])
    return text, InlineKeyboardMarkup(keyboard)


def payment_employee_card(user_id, start_date):
    """One employee's month: how the amount to pay is made up, the payments
    already recorded, and the button that pays or settles it."""
    ym = start_date.strftime('%Y-%m')
    entry = analytics.employee_month(user_id, start_date)
    back = [InlineKeyboardButton("◀ Ro'yxat", callback_data=f"pay:list:{ym}")]
    if not entry:
        return "❌ Bu oyda ma'lumot yo'q.", InlineKeyboardMarkup([back])

    to_pay = round(entry['to_pay'], 2)
    text = (
        f"💰 <b>{esc(entry['name'])}</b>\n"
        f"<i>{fmt_month(start_date)} uchun</i>\n"
        f"{'━' * 18}\n\n"
        f"<code>Ish haqi:  {fmt_money(entry['wage'])}</code>\n"
    )
    if entry['carry_in']:
        text += f"<code>O'tgan oy: {fmt_money(entry['carry_in'])}</code>\n"
    if entry['advance']:
        text += f"<code>Avans:     {fmt_money(-entry['advance'])}</code>\n"
    if entry['paid']:
        text += f"<code>To'langan: {fmt_money(-entry['paid'])}</code>\n"
    text += f"\n💰 To'lash kerak: <b>{fmt_money(to_pay)}</b>\n"

    payments = db.get_payments(start_date, user_id)
    if payments:
        text += "\n<b>To'lovlar:</b>\n"
        for p in payments:
            text += f"<code>{p['created_at'].strftime('%d.%m %H:%M')}  {fmt_money(p['amount'])}</code>\n"

    keyboard = []
    cents = int(round(to_pay * 100))
    if to_pay > 0:
        keyboard.append([InlineKeyboardButton(
            f"✅ {fmt_money(to_pay)} to'landi", callback_data=f"pay:do:{user_id}:{ym}:{cents}"
        )])
    elif not entry['settled']:
        if to_pay < 0:
            text += (f"\n<i>Avans ish haqidan {fmt_money(-to_pay)} ko'p. Oyni yopsangiz, bu summa "
                     f"keyingi oy hisobidan ushlab qolinadi.</i>\n")
        keyboard.append([InlineKeyboardButton(
            "🔒 Oyni yopish", callback_data=f"pay:do:{user_id}:{ym}:{cents}"
        )])
    elif to_pay == 0:
        text += "\n✅ <b>To'liq to'langan.</b>\n"
    else:
        text += f"\n<i>Oy yopilgan: {fmt_money(-to_pay)} keyingi oyga qarz bo'lib o'tadi.</i>\n"

    keyboard.append([InlineKeyboardButton("✏️ Boshqa summa", callback_data=f"pay:sum:{user_id}:{ym}")])
    for p in payments:
        keyboard.append([InlineKeyboardButton(
            f"🗑 {p['created_at'].strftime('%d.%m')} · {fmt_money(p['amount'])} — bekor qilish",
            callback_data=f"pay:void:{p['id']}",
        )])
    keyboard.append(back)
    return text, InlineKeyboardMarkup(keyboard)


def payment_sum_prompt(name, start_date):
    return (
        f"💰 <b>{esc(name)}</b> — {fmt_month(start_date)}\n\n"
        "Qancha to'ladingiz? Summani yozing.\n"
        "<i>Masalan: 250. Qolgani keyingi oyga o'tadi.</i>\n\n"
        "Bekor qilish uchun /cancel"
    )


def payment_employee_text(start_date, amount, show_amount):
    """To the employee once the admin records their pay."""
    if show_amount:
        return f"✅ {fmt_month(start_date)} uchun ish haqi to'landi: <b>{fmt_money(amount)}</b>"
    return f"✅ {fmt_month(start_date)} uchun ish haqingiz to'landi."


def payment_debt_text(start_date, debt):
    """To the employee when a month closes with advances above the pay."""
    return (
        f"🔒 {fmt_month(start_date)} hisobi yopildi.\n"
        f"Avans ish haqidan <b>{fmt_money(debt)}</b> ko'p edi — bu summa "
        f"{fmt_month(utils.next_month(start_date))} hisobidan ushlab qolinadi."
    )


def payment_voided_text(payment, show_amount):
    amount = f" {fmt_money(payment['amount'])}" if show_amount and payment['amount'] else ""
    return (
        f"❌ {fmt_month(payment['month'])} uchun{amount} to'lov yozuvi admin tomonidan bekor qilindi."
    )


# ==================== ADVANCES ====================
# An employee records cash taken before payday; admins are told at once and
# can void a mistaken entry. Reports take it off the month's pay.

BTN_ADVANCE_SKIP_NOTE = "⏭ Izohsiz"
BTN_ADVANCE_CONFIRM = "✅ Tasdiqlash"
ADVANCE_NOTE_LIMIT = 200

ADVANCE_NOTE_PROMPT = (
    "📝 Izoh yozing: nima uchun olindi?\n"
    "<i>Majburiy emas — izohsiz davom etish uchun «⏭ Izohsiz» tugmasini bosing.</i>"
)
ADVANCE_BAD_AMOUNT = "❌ Summani raqam bilan yozing. Masalan: <code>300</code>"


def advance_amount_prompt(user_id):
    text = (
        "💸 <b>AVANS</b>\n"
        f"{'━' * 18}\n\n"
        "Qancha pul oldingiz? Summani yozing.\n"
        "<i>Masalan: 300</i>"
    )
    taken = month_advances(user_id, utils.get_now().date())
    if taken:
        text += (
            f"\n\n<i>Bu oy olingan: {fmt_money(sum(a['amount'] for a in taken))} "
            f"({len(taken)} marta)</i>"
        )
    return text


def advance_back_keyboard():
    return ReplyKeyboardMarkup([[msg.BTN_BACK]], resize_keyboard=True)


def advance_note_keyboard():
    return ReplyKeyboardMarkup([[BTN_ADVANCE_SKIP_NOTE], [msg.BTN_BACK]], resize_keyboard=True)


def advance_confirm_keyboard():
    return ReplyKeyboardMarkup([[msg.BTN_BACK, BTN_ADVANCE_CONFIRM]], resize_keyboard=True)


def advance_admin_amount_prompt(employee):
    """The admin hands cash over and enters it for the employee."""
    text = (
        "💸 <b>AVANS BERISH</b>\n"
        f"{'━' * 18}\n\n"
        f"👤 <b>{esc(employee['full_name'])}</b>\n\n"
        "Qancha berdingiz? Summani yozing.\n"
        "<i>Masalan: 300</i>"
    )
    taken = month_advances(employee['id'], utils.get_now().date())
    if taken:
        text += (
            f"\n\n<i>Bu oy olingan: {fmt_money(sum(a['amount'] for a in taken))} "
            f"({len(taken)} marta)</i>"
        )
    return text


def advance_confirm_text(amount, note, name=None):
    text = "Tasdiqlaysizmi?\n\n"
    if name:
        text += f"👤 Xodim: <b>{esc(name)}</b>\n"
    text += (
        f"💰 Summa: <b>{fmt_money(amount)}</b>\n"
        f"📅 Sana: <b>{fmt_date(utils.get_now())}</b>\n"
    )
    if note:
        text += f"📝 Izoh: <i>{esc(note)}</i>\n"
    return text


def advance_recorded_text(advance):
    """To the admin who entered an advance for someone."""
    return (
        f"✅ <b>Avans yozildi:</b> {esc(advance['full_name'] or '?')} — "
        f"{fmt_money(advance['amount'])}\n"
        f"<i>Xodim va boshqa adminlar xabardor qilindi.</i>"
    )


def advance_given_text(advance):
    """To the employee, when an admin has entered an advance for them."""
    created = advance['created_at']
    text = (
        "💸 <b>Sizga avans yozildi</b>\n\n"
        f"💰 Summa: <b>{fmt_money(advance['amount'])}</b>\n"
        f"📅 {fmt_date(created)} · {created.strftime('%H:%M')}\n"
    )
    if advance['note']:
        text += f"📝 Izoh: <i>{esc(advance['note'])}</i>\n"
    text += "\n<i>Xato bo'lsa, admin bilan gaplashing.</i>"
    return text


def advance_saved_note(amount):
    return f"✅ <b>Avans qayd etildi: {fmt_money(amount)}</b>\n<i>Admin xabardor qilindi.</i>"


def advance_admin_card(advance):
    """What admins get the moment an employee records an advance, and what
    that message becomes once one of them voids it."""
    created = advance['created_at']
    month_total = sum(a['amount'] for a in month_advances(advance['user_id'], advance['date']))
    text = (
        "💸 <b>AVANS OLINDI</b>\n"
        f"{'━' * 18}\n\n"
        f"👤 Xodim: <b>{esc(advance['full_name'] or '?')}</b>\n"
        f"💰 Summa: <b>{fmt_money(advance['amount'])}</b>\n"
        f"📅 {fmt_date(created)} · {created.strftime('%H:%M')}\n"
    )
    if advance['note']:
        text += f"📝 Izoh: <i>{esc(advance['note'])}</i>\n"
    if advance['created_by']:
        text += f"✍️ Admin yozdi: <b>{esc(advance['created_by_name'] or '?')}</b>\n"
    text += f"\n<i>{fmt_month(created)} jami avans: {fmt_money(month_total)}</i>"
    if advance['status'] != 'ACTIVE':
        text += "\n\n❌ <b>Bekor qilingan</b>"
    return text


def advance_void_keyboard(advance_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ Bekor qilish", callback_data=f"adv:void:{advance_id}")
    ]])


def advance_voided_text(advance):
    """To the employee, once an admin has voided their entry."""
    d = advance['date']
    return (
        f"❌ {d.day}-{MONTHS_UZ[d.month - 1]}dagi {fmt_money(advance['amount'])} "
        f"avansingiz admin tomonidan bekor qilindi.\n"
        f"<i>Xato bo'lsa, admin bilan gaplashing.</i>"
    )
