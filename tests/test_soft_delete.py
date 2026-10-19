"""Deleting an employee takes away the bot, not the books: Ibrohim, deleted
on 2026-10-18, dropped out of every report with $103 earned and a $100
advance, so his $3 could no longer be seen or paid."""
import asyncio
import datetime
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

os.environ['BOT_TOKEN'] = '123456:AAHtesttokenAAHtesttokenAAHtesttoken'
os.environ['ADMIN_SECRET'] = 'test_secret'
os.environ['DATABASE_PATH'] = os.path.join(tempfile.mkdtemp(), 'soft_delete.db')

import openpyxl  # noqa: E402
from telegram import Update  # noqa: E402
from telegram.ext import ApplicationHandlerStop, ConversationHandler, TypeHandler  # noqa: E402

import analytics  # noqa: E402
import app  # noqa: E402
import database as db  # noqa: E402
import excel_export  # noqa: E402
import messages as msg  # noqa: E402
import pdf_export  # noqa: E402
import ui  # noqa: E402
import utils  # noqa: E402

failures = []


def check(label, condition, detail=''):
    print(f"  {'PASS' if condition else 'FAIL'}  {label}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures.append(label)


class Sent:
    def __init__(self, chat_id, message_id):
        self.chat_id = chat_id
        self.message_id = message_id


class FakeBot:
    def __init__(self):
        self.sent = []
        self.next_id = 100

    async def send_message(self, chat_id, text, reply_markup=None, **kwargs):
        self.next_id += 1
        self.sent.append({'chat_id': chat_id, 'text': text, 'reply_markup': reply_markup})
        return Sent(chat_id, self.next_id)

    async def edit_message_text(self, text, chat_id, message_id, reply_markup=None, **kwargs):
        pass


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()


class FakeUser:
    def __init__(self, user_id, full_name='Someone'):
        self.id = user_id
        self.username = None
        self.full_name = full_name


class TextMessage:
    def __init__(self, text=''):
        self.text = text
        self.contact = None
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


class FakeQuery:
    def __init__(self, user_id, data, message=None):
        self.from_user = FakeUser(user_id)
        self.data = data
        self.message = message
        self.edits = []
        self.answered = False

    async def answer(self, text=None):
        self.answered = True

    async def edit_message_text(self, text=None, **kwargs):
        self.edits.append(text)


class CallbackUpdate:
    def __init__(self, query):
        self.callback_query = query
        self.message = None
        self.effective_user = query.from_user


class MessageUpdate:
    def __init__(self, user_id, text='', phone=None):
        self.callback_query = None
        self.effective_user = FakeUser(user_id)
        self.message = TextMessage(text)
        if phone:
            self.message.contact = type('C', (), {'user_id': user_id, 'phone_number': phone})()


class FakeContext:
    def __init__(self):
        self.user_data = {}


def run(coro):
    return asyncio.run(coro)


def turned_away(update):
    """True if the gate stopped the update before any handler."""
    try:
        run(app.turn_away_deleted(update, FakeContext()))
        return False
    except ApplicationHandlerStop:
        return True


def share(user_id, phone):
    update = MessageUpdate(user_id, phone=phone)
    run(app.contact_handler(update, FakeContext()))
    return update.message.replies


def entry_for(user_id):
    return next((e for e in analytics.month_payroll(month)['employees'] if e['user_id'] == user_id), None)


def excel_cells():
    wb = openpyxl.load_workbook(excel_export.create_monthly_report_excel(month))
    return [str(c.value) for ws in wb.worksheets for row in ws.iter_rows() for c in row if c.value]


IBROHIM, MOHIR, A1, A2, NEW = 600, 601, 701, 702, 9600
PHONE = '998900000600'
db.init_db()
db.add_user(IBROHIM, PHONE, 'Ibrohim')
db.add_user(MOHIR, '998900000601', 'Mohir')
db.add_user(A1, 'AdminPhone', 'Odilbek', role='admin')
db.add_user(A2, 'AdminPhone', 'Abdulaziz Climadens', role='admin')
db.update_rates(IBROHIM, 'per_minute', rate_per_minute=0.2)
db.update_rates(MOHIR, 'per_minute', rate_per_minute=0.2)

real_app = app.create_application()
app.telegram_app = FakeApp()
bot = app.telegram_app.bot
now = utils.get_now()
month = now.date().replace(day=1)
ym = month.strftime('%Y-%m')
yesterday = (now - datetime.timedelta(days=1)).date()

# $103 for a day this month, a $100 advance, and a day left open
first = datetime.datetime.combine(month, datetime.time(9, 0))
db.update_attendance_manual(IBROHIM, month, first, first + datetime.timedelta(hours=8), 103)
db.add_advance(IBROHIM, 100, None, now)
db.check_in_user(IBROHIM, datetime.datetime.combine(yesterday, datetime.time(9, 0)))
db.update_attendance_manual(MOHIR, month, first, first + datetime.timedelta(hours=8), 80)

print("1. Удаление выключает доступ, но не стирает запись")
pending = db.create_correction_request(IBROHIM, yesterday.isoformat(), '09:00', '18:00')
query = FakeQuery(A1, f"delok:{IBROHIM}", TextMessage())
run(app.delete_confirm_callback(CallbackUpdate(query), FakeContext()))
check("get_user его больше не видит", db.get_user(IBROHIM) is None)
kept = db.get_user(IBROHIM, include_inactive=True)
check("строка осталась, is_active = 0", kept is not None and kept['is_active'] == 0)
check("ставка осталась", db.get_db_rates(IBROHIM)['rate_per_minute'] == 0.2)
check("заявка отменена", db.get_correction_request(pending)['status'] == 'CANCELLED')
notice = [m['text'] for m in bot.sent if m['chat_id'] == A2]
check("второй админ узнал, что история осталась",
      notice and "o'chirildi" in notice[0] and "(o'chirilgan)" in notice[0])
query = FakeQuery(A1, f"delok:{IBROHIM}", TextMessage())
bot.sent.clear()
run(app.delete_confirm_callback(CallbackUpdate(query), FakeContext()))
check("второе нажатие — «не найден», без нового уведомления",
      query.edits == ["❌ Xodim topilmadi."] and not bot.sent)

print("\n2. В отчёте за месяц, Excel и PDF он есть, с пометкой")
entry = entry_for(IBROHIM)
check("в расчёте: $103 − $100 = $3",
      entry and round(entry['wage'], 2) == 103 and round(entry['advance'], 2) == 100
      and round(entry['to_pay'], 2) == 3, str(entry and entry['to_pay']))
check("помечен неактивным", entry and entry['active'] is False and entry['name'] == "Ibrohim (o'chirilgan)")
card = ui.admin_month_report_card(month)
check("в отчёте бота", "Ibrohim (o'chirilgan)" in card and 'Mohir' in card)
cells = excel_cells()
check("в Excel", any("Ibrohim (o'chirilgan)" in c for c in cells))
check("PDF собирается", pdf_export.create_monthly_pdf_report(month) is not None)

print("\n3. Среди текущих сотрудников его нет")
check("get_employees", [e['id'] for e in db.get_employees()] == [MOHIR])
text, keyboard = ui.admin_employee_list()
check("список сотрудников", 'Ibrohim' not in text and not any(
    b.callback_data == f"edit_{IBROHIM}" for row in keyboard.inline_keyboard for b in row))
check("панель «сегодня»", 'Ibrohim' not in ui.admin_dashboard_card())
check("напоминания", [e['id'] for e in app._get_all_employees()] == [MOHIR])
bot.sent.clear()
run(app._broadcast(bot, 'salom', 'employees'))
run(app._broadcast(bot, 'salom', 'all'))
check("рассылки", not any(m['chat_id'] == IBROHIM for m in bot.sent))
check("незакрытые дни", not any(r['user_id'] == IBROHIM for r in db.get_unreported_open_shifts(now.date())))
check("поиск по номеру (перепривязка)", db.get_user_by_phone(PHONE, role='employee') is None)
check("аналитика", [s['user_id'] for s in analytics.get_all_employees_stats()] == [MOHIR])
ctx = FakeContext()
query = FakeQuery(A1, f"edit_{IBROHIM}", TextMessage())
state = run(app.handle_callback_query(CallbackUpdate(query), ctx))
check("старая карточка не открывает меню",
      state == ConversationHandler.END and 'edit_user_id' not in ctx.user_data)

print("\n4. Остаток можно выплатить; после этого он уходит из списка выплат")


def payment_buttons():
    _, keyboard = ui.payment_list_card(month)
    return [b.callback_data for row in keyboard.inline_keyboard for b in row]


check("в списке выплат, пока должны", f"pay:emp:{IBROHIM}:{ym}" in payment_buttons())
state = run(app.payment_sum_start(
    CallbackUpdate(FakeQuery(A1, f"pay:sum:{IBROHIM}:{ym}", TextMessage())), FakeContext()))
check("можно ввести свою сумму", state == app.PAY_SUM)
query = FakeQuery(A1, f"pay:do:{IBROHIM}:{ym}:300", TextMessage())
run(app.payment_do_callback(CallbackUpdate(query), FakeContext()))
paid = db.get_payments(month, IBROHIM)
check("$3 выплачено", len(paid) == 1 and round(paid[0]['amount'], 2) == 3)
entry = entry_for(IBROHIM)
check("месяц закрыт", entry and entry['settled'] and round(entry['to_pay'], 2) == 0)
check("рассчитанный — больше не в списке выплат", f"pay:emp:{IBROHIM}:{ym}" not in payment_buttons())
check("Мохир — по-прежнему в списке", f"pay:emp:{MOHIR}:{ym}" in payment_buttons())
check("но в отчёте месяца остался", "Ibrohim (o'chirilgan)" in ui.admin_month_report_card(month))

print("\n5. Пользоваться ботом он не может")
before = len(db.get_user_attendance(IBROHIM, limit=100))
update = MessageUpdate(IBROHIM, ui.BTN_CHECK_IN)
check("«Keldim» остановлен до обработчиков", turned_away(update))
check("ему сказано «нет в списке»", update.message.replies == [msg.MSG_NOT_AUTHORIZED])
check("/in остановлен", turned_away(MessageUpdate(IBROHIM, '/in')))
query = FakeQuery(IBROHIM, f"creq_dt_{yesterday.isoformat()}")
check("кнопка остановлена", turned_away(CallbackUpdate(query)) and query.answered)
check("ни одного нового дня", len(db.get_user_attendance(IBROHIM, limit=100)) == before)
check("/start проходит", not turned_away(MessageUpdate(IBROHIM, '/start')))
check("контакт проходит", not turned_away(MessageUpdate(IBROHIM, phone=PHONE)))
check("действующего не трогает", not turned_away(MessageUpdate(MOHIR, ui.BTN_CHECK_IN)))
check("незнакомца не трогает", not turned_away(MessageUpdate(123456, '/start')))
update = MessageUpdate(IBROHIM, '/start')
run(app.start(update, FakeContext()))
check("/start показывает приветствие", update.message.replies == [msg.MSG_WELCOME])
bot.sent.clear()
check("контакт без приглашения — «нет в списке»", share(IBROHIM, '+' + PHONE) == [msg.MSG_NOT_AUTHORIZED])
check("и админам не ушёл запрос на перепривязку", not bot.sent)
check("не админ", not run(app.check_admin(IBROHIM)))
gate = [h for h in real_app.handlers.get(-1, []) if isinstance(h, TypeHandler)]
check("проверка стоит в группе -1 для всех обновлений",
      len(gate) == 1 and gate[0].callback is app.turn_away_deleted and gate[0].type is Update)

print("\n6. Повторное приглашение того же аккаунта — возвращает с историей")
db.add_pending_user(PHONE, 'Ibrohim', 'per_minute', rate_per_minute=0.3)
replies = share(IBROHIM, '+' + PHONE)
back = db.get_user(IBROHIM)
check("снова активен под тем же ID", back is not None and back['is_active'] == 1)
check("ему сказали, что он вошёл", replies and replies[0] == msg.MSG_AUTH_SUCCESS.format(name='Ibrohim'))
check("ставка из нового приглашения", db.get_db_rates(IBROHIM)['rate_per_minute'] == 0.3)
entry = entry_for(IBROHIM)
check("история при нём, без пометки",
      entry and entry['active'] and entry['name'] == 'Ibrohim' and round(entry['wage'], 2) == 103
      and round(entry['paid'], 2) == 3)
check("снова в списке сотрудников", IBROHIM in [e['id'] for e in db.get_employees()])
check("проверка его больше не останавливает", not turned_away(MessageUpdate(IBROHIM, ui.BTN_CHECK_IN)))

print("\n7. Повторное приглашение с другого аккаунта — новая запись, старая остаётся")
run(app.delete_confirm_callback(CallbackUpdate(FakeQuery(A1, f"delok:{IBROHIM}", TextMessage())),
                                FakeContext()))
db.add_pending_user(PHONE, 'Ibrohim', 'per_minute', rate_per_minute=0.3)
share(NEW, '+' + PHONE)
check("новый аккаунт — действующий сотрудник", db.get_user(NEW) is not None)
check("старый по-прежнему удалён", db.get_user(IBROHIM) is None
      and db.get_user(IBROHIM, include_inactive=True) is not None)
old = entry_for(IBROHIM)
check("старая история — под старой записью, с пометкой",
      old and old['name'] == "Ibrohim (o'chirilgan)" and round(old['wage'], 2) == 103)

print()
if failures:
    print(f"ПРОВАЛЕНО: {len(failures)}")
    sys.exit(1)
print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
