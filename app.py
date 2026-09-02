import logging
import asyncio
import os
import re
import subprocess
import threading
from datetime import datetime, time, timedelta
from io import BytesIO

from flask import Flask, request, jsonify
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.error import BadRequest, NetworkError, TimedOut
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
import settings
import ui
from config import BOT_TOKEN, WEBHOOK_URL, WEBHOOK_DOMAIN, ADMIN_SECRET, FLASK_PORT, CRON_SECRET, DEPLOY_SECRET, BOT_VERSION

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


_stats = {'updates': 0, 'inits': 0, 'last_ms': None, 'errors': 0}


def _initialize_bot(retries=3):
    """(Re)build PTB's client on our loop.

    PythonAnywhere's outbound proxy occasionally answers 503, which used to
    leave the Application half-built: our own flag said 'ready' while PTB's
    internal state disagreed, and every later update then died with
    'ExtBot is not properly initialized'. So we always tear down first, and
    retry a transient proxy failure - initialize() has no user-visible side
    effects, so retrying it is safe (unlike retrying an update)."""
    global _ptb_ready
    _ptb_ready = False
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            try:
                _loop.run_until_complete(telegram_app.shutdown())
            except Exception:
                pass  # nothing to tear down on the very first run
            _loop.run_until_complete(telegram_app.initialize())
            _ptb_ready = True
            _stats['inits'] += 1
            logger.info("✅ Telegram client initialized (persists for this worker)")
            return
        except (NetworkError, TimedOut) as e:
            last_err = e
            logger.warning(f"initialize() attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                _loop.run_until_complete(asyncio.sleep(0.6 * attempt))
    raise last_err


def run_sync(coro, timeout=25):
    """Run one PTB coroutine on the long-lived loop, initializing on first use."""
    global _ptb_ready
    with _loop_lock:
        if not _ptb_ready:
            _initialize_bot()
        started = datetime.now()
        try:
            result = _loop.run_until_complete(asyncio.wait_for(coro, timeout))
            _stats['updates'] += 1
            _stats['last_ms'] = int((datetime.now() - started).total_seconds() * 1000)
            return result
        except RuntimeError as e:
            if "not properly initialized" not in str(e):
                raise
            _stats['errors'] += 1
            _ptb_ready = False  # rebuild on the next update
            raise
        except (NetworkError, TimedOut):
            _stats['errors'] += 1
            # Client may have gone stale (long idle, connection reset). Rebuild
            # on the NEXT update rather than retrying this one - a retry could
            # repeat handler side effects that already happened (e.g. sending a
            # reply twice). Telegram re-delivers after we answer 500.
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
SET_TIME_VALUE = 26

telegram_app = None

# ==================== AUTH ====================

async def check_admin(user_id):
    user = db.get_user(user_id)
    return user is not None and user['role'] == 'admin'


async def get_main_menu_markup(role, user_id=None):
    if role == 'admin':
        return ui.admin_keyboard()
    return ui.employee_keyboard(user_id)


async def show_main_menu(update: Update, user_row):
    """Everyone's home screen: employees get their status card, admins get the
    live dashboard of who is working right now."""
    if user_row['role'] != 'admin':
        await send_employee_home(update, user_row)
        return
    await update.message.reply_text(
        ui.admin_dashboard_card(), reply_markup=ui.admin_keyboard(), parse_mode='HTML'
    )


# ==================== START & AUTH ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_user = db.get_user(user.id)
    if not db_user:
        button = KeyboardButton(msg.MSG_SEND_CONTACT, request_contact=True)
        reply_markup = ReplyKeyboardMarkup([[button]], resize_keyboard=True, one_time_keyboard=False)
        await update.message.reply_text(msg.MSG_WELCOME, reply_markup=reply_markup)
        return

    if db_user['role'] == 'admin':
        await show_main_menu(update, db_user)
    else:
        await send_employee_home(update, db_user)


# ==================== EMPLOYEE UI ====================

async def send_employee_home(update: Update, db_user, note=None):
    """Status card + the bottom keyboard, whose primary button reflects
    whether they're currently checked in."""
    text = ui.employee_status_card(db_user['id'], db_user['full_name'], note=note)
    await update.message.reply_text(
        text,
        reply_markup=ui.employee_keyboard(db_user['id']),
        parse_mode='HTML',
    )


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
    user = db.get_user(user_id)
    now = utils.get_now()
    result = db.check_in_user(user_id, now)

    if result['success']:
        late_after = settings.get_time('late_after')
        cutoff = now.replace(hour=late_after.hour, minute=late_after.minute, second=0, microsecond=0)
        if now > cutoff:
            note = f"⚠️ <i>Kechikdingiz ({settings.get_time_str('late_after')} dan keyin).</i>"
        else:
            note = "<i>Hayrli ish!</i>"
    else:
        note = f"⚠️ <i>{result['message']}</i>"

    await send_employee_home(update, user, note=note)


async def check_out_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = db.get_user(user_id)
    now = utils.get_now()
    result = db.check_out_user(user_id, now)

    if result['success']:
        note = f"<i>{result['details']}</i>\n\n<i>Ish kuningiz uchun rahmat!</i>"
    else:
        note = f"⚠️ <i>{result['message']}</i>"

    await send_employee_home(update, user, note=note)


async def employee_status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Refresh the status card (live worked-time / earnings while checked in)."""
    user = db.get_user(update.effective_user.id)
    if user:
        await send_employee_home(update, user)


async def employee_today_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Today's status for an employee - same card as the 🏠 Holat button."""
    await employee_status_handler(update, context)


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
    await update.message.reply_text(
        ui.employee_stats_card(user_id),
        reply_markup=ui.employee_keyboard(user_id),
        parse_mode='HTML',
    )


# ==================== ADMIN HANDLERS ====================

async def admin_today_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Live dashboard: who's working, who finished, who never showed up."""
    await update.message.reply_text(
        ui.admin_dashboard_card(), reply_markup=ui.admin_keyboard(), parse_mode='HTML'
    )


async def admin_month_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Month picker. Picking one shows the report straight away."""
    today = utils.get_now()
    buttons = []

    for i in range(6):
        y, m = today.year, today.month
        m -= i
        while m <= 0:
            m += 12
            y -= 1
        label = ui.fmt_month(datetime(y, m, 1))
        cb = f"rep:{y}-{m:02d}"
        if buttons and len(buttons[-1]) < 2:
            buttons[-1].append(InlineKeyboardButton(label, callback_data=cb))
        else:
            buttons.append([InlineKeyboardButton(label, callback_data=cb)])

    await update.message.reply_text(
        "📊 <b>Hisobot oyini tanlang:</b>",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode='HTML',
    )


def _month_start(ym):
    """'2026-09' -> date(2026, 9, 1)"""
    return datetime.strptime(ym, "%Y-%m").date()


async def admin_report_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the monthly report for the chosen month, with export options."""
    query = update.callback_query
    await query.answer()

    # Accepts both the new 'rep:YYYY-MM' and the legacy 'adm_report_YYYY-MM'
    # so month buttons sent before this redesign still work.
    data = query.data
    ym = data.split('_report_')[-1] if '_report_' in data else data.split(':', 1)[1]
    context.user_data['report_month'] = ym

    buttons = [[
        InlineKeyboardButton("📥 Excel", callback_data=f"repx:xls:{ym}"),
        InlineKeyboardButton("📄 PDF", callback_data=f"repx:pdf:{ym}"),
    ]]
    try:
        await query.edit_message_text(
            ui.admin_month_report_card(_month_start(ym)),
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode='HTML',
        )
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            raise


async def report_export_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send the chosen month's report as an Excel or PDF file."""
    query = update.callback_query
    await query.answer("Tayyorlanmoqda…")
    _, fmt, ym = query.data.split(':', 2)
    start_date = _month_start(ym)

    if fmt == 'xls':
        bio = excel_export.create_monthly_report_excel(start_date)
        filename, label = f"hisobot_{ym.replace('-', '_')}.xlsx", "Excel"
    else:
        bio = pdf_export.create_monthly_pdf_report(start_date)
        filename, label = f"hisobot_{ym.replace('-', '_')}.pdf", "PDF"

    if not bio:
        await query.message.reply_text(f"❌ {label} hisobotini yaratib bo'lmadi (ma'lumot yo'q).")
        return

    await query.message.reply_document(document=bio, filename=filename)
    audit.log_action(query.from_user.id, 'report_generated', f"{label} hisobot: {ym}")


async def admin_employees_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, keyboard = ui.admin_employee_list()
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode='HTML')

    buttons = [[msg.BTN_ADMIN_ADD_EMP], [msg.BTN_BACK]]
    await update.message.reply_text(
        "➕ <i>Yangi xodim qo'shish uchun pastdagi tugmani bosing.</i>",
        reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=False),
        parse_mode='HTML',
    )


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

            buttons = [
                [
                    InlineKeyboardButton("💵 Stavka", callback_data=f"act_rates_{user_id}"),
                    InlineKeyboardButton("📝 Vaqt", callback_data=f"act_att_{user_id}"),
                ],
                [InlineKeyboardButton("❌ O'chirish", callback_data=f"del_{user_id}")],
            ]
            await query.edit_message_text(
                text=ui.admin_employee_card(user_id),
                reply_markup=InlineKeyboardMarkup(buttons),
                parse_mode='HTML',
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

# ==================== SETTINGS ====================

async def admin_settings_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update.effective_user.id):
        return
    text, keyboard = ui.settings_card()
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode='HTML')


async def settings_pick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin tapped a setting - ask for the new value."""
    query = update.callback_query
    await query.answer()
    if not await check_admin(query.from_user.id):
        return ConversationHandler.END

    key = query.data.split(':', 1)[1]
    if key not in settings.TIME_SETTINGS:
        return ConversationHandler.END

    context.user_data['setting_key'] = key
    _, label, desc = settings.TIME_SETTINGS[key]
    await query.message.reply_text(
        f"{label}\n<i>{desc}</i>\n\n"
        f"Hozirgi qiymat: <b>{settings.get_time_str(key)}</b>\n\n"
        f"Yangi vaqtni <b>SS:DD</b> ko'rinishida yuboring (masalan <code>09:30</code>).\n"
        f"Bekor qilish uchun /cancel",
        parse_mode='HTML',
    )
    return SET_TIME_VALUE


async def settings_set_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = context.user_data.get('setting_key')
    if not key:
        return ConversationHandler.END

    if not settings.set_time(key, update.message.text):
        await update.message.reply_text(
            "❌ Noto'g'ri format. Masalan: <code>09:30</code>\nQayta urinib ko'ring yoki /cancel",
            parse_mode='HTML',
        )
        return SET_TIME_VALUE

    _, label, _ = settings.TIME_SETTINGS[key]
    new_value = settings.get_time_str(key)
    audit.log_action(update.effective_user.id, 'settings_changed', f"{label} -> {new_value}")
    context.user_data.pop('setting_key', None)

    await update.message.reply_text(
        f"✅ <b>{label}</b> yangilandi: <b>{new_value}</b>",
        reply_markup=ui.admin_keyboard(),
        parse_mode='HTML',
    )
    text, keyboard = ui.settings_card()
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode='HTML')
    return ConversationHandler.END


async def settings_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop('setting_key', None)
    await update.message.reply_text("Bekor qilindi.", reply_markup=ui.admin_keyboard())
    return ConversationHandler.END


async def cmd_preview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin-only: render an employee's own card as they currently see it.
    Doubles as a live per-employee status check."""
    if not await check_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Bu buyruq faqat administrator uchun.")
        return
    employees = _get_all_employees()
    if not employees:
        await update.message.reply_text("Xodimlar yo'q.")
        return
    keyboard = [
        [InlineKeyboardButton(e['full_name'], callback_data=f"prev:{e['id']}")]
        for e in employees
    ]
    await update.message.reply_text(
        "👁 <b>Xodim ekranini ko'rish</b>\n<i>Xodim o'z telefonida nimani ko'rayotganini tanlang:</i>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML',
    )


async def preview_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await check_admin(query.from_user.id):
        return
    emp_id = int(query.data.split(":")[1])
    emp = db.get_user(emp_id)
    if not emp:
        await query.edit_message_text("❌ Xodim topilmadi.")
        return
    card = ui.employee_status_card(emp_id, emp['full_name'])
    rates = db.get_db_rates(emp_id)
    try:
        await query.edit_message_text(
            f"👁 <i>Xodim ekrani:</i>\n\n{card}\n\n💵 <i>Stavka: {ui.fmt_rate(rates)}</i>",
            parse_mode='HTML',
        )
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            raise


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

        is_admin = user['role'] == 'admin'
        if is_admin and text in (ui.BTN_ADMIN_TODAY, msg.BTN_ADMIN_TODAY):
            await admin_today_handler(update, context)
        elif is_admin and text in (ui.BTN_ADMIN_REPORT, msg.BTN_ADMIN_MONTH):
            await admin_month_handler(update, context)
        elif is_admin and text in (ui.BTN_ADMIN_EMPLOYEES, msg.BTN_ADMIN_EMPLOYEES):
            await admin_employees_handler(update, context)
        elif is_admin and text in (ui.BTN_ADMIN_CORRECTIONS, msg.BTN_ADMIN_CORRECTIONS):
            await admin_correction_list_handler(update, context)
        elif is_admin and text == ui.BTN_ADMIN_SETTINGS:
            await admin_settings_handler(update, context)
        elif is_admin and text in ("Telegram", "Excel"):
            await handle_report_format(update, context)
        # New employee keyboard. The old labels are still accepted below so
        # anyone whose Telegram is still showing the previous keyboard (it
        # persists client-side until they interact) doesn't hit a dead button.
        elif text in (ui.BTN_CHECK_IN, msg.BTN_CHECK_IN):
            await check_in_handler(update, context)
        elif text in (ui.BTN_CHECK_OUT, msg.BTN_CHECK_OUT) or "Ketdim" in text:
            await check_out_handler(update, context)
        elif text in (ui.BTN_STATUS, msg.BTN_TODAY_STAT):
            await employee_status_handler(update, context)
        elif text in (ui.BTN_MY_STATS, msg.BTN_MY_STATS, msg.BTN_MONTH_STAT):
            await my_stats_handler(update, context)
        elif text in (ui.BTN_CORRECTION, msg.BTN_CORRECTION_REQUEST):
            await correction_request_start(update, context)
        elif text == msg.BTN_BACK:
            await show_main_menu(update, user)
        else:
            await update.message.reply_text("Tushunarsiz buyruq. Iltimos, menudan foydalaning yoki /start bosing.")
    except Exception as e:
        # Never leave the user staring at silence - a swallowed exception here
        # looks exactly like "the bot is broken" from their side.
        logger.error(f"Error in unknown_text: {type(e).__name__}: {e}", exc_info=True)
        try:
            await update.message.reply_text("⚠️ Xatolik yuz berdi. Qayta urinib ko'ring yoki /start bosing.")
        except Exception:
            pass


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

def _maybe_send_evening_reminder():
    """Fallback for the evening reminder.

    The free tier allows only ONE scheduled task, which is used for the
    morning one. So we also check, on ordinary bot traffic, whether the
    evening reminder is due and hasn't gone out yet today. Best-effort by
    nature (it needs *someone* to message the bot after work ends), which is
    why the flag guard is shared with the scheduled path - whichever fires
    first wins, and the other becomes a no-op."""
    try:
        now = utils.get_now()
        end = settings.get_time('work_end')
        past_end = (now.hour, now.minute) >= (end.hour, end.minute)
        if not past_end or not _reminder_due('evening', now.date()):
            return
        run_sync(_send_reminders_job('evening'), timeout=60)
    except Exception as e:
        logger.warning(f"Evening reminder fallback skipped: {type(e).__name__}: {e}")


@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle webhook updates from Telegram."""
    try:
        data = request.get_json()
        update = Update.de_json(data, telegram_app.bot)
        run_sync(telegram_app.process_update(update))
    except Exception as e:
        logger.error(f"Webhook error: {type(e).__name__}: {e}", exc_info=True)
        return 'ERROR', 500

    # After the user has had their reply, not before.
    _maybe_send_evening_reminder()
    return 'OK', 200


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok', 'bot': 'running'}), 200


@app.route('/logs/<secret>', methods=['GET'])
def logs(secret):
    """Tail the server error log. Saves a round-trip through the user for
    every diagnosis - they can't be expected to run console commands."""
    if secret != DEPLOY_SECRET:
        return 'Forbidden', 403
    lines = int(request.args.get('n', 60))
    path = f"/var/log/{WEBHOOK_DOMAIN.replace('.', '_').replace('_com', '.com')}.error.log"
    # PythonAnywhere names it <domain>.error.log with dots intact
    path = f"/var/log/{WEBHOOK_DOMAIN}.error.log"
    try:
        with open(path, 'r', errors='replace') as fh:
            tail = fh.readlines()[-lines:]
        return ''.join(tail), 200, {'Content-Type': 'text/plain; charset=utf-8'}
    except Exception as e:
        return f"Could not read {path}: {e}", 500, {'Content-Type': 'text/plain'}


@app.route('/status/<secret>', methods=['GET'])
def status(secret):
    """Runtime diagnostics - lets deploys be verified without reading server
    logs by hand. 'inits' staying at 1 while 'updates' climbs is the signal
    that the long-lived event loop is doing its job (see run_sync)."""
    if secret != DEPLOY_SECRET:
        return 'Forbidden', 403
    conn = db.get_connection()
    c = conn.cursor()
    c.execute("SELECT role, COUNT(*) AS n FROM users GROUP BY role")
    roles = {row['role']: row['n'] for row in c.fetchall()}
    conn.close()
    return jsonify({
        'status': 'ok',
        'version': BOT_VERSION,
        'server_time_tashkent': utils.get_now().strftime('%Y-%m-%d %H:%M:%S'),
        'telegram_client_ready': _ptb_ready,
        'runtime': _stats,
        'users': roles,
    }), 200


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


def _reminder_flag_key(kind):
    return f"reminder_{kind}_sent_on"


def _reminder_due(kind, today):
    """True if this reminder hasn't gone out yet today. Guards against a
    double-send when both the scheduled task and the lazy fallback fire."""
    return settings.get_flag(_reminder_flag_key(kind)) != today.isoformat()


async def _send_reminders_job(kind=None):
    """kind=None auto-selects by time of day, so a single scheduled task can
    serve either slot depending on when it runs."""
    bot = telegram_app.bot
    now = utils.get_now()
    today = now.date()
    if kind is None:
        kind = "morning" if now.hour < 12 else "evening"

    employees = _get_all_employees()
    sent = 0

    for emp in employees:
        if kind == "morning":
            # Skip anyone who already checked in - they don't need nagging.
            if db.get_daily_attendance_for_user(emp['id'], today) is not None:
                continue
            text = MORNING_REMINDER_MSG
        else:
            # Only people still clocked in have something left to do.
            if not db.is_user_checked_in(emp['id']):
                continue
            text = EVENING_REMINDER_MSG
        try:
            await bot.send_message(chat_id=emp['id'], text=text)
            sent += 1
        except Exception as e:
            logger.warning(f"{kind} reminder failed for {emp['full_name']} ({emp['id']}): {e}")

    settings.set_flag(_reminder_flag_key(kind), today.isoformat())
    logger.info(f"✅ {kind} reminders sent to {sent}/{len(employees)} employees")

    # Monday morning: fold the weekly digest into the same run, so it costs no
    # extra scheduled task (the free tier only allows one).
    digest_sent = False
    if kind == "morning" and now.weekday() == 0:
        digest_sent = await _send_weekly_digest(bot)

    return kind, sent, len(employees), digest_sent


async def _send_weekly_digest(bot):
    """Last 7 days summarised for the admins."""
    now = utils.get_now()
    start = (now - timedelta(days=7)).date()
    text = (
        f"📅 <b>HAFTALIK HISOBOT</b>\n"
        f"<i>{start.strftime('%d.%m')} — {now.strftime('%d.%m')}</i>\n"
        f"{'━' * 18}\n\n"
    )
    rows = db.get_month_attendance_details(start)
    if not rows:
        text += "<i>Bu haftada ma'lumot yo'q.</i>"
    else:
        per_employee = {}
        for r in rows:
            b = per_employee.setdefault(r['full_name'], {'days': 0, 'wage': 0.0, 'mins': 0.0})
            if r['check_in'] and r['check_out']:
                b['days'] += 1
                b['wage'] += r['total_wage'] or 0
                b['mins'] += ui.worked_minutes(r['check_in'], r['check_out'])
        grand = 0.0
        for name, b in sorted(per_employee.items(), key=lambda kv: -kv[1]['wage']):
            grand += b['wage']
            text += (
                f"👤 <b>{name}</b>\n"
                f"<code>  {b['days']} kun · {ui.fmt_duration(b['mins'])} · {ui.fmt_money(b['wage'])}</code>\n\n"
            )
        text += f"{'━' * 18}\n💵 <b>JAMI: {ui.fmt_money(grand)}</b>"

    conn = db.get_connection()
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE role='admin'")
    admins = c.fetchall()
    conn.close()

    ok = False
    for admin in admins:
        try:
            await bot.send_message(chat_id=admin['id'], text=text, parse_mode='HTML')
            ok = True
        except Exception as e:
            logger.warning(f"Weekly digest failed for admin {admin['id']}: {e}")
    return ok


@app.route('/cron/reminders/<secret>', methods=['GET', 'POST'])
def cron_reminders(secret):
    """Triggered by a scheduled task hitting this URL. The secret in the path
    keeps random internet traffic from spamming everyone with reminders.
    Optional ?kind=morning|evening pins which reminder to send; without it the
    time of day decides, so one task can cover either slot."""
    if secret != CRON_SECRET:
        return 'Forbidden', 403
    kind = request.args.get('kind')
    if kind not in (None, 'morning', 'evening'):
        return jsonify({'status': 'error', 'message': "kind must be morning or evening"}), 400
    try:
        kind, sent, total, digest = run_sync(_send_reminders_job(kind), timeout=120)
        return jsonify({
            'status': 'ok', 'kind': kind, 'sent': sent,
            'total': total, 'weekly_digest': digest,
        }), 200
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
        app_config.add_handler(CommandHandler("preview", cmd_preview))
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
            entry_points=[MessageHandler(
                filters.Regex(f"^({re.escape(ui.BTN_CORRECTION)}|{re.escape(msg.BTN_CORRECTION_REQUEST)})$"),
                correction_request_start,
            )],
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

        # Settings Conversation (edit a work-hour value)
        settings_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(settings_pick_callback, pattern="^set:")],
            states={
                SET_TIME_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_set_value)],
            },
            fallbacks=[CommandHandler("cancel", settings_cancel)],
            name="settings_conv",
            persistent=False,
            allow_reentry=True,
        )
        app_config.add_handler(settings_conv)

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
        app_config.add_handler(CallbackQueryHandler(preview_callback, pattern="^prev:"))
        app_config.add_handler(CallbackQueryHandler(report_export_callback, pattern="^repx:"))
        app_config.add_handler(CallbackQueryHandler(admin_report_callback, pattern="^rep:"))
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
