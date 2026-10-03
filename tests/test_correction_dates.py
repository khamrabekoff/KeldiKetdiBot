"""A correction can't close a day that hasn't happened yet.

Just after midnight "Bugun" is already the new day. A request sent then for
yesterday's hours was recorded for today; once approved, today held a finished
day before the employee came in, and KELDIM / KETDIM both refused all day.
"""
import asyncio
import datetime
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The Windows console is not UTF-8 by default and the replies carry emoji
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

os.environ['BOT_TOKEN'] = '123456:AAHtesttokenAAHtesttokenAAHtesttoken'
os.environ['ADMIN_SECRET'] = 'test_secret'
os.environ['DATABASE_PATH'] = os.path.join(tempfile.mkdtemp(), 'correction_dates.db')

from telegram.ext import ConversationHandler  # noqa: E402

import app  # noqa: E402
import database as db  # noqa: E402
import ui  # noqa: E402
import utils  # noqa: E402

failures = []


def check(label, condition, detail=''):
    print(f"  {'PASS' if condition else 'FAIL'}  {label}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures.append(label)


class FakeMessage:
    def __init__(self, text=''):
        self.text = text
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


class FakeUser:
    def __init__(self, user_id):
        self.id = user_id


class FakeUpdate:
    def __init__(self, user_id, text=''):
        self.message = FakeMessage(text)
        self.effective_user = FakeUser(user_id)


class FakeContext:
    def __init__(self, **user_data):
        self.user_data = dict(user_data)


class FakeQuery:
    def __init__(self, data):
        self.data = data
        self.edits = []
        self.message = FakeMessage('so\'rov')

    async def answer(self, text=None):
        pass

    async def edit_message_text(self, text, **kwargs):
        self.edits.append(text)


class FakeCallbackUpdate:
    def __init__(self, user_id, data):
        self.callback_query = FakeQuery(data)
        self.effective_user = FakeUser(user_id)


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text))


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()


EMP = 901
ADMIN = 902
TODAY = datetime.date(2026, 10, 3)
YESTERDAY = TODAY - datetime.timedelta(days=1)
# 00:43 in Tashkent, while the UTC server still lives on the 2nd
NOW = datetime.datetime(2026, 10, 3, 0, 43)
utils.get_now = lambda: NOW
app.telegram_app = FakeApp()

db.init_db()
db.add_user(EMP, '998900000040', 'Mustafo')
db.add_user(ADMIN, '998900000041', 'Boss', role='admin')


def send_out_time(date_str, in_str, out_str):
    context = FakeContext(req_date=date_str, req_in=in_str)
    update = FakeUpdate(EMP, out_str)
    state = asyncio.run(app.correction_request_out(update, context))
    return state, update.message.replies, context


print("1. Сотрудник выбирает «Bugun» сразу после полуночи")
state, replies, context = send_out_time(str(TODAY), '09:35', '18:37')
check("разговор завершён, а не ждёт другое время", state == ConversationHandler.END, str(state))
check("объяснено, что время ещё не наступило", any('hali kelmagan' in r for r in replies), str(replies))
check("подсказано выбрать «Kecha»", any('Kecha' in r for r in replies))
check("запрос не сохранён", 'req_out' not in context.user_data)

print("\n2. Тот же запрос за вчера проходит")
state, replies, _ = send_out_time(str(YESTERDAY), '09:35', '18:37')
check("переходит к подтверждению", state == app.COR_REQ_CONFIRM, str(state))

print("\n3. Уход раньше прихода")
state, replies, _ = send_out_time(str(YESTERDAY), '18:00', '09:00')
check("просит ввести время заново", state == app.COR_REQ_OUT, str(state))
check("говорит, что не так", any("keyin bo'lishi" in r for r in replies), str(replies))

print("\n4. Админ не может одобрить запрос на будущее, созданный до исправления")
req_id = db.create_correction_request(EMP, str(TODAY), '09:35', '18:37')
update = FakeCallbackUpdate(ADMIN, f"approve_req_{req_id}")
asyncio.run(app.approve_request_callback(update, FakeContext()))
check("запрос остался PENDING", db.get_correction_request(req_id)['status'] == 'PENDING')
check("день не закрыт заранее", db.get_daily_attendance_for_user(EMP, TODAY) is None)
check("админу сказано почему", any('Tasdiqlab bo\'lmaydi' in r for r in update.callback_query.message.replies),
      str(update.callback_query.message.replies))
check("сотруднику ничего не ушло", not app.telegram_app.bot.sent)

print("\n5. Запрос за вчера одобряется как раньше")
req_id = db.create_correction_request(EMP, str(YESTERDAY), '09:35', '18:37')
asyncio.run(app.approve_request_callback(FakeCallbackUpdate(ADMIN, f"approve_req_{req_id}"), FakeContext()))
check("запрос APPROVED", db.get_correction_request(req_id)['status'] == 'APPROVED')
row = db.get_daily_attendance_for_user(EMP, YESTERDAY)
check("вчерашний день записан", row is not None and row['check_out'] is not None)

print("\n6. Если день всё же закрыт, KELDIM объясняет, что делать")
db.update_attendance_manual(EMP, TODAY, datetime.datetime(2026, 10, 3, 9, 0),
                            datetime.datetime(2026, 10, 3, 18, 0), 0)
result = db.check_in_user(EMP, datetime.datetime(2026, 10, 3, 9, 5))
check("отметка не прошла", not result['success'])
check("отправляет в «Tuzatish»", 'Tuzatish' in result['message'], result['message'])

print("\n7. Кнопка KETDIM после полуночи по Ташкенту")
NIGHT = datetime.date(2026, 10, 4)
NOW = datetime.datetime(2026, 10, 4, 1, 30)
db.check_in_user(EMP, datetime.datetime(2026, 10, 4, 1, 0))
check("сотрудник на работе — показана KETDIM", db.is_user_checked_in(EMP))
keyboard = ui.employee_keyboard(EMP)
check("на клавиатуре KETDIM", keyboard.keyboard[0][0].text == ui.BTN_CHECK_OUT, keyboard.keyboard[0][0].text)

print("\n8. Ручная правка админа тоже не закрывает день заранее")
NOW = datetime.datetime(2026, 10, 5, 0, 20)
context = FakeContext(edit_user_id=EMP, edit_att_date='2026-10-05', edit_att_in='09:00')
update = FakeUpdate(ADMIN, '18:00')
state = asyncio.run(app.edit_att_out_handler(update, context))
check("разговор завершён", state == ConversationHandler.END, str(state))
check("правка не сохранена", db.get_daily_attendance_for_user(EMP, datetime.date(2026, 10, 5)) is None)
check("админу объяснено", any('hali kelmagan' in r for r in update.message.replies), str(update.message.replies))
context = FakeContext(edit_user_id=EMP, edit_att_date='2026-10-04', edit_att_in='09:00')
asyncio.run(app.edit_att_out_handler(FakeUpdate(ADMIN, '18:00'), context))
row = db.get_daily_attendance_for_user(EMP, datetime.date(2026, 10, 4))
check("правка за прошедший день сохраняется", row is not None and row['check_out'].hour == 18)

print("\n" + ("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ" if not failures else f"ПАДЕНИЙ: {len(failures)} -> {failures}"))
sys.exit(0 if not failures else 1)
