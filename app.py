import logging
import asyncio
import os
import subprocess
import threading
from datetime import datetime, time, timedelta
from io import BytesIO

from flask import Flask, request, jsonify
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.error import NetworkError, TimedOut
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters, ContextTypes

import openpyxl
from openpyxl.styles import Font

import database as db
import messages as msg
import utils
import analytics
import audit
import excel_export
import pdf_export
from config import BOT_TOKEN, WEBHOOK_URL, WEBHOOK_DOMAIN, ADMIN_SECRET, FLASK_PORT, CRON_SECRET, DEPLOY_SECRET

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ==================== ASYNC RUNTIME ====================
# python-telegram-bot (v20+) is fully async, Flask (WSGI) here is synchronous.
#
# Two approaches were tried and rejected before this one:
#   1. A background thread running a forever-loop: PythonAnywhere's free tier
#      never actually schedules such threads - confirmed via diagnostics, the
#      thread reported alive and its loop 'running', but submitted coroutines
#      never executed (always timed out).
#   2. asyncio.run() per request: works, but it CLOSES the loop when done,
#      which invalidates PTB's HTTP client, so initialize() had to run again
#      on every single message - roughly 0.5-1s of overhead per message.
#
# What we do instead: keep ONE event loop object alive for the life of the
# worker process and drive it with run_until_complete(), which (unlike
# asyncio.run) leaves the loop open afterwards. The loop only actually runs
# while we are inside run_until_complete, i.e. on the request thread - so no
# background thread is needed, and initialize() is paid once per worker.

_loop = asyncio.new_event_loop()
_loop_lock = threading.Lock()  # WSGI may hand us concurrent requests per process
_ptb_ready = False


def run_sync(coro, timeout=25):
    """Run one PTB coroutine on the long-lived loop, initializing on first use."""
    global _ptb_ready
    with _loop_lock:
        if not _ptb_ready:
            _loop.run_until_complete(telegram_app.initialize())
            _ptb_ready = True
            logger.info("✅ Telegram client initialized (persists for this worker)")
        try:
            return _loop.run_until_complete(asyncio.wait_for(coro, timeout))
        except (NetworkError, TimedOut):
            # The HTTP client may have gone stale (long idle, connection reset).
            # Force a fresh initialize() on the NEXT request rather than retrying
            # here - a retry could re-run handler side effects that already
            # happened (e.g. sending a reply twice). Telegram re-delivers the
            # update on its own after we return 500.
            _ptb_ready = False
            raise

# States for conversations
ADD_NAME, ADD_PHONE, ADD_SALARY_TYPE = range(3)
ADD_RATE_N, ADD_RATE_M, ADD_RATE_K, ADD_RATE_OVERTIME = range(3, 7)
ADD_MONTHLY_SALARY, ADD_OVERTIME_HOURLY, ADD_RATE_PER_MINUTE = range(7, 10)
EDIT_SALARY_TYPE = 10
EDIT_RATE_N, EDIT_RATE_M, EDIT_RATE_K, EDIT_RATE_OVERTIME = range(11, 15)
EDIT_MONTHLY_SALARY, EDIT_OVERTIME_HOURLY, EDIT_RATE_PER_MINUTE = range(15, 18)
ACTION_MENU, EDIT_ATT_DATE, EDIT_ATT_IN, EDIT_ATT_OUT = range(18, 22)
COR_REQ_DATE, COR_REQ_IN, COR_REQ_OUT, COR_REQ_CONFIRM = range(22, 26)

telegram_app = None

# ==================== AUTH ====================

async def check_admin(user_id):
    user = db.get_user(user_id)
    return user is not None and user['role'] == 'admin'


async def get_main_menu_markup(role, user_id=None):
    if role == 'admin':
        buttons = [
            [msg.BTN_ADMIN_TODAY, msg.BTN_ADMIN_MONTH],
            [msg.BTN_ADMIN_EMPLOYEES, msg.BTN_ADMIN_CORRECTIONS]
        ]
    else:
        is_checked_in = False
        if user_id:
            is_checked_in = db.is_user_checked_in(user_id)

        action_btn = msg.BTN_CHECK_OUT if is_checked_in else msg.BTN_CHECK_IN

        buttons = [
            [action_btn],
            [msg.BTN_TODAY_STAT, msg.BTN_MONTH_STAT],
            [msg.BTN_MY_STATS, msg.BTN_CORRECTION_REQUEST]
        ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=False)


async def show_main_menu(update: Update, user_row):
    role = user_row['role']
    user_id = user_row['id']
    menu_markup = await get_main_menu_markup(role, user_id)
    await update.message.reply_text(f"Menu ({role}):", reply_markup=menu_markup)


# ==================== START & AUTH ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_user = db.get_user(user.id)
    if db_user:
        await show_main_menu(update, db_user)
    else:
        button = KeyboardButton(msg.MSG_SEND_CONTACT, request_contact=True)
        reply_markup = ReplyKeyboardMarkup([[button]], resize_keyboard=True, one_time_keyboard=False)
        await update.message.reply_text(msg.MSG_WELCOME, reply_markup=reply_markup)


async def contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.contact
    if not contact:
        return
    phone = contact.phone_number.replace("+", "").strip()
    phone_short = phone[-9:]
    pending = db.get_pending_user(phone_short)
    if pending:
        admin_provided_name = pending['full_name']
        db.promote_pending_to_user(update.effective_user.id, phone, admin_provided_name, pending)
        await update.message.reply_text(msg.MSG_AUTH_SUCCESS.format(name=admin_provided_name))
        new_user = db.get_user(update.effective_user.id)
        await show_main_menu(update, new_user)
    else:
        await update.message.reply_text(msg.MSG_NOT_AUTHORIZED)


async def secret_admin_claim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return

    code = context.args[0]
    if code == ADMIN_SECRET:
        user = update.effective_user
        db.add_user(user.id, "AdminPhone", user.full_name, role='admin')
        await update.message.reply_text(msg.MSG_ADMIN_PROMOTED)
        await show_main_menu(update, {'role': 'admin', 'full_name': user.full_name, 'id': user.id})
    else:
        await update.message.reply_text(msg.MSG_WRONG_CODE)


# ==================== EMPLOYEE HANDLERS ====================

async def check_in_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    now = utils.get_now()
    result = db.check_in_user(user_id, now)
    user = db.get_user(user_id)
    menu_markup = await get_main_menu_markup(user['role'], user_id)

    if result['success']:
        cutoff = now.replace(hour=9, minute=15, second=0, microsecond=0)
        start_of_work = now.replace(hour=9, minute=0, second=0, microsecond=0)
        reply_txt = msg.MSG_CHECKED_IN.format(time=now.strftime("%H:%M"))

        if start_of_work <= now < now.replace(hour=11, minute=0):
            if now > cutoff:
                reply_txt = msg.MSG_CHECKED_IN_LATE.format(time=now.strftime("%H:%M"))

        await update.message.reply_text(reply_txt, reply_markup=menu_markup, parse_mode='HTML')
    else:
        await update.message.reply_text(result['message'], reply_markup=menu_markup)


async def check_out_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    now = utils.get_now()
    result = db.check_out_user(user_id, now)
    user = db.get_user(user_id)
    menu_markup = await get_main_menu_markup(user['role'], user_id)

    if result['success']:
        await update.message.reply_text(
            msg.MSG_CHECKED_OUT.format(
                time=now.strftime("%H:%M"),
                wage=f"{result['wage']:.2f}",
                details=result['details']
            ),
            reply_markup=menu_markup
        )
    else:
        await update.message.reply_text(result['message'], reply_markup=menu_markup)


async def employee_today_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    today_date = utils.get_now().date()
    row = db.get_daily_attendance_for_user(user_id, today_date)
    user = db.get_user(user_id)
    menu_markup = await get_main_menu_markup(user['role'], user_id)

    if row:
        check_in = row['check_in'].strftime('%H:%M') if row['check_in'] else "--:--"
        check_out = row['check_out'].strftime('%H:%M') if row['check_out'] else "--:--"
        wage = row['total_wage'] if row['total_wage'] else 0
        txt = (f"📅 Bugungi hisobot:\n\n"
               f"📥 Kelish: {check_in}\n"
               f"📤 Ketish: {check_out}\n"
               f"💰 Hisoblangan pul: {wage} $")
        await update.message.reply_text(txt, reply_markup=menu_markup)
    else:
        await update.message.reply_text("Bugun hali ma'lumot yo'q.", reply_markup=menu_markup)


async def employee_month_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    today = utils.get_now()
    start_date = today.replace(day=1)
    total = db.get_user_month_wage(user_id, start_date)
    details = db.get_user_month_details(user_id, start_date)
    report = f"📅 Bu oydagi hisobot:\n\n"
    for row in details:
        d = row['date'].strftime('%d.%m')
        ci = row['check_in'].strftime('%H:%M') if row['check_in'] else "--:--"
        co = row['check_out'].strftime('%H:%M') if row['check_out'] else "--:--"
        w = row['total_wage']
        report += f"🔹 {d}: {ci} - {co} | {w} $\n"
    report += f"\n💰 Jami: {total} $"
    user = db.get_user(user_id)
    menu_markup = await get_main_menu_markup(user['role'], user_id)
    await update.message.reply_text(report, reply_markup=menu_markup)


async def my_stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    now = utils.get_now()
    start_date = now.replace(day=1, hour=0, minute=0, second=0)
    stats = db.get_employee_summary(user_id, start_date)
    await update.message.reply_text(msg.MSG_MY_STATS.format(days=stats['days'], earned=f"{stats['earned']:.2f}"), parse_mode='HTML')


# ==================== ADMIN HANDLERS ====================

async def admin_today_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = utils.get_now().date()
    rows = db.get_today_attendance(today)

    if not rows:
        await update.message.reply_text("Bugun hich kim kelmadi.")
        return

    report = f"📅 Bugungi hisobot ({today}):\n\n"
    for row in rows:
        name = row['full_name']
        check_in = row['check_in'].strftime('%H:%M') if row['check_in'] else "--:--"
        check_out = row['check_out'].strftime('%H:%M') if row['check_out'] else "--:--"

        wage_str = ""
        if row['total_wage']:
            wage_str = f"| {row['total_wage']} $"
        elif row['check_in'] and not row['check_out']:
            now = utils.get_now()
            rates = {
                'salary_type': row['salary_type'] if row['salary_type'] else 'tariff',
                'rate_n': row['rate_n'] if row['rate_n'] else 0,
                'rate_m': row['rate_m'] if row['rate_m'] else 0,
                'rate_k': row['rate_k'] if row['rate_k'] else 0,
                'rate_overtime': row['rate_overtime'] if row['rate_overtime'] else 0,
                'monthly_salary': row['monthly_salary'] if row['monthly_salary'] else 0,
                'overtime_hourly_rate': row['overtime_hourly_rate'] if row['overtime_hourly_rate'] else 0,
                'rate_per_minute': row['rate_per_minute'] if row['rate_per_minute'] else 0,
            }
            live_wage, _, _ = utils.calculate_wage(row['check_in'], now, rates)
            wage_str = f"| ~{live_wage:.2f} $ (Ish jarayonida)"

        stype = row['salary_type'] if row['salary_type'] else 'tariff'
        stype_label = "Tarif" if stype == 'tariff' else ("Oylik" if stype == 'monthly' else "Minutlik")

        report += f"👤 {name} ({stype_label}): {check_in} - {check_out} {wage_str}\n"

    await update.message.reply_text(report)


async def admin_month_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = utils.get_now()
    buttons = []

    for i in range(6):
        y, m = today.year, today.month
        m = m - i
        while m <= 0:
            m += 12
            y -= 1

        label = f"{y}-{m:02d}"
        callback_data = f"adm_report_{y}-{m:02d}"

        if len(buttons) > 0 and len(buttons[-1]) < 3:
            buttons[-1].append(InlineKeyboardButton(label, callback_data=callback_data))
        else:
            buttons.append([InlineKeyboardButton(label, callback_data=callback_data)])

    await update.message.reply_text("Hisobot oyini tanlang:", reply_markup=InlineKeyboardMarkup(buttons))


async def admin_report_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    _, date_str = data.split('_report_')

    context.user_data['report_month'] = date_str

    buttons = [["Telegram", "Excel"], [msg.BTN_BACK]]
    await query.message.reply_text(f"Tanlangan oy: {date_str}. Formatni tanlang:", reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=False))


async def admin_employees_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = db.get_connection()
    c = conn.cursor()
    c.execute("SELECT id, full_name FROM users WHERE role='employee'")
    users = c.fetchall()
    conn.close()

    if not users:
        await update.message.reply_text("Xodimlar yo'q.")
    else:
        keyboard = []
        for u in users:
            keyboard.append([InlineKeyboardButton(u['full_name'], callback_data=f"edit_{u['id']}")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Xodimni tanlang (tahrirlash yoki o'chirish uchun):", reply_markup=reply_markup)

    buttons = [[msg.BTN_ADMIN_ADD_EMP], [msg.BTN_BACK]]
    await update.message.reply_text("Boshqaruv:", reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=False))


# ==================== MANAGE EMPLOYEE (edit rates / attendance / delete) ====================

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass

    try:
        data = query.data
        if data.startswith("del_"):
            user_id = int(data.split("_")[1])
            employee = db.get_user(user_id)
            db.delete_user(user_id)
            if employee:
                audit.log_employee_action(update.effective_user.id, user_id, 'user_deleted',
                                           f"O'chirildi: {employee['full_name']}")
            await query.edit_message_text(text="✅ Xodim o'chirildi.")
            return ConversationHandler.END

        elif data.startswith("edit_"):
            user_id = int(data.split("_")[1])
            context.user_data['edit_user_id'] = user_id
            u = db.get_user(user_id)
            name = u['full_name'] if u else "Xodim"

            buttons = [
                [InlineKeyboardButton(msg.BTN_ADMIN_EDIT_RATES_MENU, callback_data=f"act_rates_{user_id}")],
                [InlineKeyboardButton(msg.BTN_ADMIN_EDIT_ATT_MENU, callback_data=f"act_att_{user_id}")],
                [InlineKeyboardButton(msg.BTN_ADMIN_DELETE_EMP_MENU, callback_data=f"del_{user_id}")]
            ]
            await query.edit_message_text(
                text=msg.MSG_CHOOSE_ACTION.format(name=name),
                reply_markup=InlineKeyboardMarkup(buttons)
            )
            return ACTION_MENU

    except Exception as e:
        logger.error(f"Error in handle_callback_query: {e}")
    return ConversationHandler.END


async def employee_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("act_rates_"):
        user_id = int(data.split("_")[-1])
        context.user_data['edit_user_id'] = user_id
        buttons = [
            [msg.BTN_SALARY_TARIFF],
            [msg.BTN_SALARY_MONTHLY],
            [msg.BTN_SALARY_PER_MINUTE],
        ]
        await query.message.reply_text(
            msg.MSG_SELECT_SALARY_TYPE,
            reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=True),
            parse_mode='HTML'
        )
        return EDIT_SALARY_TYPE

    elif data.startswith("act_att_"):
        user_id = int(data.split("_")[-1])
        context.user_data['edit_user_id'] = user_id
        today = utils.get_now().date()
        buttons = []
        for i in range(7):
            d = today - timedelta(days=i)
            label = "Bugun" if i == 0 else ("Kecha" if i == 1 else d.strftime("%d.%m"))
            val = d.strftime("%Y-%m-%d")
            if len(buttons) > 0 and len(buttons[-1]) < 2:
                buttons[-1].append(InlineKeyboardButton(label, callback_data=f"edt_dt_{val}"))
            else:
                buttons.append([InlineKeyboardButton(label, callback_data=f"edt_dt_{val}")])
        await query.edit_message_text(text=msg.MSG_CHOOSE_DATE, reply_markup=InlineKeyboardMarkup(buttons))
        return EDIT_ATT_DATE

    return ACTION_MENU


async def edit_salary_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if "Tarif" in text:
        context.user_data['edit_salary_type'] = 'tariff'
        await update.message.reply_text(msg.MSG_INPUT_RATE_N, reply_markup=ReplyKeyboardRemove())
        return EDIT_RATE_N
    elif "Oylik" in text:
        context.user_data['edit_salary_type'] = 'monthly'
        await update.message.reply_text(msg.MSG_INPUT_MONTHLY_SALARY, reply_markup=ReplyKeyboardRemove(), parse_mode='HTML')
        return EDIT_MONTHLY_SALARY
    elif "Minutlik" in text:
        context.user_data['edit_salary_type'] = 'per_minute'
        await update.message.reply_text(msg.MSG_INPUT_RATE_PER_MINUTE, reply_markup=ReplyKeyboardRemove(), parse_mode='HTML')
        return EDIT_RATE_PER_MINUTE
    else:
        await update.message.reply_text("Iltimos, pastdagi tugmalardan birini tanlang.")
        return EDIT_SALARY_TYPE


async def edit_rate_n(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = utils.validate_float(update.message.text)
    if val is None:
        await update.message.reply_text("Raqam kiriting.")
        return EDIT_RATE_N
    context.user_data['edit_rate_n'] = val
    await update.message.reply_text(msg.MSG_INPUT_RATE_M)
    return EDIT_RATE_M


async def edit_rate_m(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = utils.validate_float(update.message.text)
    if val is None:
        await update.message.reply_text("Raqam kiriting.")
        return EDIT_RATE_M
    context.user_data['edit_rate_m'] = val
    await update.message.reply_text(msg.MSG_INPUT_RATE_K)
    return EDIT_RATE_K


async def edit_rate_k(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = utils.validate_float(update.message.text)
    if val is None:
        await update.message.reply_text("Raqam kiriting.")
        return EDIT_RATE_K
    context.user_data['edit_rate_k'] = val
    await update.message.reply_text(msg.MSG_INPUT_RATE_OVERTIME)
    return EDIT_RATE_OVERTIME


async def edit_rate_overtime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = utils.validate_float(update.message.text)
    if val is None:
        await update.message.reply_text("Raqam kiriting.")
        return EDIT_RATE_OVERTIME
    user_id = context.user_data['edit_user_id']
    db.update_rates(user_id, 'tariff',
                    rate_n=context.user_data['edit_rate_n'],
                    rate_m=context.user_data['edit_rate_m'],
                    rate_k=context.user_data['edit_rate_k'],
                    rate_overtime=val)
    audit.log_rates_updated(update.effective_user.id, user_id, 'tariff')
    await update.message.reply_text("✅ Stavkalar yangilandi!")
    user = db.get_user(update.effective_user.id)
    await show_main_menu(update, user)
    return ConversationHandler.END


async def edit_monthly_salary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = utils.validate_float(update.message.text)
    if val is None:
        await update.message.reply_text("Raqam kiriting. Masalan: 500")
        return EDIT_MONTHLY_SALARY
    context.user_data['edit_monthly_salary'] = val
    await update.message.reply_text(msg.MSG_INPUT_OVERTIME_HOURLY, parse_mode='HTML')
    return EDIT_OVERTIME_HOURLY


async def edit_overtime_hourly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = utils.validate_float(update.message.text)
    if val is None:
        await update.message.reply_text("Raqam kiriting. Masalan: 2.5")
        return EDIT_OVERTIME_HOURLY
    user_id = context.user_data['edit_user_id']
    db.update_rates(user_id, 'monthly',
                    monthly_salary=context.user_data['edit_monthly_salary'],
                    overtime_hourly_rate=val)
    audit.log_rates_updated(update.effective_user.id, user_id, 'monthly')
    await update.message.reply_text("✅ Oylik maosh yangilandi!")
    user = db.get_user(update.effective_user.id)
    await show_main_menu(update, user)
    return ConversationHandler.END


async def edit_rate_per_minute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = utils.validate_float(update.message.text)
    if val is None:
        await update.message.reply_text("Raqam kiriting. Masalan: 0.036")
        return EDIT_RATE_PER_MINUTE
    user_id = context.user_data['edit_user_id']
    db.update_rates(user_id, 'per_minute', rate_per_minute=val)
    audit.log_rates_updated(update.effective_user.id, user_id, 'per_minute')
    await update.message.reply_text("✅ Minutlik stavka yangilandi!")
    user = db.get_user(update.effective_user.id)
    await show_main_menu(update, user)
    return ConversationHandler.END


async def edit_att_date_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    date_str = query.data.split("edt_dt_")[-1]
    context.user_data['edit_att_date'] = date_str
    await query.message.reply_text(msg.MSG_INPUT_TIME_IN)
    return EDIT_ATT_IN


async def edit_att_in_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text
    if not utils.validate_time(val):
        await update.message.reply_text("Noto'g'ri format! Masalan: 09:00")
        return EDIT_ATT_IN
    context.user_data['edit_att_in'] = val
    await update.message.reply_text(msg.MSG_INPUT_TIME_OUT)
    return EDIT_ATT_OUT


async def edit_att_out_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    out_val = update.message.text
    if not utils.validate_time(out_val):
        await update.message.reply_text("Noto'g'ri format! Masalan: 18:00")
        return EDIT_ATT_OUT
    try:
        user_id = context.user_data['edit_user_id']
        date_str = context.user_data['edit_att_date']
        in_val = context.user_data['edit_att_in']
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        in_time = datetime.strptime(f"{date_str} {in_val}", "%Y-%m-%d %H:%M")
        out_time = datetime.strptime(f"{date_str} {out_val}", "%Y-%m-%d %H:%M")
        rates = db.get_db_rates(user_id)
        wage, _, _ = utils.calculate_wage(in_time, out_time, rates)
        db.update_attendance_manual(user_id, target_date, in_time, out_time, wage)
        audit.log_attendance_updated(update.effective_user.id, user_id, date_str, in_val, out_val)
        await update.message.reply_text(msg.MSG_EDIT_ATT_CONFIRM.format(date=date_str, ci=in_val, co=out_val, wage=f"{wage:.2f}"))
        user = db.get_user(update.effective_user.id)
        await show_main_menu(update, user)
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in edit_att_out_handler: {e}")
        await update.message.reply_text(f"Xatolik: {e}")
        return ConversationHandler.END


async def admin_correction_list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pending = db.get_pending_correction_requests()
    if not pending:
        await update.message.reply_text("✅ Hozircha yangi so'rovlar yo'q.")
        return

    await update.message.reply_text(f"🔔 {len(pending)} ta yangi so'rov bor:")
    for row in pending:
        req_id = row['id']
        name = row['full_name']
        date_str = row['request_date']
        in_time = row['actual_check_in']
        out_time = row['actual_check_out']

        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        att = db.get_daily_attendance_for_user(row['user_id'], d)
        current_status = "Kelmagan"
        if att and att['check_in']:
            ci = att['check_in'].strftime("%H:%M")
            co = att['check_out'].strftime("%H:%M") if att['check_out'] else "?"
            current_status = f"{ci} - {co}"

        msg_text = msg.MSG_COR_REQ_ADMIN.format(
            name=name, date=date_str, in_time=in_time, out_time=out_time, current=current_status
        )
        buttons = [
            [InlineKeyboardButton(msg.BTN_APPROVE, callback_data=f"approve_req_{req_id}")],
            [InlineKeyboardButton(msg.BTN_REJECT, callback_data=f"reject_req_{req_id}")]
        ]
        await update.message.reply_text(msg_text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode='HTML')


# ==================== QUICK COMMANDS ====================

async def cmd_in(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Быстрая команда /in - отметить приход"""
    await check_in_handler(update, context)


async def cmd_out(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Быстрая команда /out - отметить уход"""
    await check_out_handler(update, context)


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Быстрая команда /stats - мой счёт"""
    await my_stats_handler(update, context)


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Быстрая команда /today - отчёт за сегодня"""
    user = db.get_user(update.effective_user.id)
    if not user:
        return
    if user['role'] == 'admin':
        await admin_today_handler(update, context)
    else:
        await employee_today_handler(update, context)


async def cmd_month(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Быстрая команда /month - месячный отчёт"""
    user = db.get_user(update.effective_user.id)
    if not user:
        return
    if user['role'] == 'admin':
        await admin_month_handler(update, context)
    else:
        await employee_month_handler(update, context)


# ==================== ANALYTICS COMMANDS (ADMIN ONLY) ====================

async def cmd_analytics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /analytics - общая статистика по всем сотрудникам"""
    if not await check_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Bu buyruq faqat administrator uchun.")
        return
    try:
        text = analytics.format_all_stats_summary(days=30)
        await update.message.reply_text(text, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Error in cmd_analytics: {e}")
        await update.message.reply_text(f"❌ Xatolik: {e}")


async def cmd_employee_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /employee_stats <имя> - статистика по одному сотруднику"""
    if not await check_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Bu buyruq faqat administrator uchun.")
        return
    if not context.args:
        await update.message.reply_text("Foydalanish: /employee_stats <ism>\nMasalan: /employee_stats Ivan")
        return
    search_name = " ".join(context.args).lower()
    try:
        conn = db.get_connection()
        c = conn.cursor()
        c.execute("SELECT id, full_name FROM users WHERE role='employee' AND LOWER(full_name) LIKE ?",
                  (f"%{search_name}%",))
        matches = c.fetchall()
        conn.close()

        if not matches:
            await update.message.reply_text(f"❌ '{search_name}' nomli xodim topilmadi.")
            return
        if len(matches) > 1:
            names = "\n".join(f"• {m['full_name']}" for m in matches)
            await update.message.reply_text(f"⚠️ Bir nechta xodim topildi, aniqroq yozing:\n{names}")
            return

        employee_id = matches[0]['id']
        text = analytics.format_stats(analytics.get_employee_stats(employee_id, days=30))
        await update.message.reply_text(text, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Error in cmd_employee_stats: {e}")
        await update.message.reply_text(f"❌ Xatolik: {e}")


async def cmd_export_excel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /export_excel - выгрузить отчёт текущего месяца в Excel"""
    if not await check_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Bu buyruq faqat administrator uchun.")
        return
    try:
        start_date = utils.get_now().replace(day=1).date()
        bio = excel_export.create_monthly_report_excel(start_date)
        if not bio:
            await update.message.reply_text("❌ Bu oyda ma'lumot yo'q.")
            return
        await update.message.reply_document(document=bio, filename=f"hisobot_{start_date.strftime('%Y_%m')}.xlsx")
        audit.log_action(update.effective_user.id, 'report_generated', "Excel hisobot yuklab olindi")
    except Exception as e:
        logger.error(f"Error in cmd_export_excel: {e}")
        await update.message.reply_text(f"❌ Xatolik: {e}")


async def cmd_export_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /export_pdf - выгрузить отчёт текущего месяца в PDF"""
    if not await check_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Bu buyruq faqat administrator uchun.")
        return
    try:
        start_date = utils.get_now().replace(day=1).date()
        bio = pdf_export.create_monthly_pdf_report(start_date)
        if not bio:
            await update.message.reply_text("❌ Bu oyda ma'lumot yo'q yoki PDF kutubxonasi o'rnatilmagan.")
            return
        await update.message.reply_document(document=bio, filename=f"hisobot_{start_date.strftime('%Y_%m')}.pdf")
        audit.log_action(update.effective_user.id, 'report_generated', "PDF hisobot yuklab olindi")
    except Exception as e:
        logger.error(f"Error in cmd_export_pdf: {e}")
        await update.message.reply_text(f"❌ Xatolik: {e}")


# ==================== ADD EMPLOYEE ====================

async def start_add_employee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(msg.MSG_INPUT_NAME, reply_markup=ReplyKeyboardRemove())
    return ADD_NAME


async def add_emp_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_emp_name'] = update.message.text
    await update.message.reply_text(msg.MSG_INPUT_PHONE)
    return ADD_PHONE


async def add_emp_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text
    context.user_data['new_emp_phone'] = phone

    buttons = [
        [msg.BTN_SALARY_TARIFF],
        [msg.BTN_SALARY_MONTHLY],
        [msg.BTN_SALARY_PER_MINUTE],
    ]
    await update.message.reply_text(
        msg.MSG_SELECT_SALARY_TYPE,
        reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=True),
        parse_mode='HTML'
    )
    return ADD_SALARY_TYPE


async def add_emp_salary_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if "Tarif" in text:
        context.user_data['salary_type'] = 'tariff'
        await update.message.reply_text(msg.MSG_INPUT_RATE_N, reply_markup=ReplyKeyboardRemove())
        return ADD_RATE_N
    elif "Oylik" in text:
        context.user_data['salary_type'] = 'monthly'
        await update.message.reply_text(msg.MSG_INPUT_MONTHLY_SALARY, reply_markup=ReplyKeyboardRemove(), parse_mode='HTML')
        return ADD_MONTHLY_SALARY
    elif "Minutlik" in text:
        context.user_data['salary_type'] = 'per_minute'
        await update.message.reply_text(msg.MSG_INPUT_RATE_PER_MINUTE, reply_markup=ReplyKeyboardRemove(), parse_mode='HTML')
        return ADD_RATE_PER_MINUTE
    else:
        await update.message.reply_text("Iltimos, pastdagi tugmalardan birini tanlang.")
        return ADD_SALARY_TYPE


async def add_emp_rate_n(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = utils.validate_float(update.message.text)
        if val is None:
            await update.message.reply_text("Iltimos, to'g'ri raqam kiriting.")
            return ADD_RATE_N
        context.user_data['rate_n'] = val
        await update.message.reply_text(msg.MSG_INPUT_RATE_M)
        return ADD_RATE_M
    except ValueError:
        await update.message.reply_text("Iltimos, raqam kiriting.")
        return ADD_RATE_N


async def add_emp_rate_m(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = utils.validate_float(update.message.text)
        if val is None:
            await update.message.reply_text("Iltimos, to'g'ri raqam kiriting.")
            return ADD_RATE_M
        context.user_data['rate_m'] = val
        await update.message.reply_text(msg.MSG_INPUT_RATE_K)
        return ADD_RATE_K
    except ValueError:
        await update.message.reply_text("Iltimos, raqam kiriting.")
        return ADD_RATE_M


async def add_emp_rate_k(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = utils.validate_float(update.message.text)
        if val is None:
            await update.message.reply_text("Iltimos, to'g'ri raqam kiriting.")
            return ADD_RATE_K
        context.user_data['rate_k'] = val
        await update.message.reply_text(msg.MSG_INPUT_RATE_OVERTIME)
        return ADD_RATE_OVERTIME
    except ValueError:
        await update.message.reply_text("Iltimos, raqam kiriting.")
        return ADD_RATE_K


async def add_emp_rate_overtime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = utils.validate_float(update.message.text)
        if val is None:
            await update.message.reply_text("Iltimos, to'g'ri raqam kiriting.")
            return ADD_RATE_OVERTIME
        data = context.user_data
        db.add_pending_user(
            data['new_emp_phone'], data['new_emp_name'],
            salary_type='tariff',
            rate_n=data['rate_n'], rate_m=data['rate_m'],
            rate_k=data['rate_k'], rate_overtime=val
        )
        audit.log_user_added(update.effective_user.id, data['new_emp_name'], data['new_emp_phone'])
        rate_info = f"N:{data['rate_n']}$ | M:{data['rate_m']}$ | K:{data['rate_k']}$ | OT:{val}$"
        await update.message.reply_text(msg.MSG_EMP_ADDED.format(
            name=data['new_emp_name'], phone=data['new_emp_phone'],
            salary_type='Tarif', rate_info=rate_info
        ))
        user = db.get_user(update.effective_user.id)
        await show_main_menu(update, user)
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("Iltimos, raqam kiriting.")
        return ADD_RATE_OVERTIME


async def add_emp_monthly_salary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = utils.validate_float(update.message.text)
        if val is None:
            await update.message.reply_text("Iltimos, to'g'ri raqam kiriting.")
            return ADD_MONTHLY_SALARY
        context.user_data['monthly_salary'] = val
        await update.message.reply_text(msg.MSG_INPUT_OVERTIME_HOURLY, parse_mode='HTML')
        return ADD_OVERTIME_HOURLY
    except ValueError:
        await update.message.reply_text("Iltimos, raqam kiriting.")
        return ADD_MONTHLY_SALARY


async def add_emp_overtime_hourly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = utils.validate_float(update.message.text)
        if val is None:
            await update.message.reply_text("Iltimos, to'g'ri raqam kiriting.")
            return ADD_OVERTIME_HOURLY
        data = context.user_data
        db.add_pending_user(
            data['new_emp_phone'], data['new_emp_name'],
            salary_type='monthly',
            monthly_salary=data['monthly_salary'],
            overtime_hourly_rate=val
        )
        audit.log_user_added(update.effective_user.id, data['new_emp_name'], data['new_emp_phone'])
        rate_info = f"Oylik: {data['monthly_salary']}$ | OT soatlik: {val}$/soat"
        await update.message.reply_text(msg.MSG_EMP_ADDED.format(
            name=data['new_emp_name'], phone=data['new_emp_phone'],
            salary_type='Oylik maosh', rate_info=rate_info
        ))
        user = db.get_user(update.effective_user.id)
        await show_main_menu(update, user)
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("Iltimos, raqam kiriting.")
        return ADD_OVERTIME_HOURLY


async def add_emp_rate_per_minute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = utils.validate_float(update.message.text)
        if val is None:
            await update.message.reply_text("Iltimos, to'g'ri raqam kiriting.")
            return ADD_RATE_PER_MINUTE
        data = context.user_data
        db.add_pending_user(
            data['new_emp_phone'], data['new_emp_name'],
            salary_type='per_minute',
            rate_per_minute=val
        )
        audit.log_user_added(update.effective_user.id, data['new_emp_name'], data['new_emp_phone'])
        rate_info = f"Har daqiqa: {val}$/daq"
        await update.message.reply_text(msg.MSG_EMP_ADDED.format(
            name=data['new_emp_name'], phone=data['new_emp_phone'],
            salary_type='Minutlik stavka', rate_info=rate_info
        ))
        user = db.get_user(update.effective_user.id)
        await show_main_menu(update, user)
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("Iltimos, raqam kiriting.")
        return ADD_RATE_PER_MINUTE


async def cancel_add_employee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bekor qilindi.")
    user = db.get_user(update.effective_user.id)
    await show_main_menu(update, user)
    return ConversationHandler.END


# ==================== CORRECTION REQUEST ====================

async def correction_request_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = utils.get_now().date()
    buttons = []
    for i in range(4):
        d = today - timedelta(days=i)
        label = "Bugun" if i == 0 else ("Kecha" if i == 1 else d.strftime("%d.%m"))
        val = d.strftime("%Y-%m-%d")
        if len(buttons) > 0 and len(buttons[-1]) < 2:
            buttons[-1].append(InlineKeyboardButton(label, callback_data=f"creq_dt_{val}"))
        else:
            buttons.append([InlineKeyboardButton(label, callback_data=f"creq_dt_{val}")])
    await update.message.reply_text(msg.MSG_COR_REQ_DATE, reply_markup=InlineKeyboardMarkup(buttons))
    return COR_REQ_DATE


async def cor_req_date_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    date_str = query.data.split("creq_dt_")[-1]
    context.user_data['req_date'] = date_str
    await query.message.reply_text(msg.MSG_COR_REQ_TIME_IN)
    return COR_REQ_IN


async def correction_request_in(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text
    if not utils.validate_time(val):
        await update.message.reply_text("Noto'g'ri format! Masalan: 09:00")
        return COR_REQ_IN
    context.user_data['req_in'] = val
    await update.message.reply_text(msg.MSG_COR_REQ_TIME_OUT)
    return COR_REQ_OUT


async def correction_request_out(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text
    if not utils.validate_time(val):
        await update.message.reply_text("Noto'g'ri format! Masalan: 18:00")
        return COR_REQ_OUT
    context.user_data['req_out'] = val
    date = context.user_data['req_date']
    in_time = context.user_data['req_in']
    buttons = [[msg.BTN_BACK, "✅ Tasdiqlash"]]
    await update.message.reply_text(msg.MSG_COR_REQ_CONFIRM.format(date=date, in_time=in_time, out_time=val), reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=True))
    return COR_REQ_CONFIRM


async def correction_request_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == msg.BTN_BACK:
        await update.message.reply_text("Bekor qilindi.")
        user = db.get_user(update.effective_user.id)
        await show_main_menu(update, user)
        return ConversationHandler.END
    if "Tasdiqlash" in text:
        user_id = update.effective_user.id
        date_str = context.user_data['req_date']
        in_str = context.user_data['req_in']
        out_str = context.user_data['req_out']
        req_id = db.create_correction_request(user_id, date_str, in_str, out_str)
        await update.message.reply_text(msg.MSG_COR_REQ_SENT)
        conn = db.get_connection()
        c = conn.cursor()
        c.execute("SELECT id FROM users WHERE role='admin'")
        admins = c.fetchall()
        conn.close()
        user = db.get_user(user_id)
        name = user['full_name']
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        att = db.get_daily_attendance_for_user(user_id, d)
        current_status = "Kelmagan"
        if att and att['check_in']:
            ci = att['check_in'].strftime("%H:%M")
            co = att['check_out'].strftime("%H:%M") if att['check_out'] else "?"
            current_status = f"{ci} - {co}"
        msg_text = msg.MSG_COR_REQ_ADMIN.format(name=name, date=date_str, in_time=in_str, out_time=out_str, current=current_status)
        buttons = [[InlineKeyboardButton(msg.BTN_APPROVE, callback_data=f"approve_req_{req_id}")], [InlineKeyboardButton(msg.BTN_REJECT, callback_data=f"reject_req_{req_id}")]]
        for admin in admins:
            try:
                await telegram_app.bot.send_message(chat_id=admin['id'], text=msg_text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode='HTML')
            except Exception as e:
                logger.error(f"Failed to send correction request to admin: {e}")
        user = db.get_user(user_id)
        await show_main_menu(update, user)
        return ConversationHandler.END
    return COR_REQ_CONFIRM


async def approve_request_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    req_id = int(query.data.split("_")[-1])
    req = db.get_correction_request(req_id)
    if not req or req['status'] != 'PENDING':
        await query.edit_message_text("❌ Bu so'rov allaqachon ko'rib chiqilgan.")
        return
    db.update_correction_request_status(req_id, 'APPROVED')
    user_id = req['user_id']
    date_str = req['request_date']
    in_str = req['actual_check_in']
    out_str = req['actual_check_out']
    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    in_time = datetime.strptime(f"{date_str} {in_str}", "%Y-%m-%d %H:%M")
    out_time = datetime.strptime(f"{date_str} {out_str}", "%Y-%m-%d %H:%M")
    rates = db.get_db_rates(user_id)
    wage, _, _ = utils.calculate_wage(in_time, out_time, rates)
    db.update_attendance_manual(user_id, target_date, in_time, out_time, wage)
    audit.log_correction_approved(update.effective_user.id, user_id, date_str)
    await query.edit_message_text(f"{query.message.text}\n\n✅ Tasdiqlandi!")
    try:
        await telegram_app.bot.send_message(chat_id=user_id, text=msg.MSG_REQ_APPROVED.format(date=date_str))
    except Exception as e:
        logger.error(f"Failed to send approval message: {e}")


async def reject_request_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    req_id = int(query.data.split("_")[-1])
    req = db.get_correction_request(req_id)
    if not req or req['status'] != 'PENDING':
        await query.edit_message_text("❌ Bu so'rov allaqachon ko'rib chiqilgan.")
        return
    db.update_correction_request_status(req_id, 'REJECTED')
    audit.log_correction_rejected(update.effective_user.id, req['user_id'], req['request_date'])
    await query.edit_message_text(f"{query.message.text}\n\n❌ Rad etildi.")
    try:
        await telegram_app.bot.send_message(chat_id=req['user_id'], text=msg.MSG_REQ_REJECTED.format(date=req['request_date']))
    except Exception as e:
        logger.error(f"Failed to send rejection message: {e}")


# ==================== HANDLE TEXT ====================

async def unknown_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text
        user = db.get_user(update.effective_user.id)
        if not user:
            return

        if text == msg.BTN_ADMIN_TODAY and user['role'] == 'admin':
            await admin_today_handler(update, context)
        elif text == msg.BTN_ADMIN_MONTH and user['role'] == 'admin':
            await admin_month_handler(update, context)
        elif text == msg.BTN_ADMIN_EMPLOYEES and user['role'] == 'admin':
            await admin_employees_handler(update, context)
        elif text == msg.BTN_ADMIN_CORRECTIONS and user['role'] == 'admin':
            await admin_correction_list_handler(update, context)
        elif text in ["Telegram", "Excel"] and user['role'] == 'admin':
            await handle_report_format(update, context)
        elif text == msg.BTN_CHECK_IN:
            await check_in_handler(update, context)
        elif text == msg.BTN_CHECK_OUT or "Ketdim" in text:
            await check_out_handler(update, context)
        elif text == msg.BTN_TODAY_STAT:
            await employee_today_handler(update, context)
        elif text == msg.BTN_MONTH_STAT:
            await employee_month_handler(update, context)
        elif text == msg.BTN_MY_STATS:
            await my_stats_handler(update, context)
        elif text == msg.BTN_CORRECTION_REQUEST:
            await correction_request_start(update, context)
        elif text == msg.BTN_BACK:
            await show_main_menu(update, user)
        else:
            await update.message.reply_text("Tushunarsiz buyruq. Iltimos, menudan foydalaning yoki /start bosing.")
    except Exception as e:
        logger.error(f"Error in unknown_text: {e}")


async def handle_report_format(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    target_date = utils.get_now().replace(day=1)
    if 'report_month' in context.user_data:
        try:
            ym = context.user_data['report_month']
            dt = datetime.strptime(ym, "%Y-%m")
            target_date = dt.date()
        except:
            pass
    start_date = target_date

    if text == "Telegram":
        rows_detailed = db.get_month_attendance_details(start_date)
        if not rows_detailed:
            await update.message.reply_text("Bu oyda ma'lumot yo'q.")
            return
        report = "📅 Oylik hisobot:\n\n"
        overall_total = 0
        user_map = {}
        for r in rows_detailed:
            nm = r['full_name']
            if nm not in user_map:
                user_map[nm] = []
            user_map[nm].append(r)
        for name, records in user_map.items():
            stype = records[0]['salary_type'] if records[0]['salary_type'] else 'tariff'
            stype_label = "Tarif" if stype == 'tariff' else ("Oylik" if stype == 'monthly' else "Minutlik")
            report += f"👤 <b>{name}</b> ({stype_label}):\n"
            u_sum = 0
            for row in records:
                d = row['date'].strftime('%d.%m')
                w = row['total_wage']
                ci = row['check_in'].strftime('%H:%M') if row['check_in'] else "--"
                co = row['check_out'].strftime('%H:%M') if row['check_out'] else "--"
                report += f"  🔹 {d}: {ci}-{co} | {w:.2f}$\n"
                u_sum += w
            report += f"  💰 Jami: {u_sum:.2f} $\n\n"
            overall_total += u_sum
        report += f"🏁 Umumiy to'lov: {overall_total:.2f} $"
        await update.message.reply_text(report, parse_mode='HTML')
    elif text == "Excel":
        rows = db.get_month_attendance_details(start_date)
        if not rows:
            await update.message.reply_text("Bu oyda ma'lumot yo'q.")
            return
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Ism", "Sana", "Keldi", "Ketdi", "Turi", "Hisoblash tafsiloti", "Jami ($)"])
        header_font = Font(size=14, bold=True)
        row_font = Font(size=12)
        for cell in ws[1]:
            cell.font = header_font
        ws.column_dimensions['A'].width = 25
        ws.column_dimensions['B'].width = 12
        ws.column_dimensions['C'].width = 10
        ws.column_dimensions['D'].width = 10
        ws.column_dimensions['E'].width = 15
        ws.column_dimensions['F'].width = 40
        ws.column_dimensions['G'].width = 12
        for row in rows:
            rates = {
                'salary_type': row['salary_type'] if row['salary_type'] else 'tariff',
                'rate_n': row['rate_n'] if row['rate_n'] else 0,
                'rate_m': row['rate_m'] if row['rate_m'] else 0,
                'rate_k': row['rate_k'] if row['rate_k'] else 0,
                'rate_overtime': row['rate_overtime'] if row['rate_overtime'] else 0,
                'monthly_salary': row['monthly_salary'] if row['monthly_salary'] else 0,
                'overtime_hourly_rate': row['overtime_hourly_rate'] if row['overtime_hourly_rate'] else 0,
                'rate_per_minute': row['rate_per_minute'] if row['rate_per_minute'] else 0,
            }
            check_in = row['check_in']
            check_out = row['check_out']
            stype = rates['salary_type']
            stype_label = "Tarif" if stype == 'tariff' else ("Oylik" if stype == 'monthly' else "Minutlik")
            tafsilot = ""
            if check_in and check_out:
                _, _, breakdown = utils.calculate_wage(check_in, check_out, rates)
                total = row['total_wage']
                if stype == 'per_minute':
                    total_mins = (check_out - check_in).total_seconds() / 60.0
                    tafsilot = f"{total_mins:.0f} min x {rates['rate_per_minute']}"
                elif stype == 'monthly':
                    tafsilot = f"Reg: {breakdown.get('regular', 0):.2f}, OT: {breakdown.get('ot', 0):.2f}"
                else:
                    tafsilot = f"N:{breakdown['n']:.1f}, M:{breakdown['m']:.1f}, K:{breakdown['k']:.1f}, OT:{breakdown['ot']:.1f}"
            else:
                total = 0
                tafsilot = "Hali chiqmagan"
            ws.append([row['full_name'], row['date'], check_in.strftime("%H:%M") if check_in else "", check_out.strftime("%H:%M") if check_out else "", stype_label, tafsilot, total])
            for cell in ws[ws.max_row]:
                cell.font = row_font
        bio = BytesIO()
        wb.save(bio)
        bio.seek(0)
        await update.message.reply_document(document=bio, filename=f"hisobot_{start_date.strftime('%Y_%m')}.xlsx")


# ==================== FLASK WEBHOOK ====================

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle webhook updates from Telegram."""
    try:
        data = request.get_json()
        update = Update.de_json(data, telegram_app.bot)
        run_sync(telegram_app.process_update(update))
        return 'OK', 200
    except Exception as e:
        logger.error(f"Webhook error: {type(e).__name__}: {e}", exc_info=True)
        return 'ERROR', 500


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok', 'bot': 'running'}), 200


# ==================== SELF-DEPLOY (git pull + reload) ====================
# Lets updates be deployed by simply hitting this URL (e.g. via curl) after
# pushing new code to GitHub, instead of manually running commands in a
# PythonAnywhere Bash console every time.

@app.route('/deploy/<secret>', methods=['GET', 'POST'])
def deploy(secret):
    if secret != DEPLOY_SECRET:
        return 'Forbidden', 403
    try:
        repo_dir = os.path.dirname(os.path.abspath(__file__))
        result = subprocess.run(
            ['git', 'pull'],
            cwd=repo_dir,
            capture_output=True, text=True, timeout=30
        )
        git_output = (result.stdout + result.stderr).strip()

        wsgi_file = f"/var/www/{WEBHOOK_DOMAIN.replace('.', '_')}_wsgi.py"
        try:
            os.utime(wsgi_file, None)  # touching this file's mtime triggers a reload on PythonAnywhere
            reload_status = "reloaded"
        except Exception as e:
            reload_status = f"touch failed: {e}"

        logger.info(f"🚀 Deploy: git_output={git_output[:300]!r} reload={reload_status}")
        return jsonify({'status': 'ok', 'git_output': git_output, 'reload': reload_status}), 200
    except Exception as e:
        logger.error(f"Deploy error: {type(e).__name__}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ==================== SCHEDULED REMINDERS (via PythonAnywhere Tasks) ====================
# PythonAnywhere's free-tier Tasks/consoles go through a restricted internet
# proxy that does NOT allow reaching api.telegram.org directly (confirmed via
# testing: httpx.ProxyError 503). The web app itself, however, has full
# internet access. So instead of a Task calling Telegram directly, a Task
# hits THIS endpoint on our own web app (an allowed *.pythonanywhere.com
# request), and the web app - which can already talk to Telegram just fine,
# as proven by the working /webhook route - sends the actual messages.

MORNING_REMINDER_MSG = "☀️ Xayrli tong! Ishga kelganda 'Keldim' tugmasini bosishni unutmang."
EVENING_REMINDER_MSG = "🌙 Ish kuni tugadimi? Ishdan ketgan bo'lsangiz, 'Ketdim' tugmasini bosishni unutmang!"


def _get_all_employees():
    conn = db.get_connection()
    c = conn.cursor()
    c.execute("SELECT id, full_name FROM users WHERE role='employee'")
    employees = c.fetchall()
    conn.close()
    return employees


async def _send_reminders_job():
    bot = telegram_app.bot
    now = utils.get_now()
    employees = _get_all_employees()
    sent = 0

    if now.hour < 12:
        today = now.date()
        for emp in employees:
            if db.get_daily_attendance_for_user(emp['id'], today) is not None:
                continue  # already checked in today
            try:
                await bot.send_message(chat_id=emp['id'], text=MORNING_REMINDER_MSG)
                sent += 1
            except Exception as e:
                logger.warning(f"Morning reminder failed for {emp['full_name']} ({emp['id']}): {e}")
        kind = "morning"
    else:
        for emp in employees:
            if not db.is_user_checked_in(emp['id']):
                continue  # not currently checked in, nothing to remind about
            try:
                await bot.send_message(chat_id=emp['id'], text=EVENING_REMINDER_MSG)
                sent += 1
            except Exception as e:
                logger.warning(f"Evening reminder failed for {emp['full_name']} ({emp['id']}): {e}")
        kind = "evening"

    logger.info(f"✅ {kind.capitalize()} reminders sent to {sent}/{len(employees)} employees")
    return kind, sent, len(employees)


@app.route('/cron/reminders/<secret>', methods=['GET', 'POST'])
def cron_reminders(secret):
    """Triggered by a PythonAnywhere scheduled Task (via curl/wget) at the
    desired times. The secret in the URL path prevents random internet
    traffic from spamming all employees with reminders."""
    if secret != CRON_SECRET:
        return 'Forbidden', 403
    try:
        kind, sent, total = run_sync(_send_reminders_job(), timeout=60)
        return jsonify({'status': 'ok', 'kind': kind, 'sent': sent, 'total': total}), 200
    except Exception as e:
        logger.error(f"Cron reminders error: {type(e).__name__}: {e}", exc_info=True)
        return 'ERROR', 500


def create_application():
    """Create and configure Telegram application"""
    global telegram_app

    try:
        app_config = Application.builder().token(BOT_TOKEN).build()

        # Start command
        app_config.add_handler(CommandHandler("start", start))
        app_config.add_handler(CommandHandler("admin", secret_admin_claim))

        # Quick commands
        app_config.add_handler(CommandHandler("in", cmd_in))
        app_config.add_handler(CommandHandler("out", cmd_out))
        app_config.add_handler(CommandHandler("stats", cmd_stats))
        app_config.add_handler(CommandHandler("today", cmd_today))
        app_config.add_handler(CommandHandler("month", cmd_month))

        # Analytics commands (admin only)
        app_config.add_handler(CommandHandler("analytics", cmd_analytics))
        app_config.add_handler(CommandHandler("employee_stats", cmd_employee_stats))
        app_config.add_handler(CommandHandler("export_excel", cmd_export_excel))
        app_config.add_handler(CommandHandler("export_pdf", cmd_export_pdf))

        # Contact handler
        app_config.add_handler(MessageHandler(filters.CONTACT, contact_handler))

        # Add Employee Conversation
        add_emp_handler = ConversationHandler(
            entry_points=[MessageHandler(filters.Regex(f"^{msg.BTN_ADMIN_ADD_EMP}$"), start_add_employee)],
            states={
                ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_emp_name)],
                ADD_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_emp_phone)],
                ADD_SALARY_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_emp_salary_type)],
                ADD_RATE_N: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_emp_rate_n)],
                ADD_RATE_M: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_emp_rate_m)],
                ADD_RATE_K: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_emp_rate_k)],
                ADD_RATE_OVERTIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_emp_rate_overtime)],
                ADD_MONTHLY_SALARY: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_emp_monthly_salary)],
                ADD_OVERTIME_HOURLY: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_emp_overtime_hourly)],
                ADD_RATE_PER_MINUTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_emp_rate_per_minute)],
            },
            fallbacks=[],
            name="add_emp_conv",
            persistent=False
        )
        app_config.add_handler(add_emp_handler)

        # Correction Request Conversation
        correction_conv = ConversationHandler(
            entry_points=[MessageHandler(filters.Regex(f"^{msg.BTN_CORRECTION_REQUEST}$"), correction_request_start)],
            states={
                COR_REQ_DATE: [CallbackQueryHandler(cor_req_date_callback, pattern="^creq_dt_")],
                COR_REQ_IN: [MessageHandler(filters.TEXT & ~filters.COMMAND, correction_request_in)],
                COR_REQ_OUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, correction_request_out)],
                COR_REQ_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, correction_request_confirm)]
            },
            fallbacks=[],
            name="correction_conv",
            persistent=False
        )
        app_config.add_handler(correction_conv)

        # Manage Employee Conversation (edit rates / attendance / delete)
        manage_emp_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(handle_callback_query, pattern="^edit_"),
                CallbackQueryHandler(handle_callback_query, pattern="^del_"),
            ],
            states={
                ACTION_MENU: [
                    CallbackQueryHandler(employee_action_callback, pattern="^act_"),
                    CallbackQueryHandler(handle_callback_query, pattern="^del_"),
                ],
                EDIT_SALARY_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_salary_type)],
                EDIT_RATE_N: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_rate_n)],
                EDIT_RATE_M: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_rate_m)],
                EDIT_RATE_K: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_rate_k)],
                EDIT_RATE_OVERTIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_rate_overtime)],
                EDIT_MONTHLY_SALARY: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_monthly_salary)],
                EDIT_OVERTIME_HOURLY: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_overtime_hourly)],
                EDIT_RATE_PER_MINUTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_rate_per_minute)],
                EDIT_ATT_DATE: [CallbackQueryHandler(edit_att_date_callback, pattern="^edt_dt_")],
                EDIT_ATT_IN: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_att_in_handler)],
                EDIT_ATT_OUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_att_out_handler)],
            },
            fallbacks=[MessageHandler(filters.Regex(f"^{msg.BTN_BACK}$"), cancel_add_employee)],
            name="manage_emp_conv",
            persistent=False
        )
        app_config.add_handler(manage_emp_handler)

        # Callback handlers
        app_config.add_handler(CallbackQueryHandler(admin_report_callback, pattern="^adm_report_"))
        app_config.add_handler(CallbackQueryHandler(approve_request_callback, pattern="^approve_req_"))
        app_config.add_handler(CallbackQueryHandler(reject_request_callback, pattern="^reject_req_"))

        # Text handler (must be last)
        app_config.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_text))

        telegram_app = app_config
        logger.info("✅ Telegram app created successfully")

        # Note: initialize()/shutdown() are NOT called here. They run once
        # per webhook request instead (see _handle_update_standalone below),
        # since this app has no persistent event loop available to it.
        return app_config
    except Exception as e:
        logger.error(f"❌ Error creating application: {e}")
        raise


# Auto-initialize on import so this works under any WSGI server
# (PythonAnywhere imports `app` directly without running wsgi.py's setup code)
try:
    db.init_db()
    if telegram_app is None:
        create_application()
except Exception as e:
    logger.error(f"❌ Failed to auto-initialize on import: {e}")


if __name__ == '__main__':
    try:
        logger.info(f"🚀 Starting Flask server on port {FLASK_PORT}")
        logger.info(f"📡 Webhook URL: {WEBHOOK_URL}")
        app.run(host='0.0.0.0', port=FLASK_PORT, debug=False)
    except Exception as e:
        logger.error(f"💥 Critical error: {e}")
        raise
