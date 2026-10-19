"""Fixes from the review of the relink / delete / open-shift / shared-copy
work: each block below reproduces one finding and checks it is gone."""
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
os.environ['DATABASE_PATH'] = os.path.join(tempfile.mkdtemp(), 'review_fixes.db')

from telegram import Chat, InaccessibleMessage  # noqa: E402
from telegram.ext import ConversationHandler  # noqa: E402

import app  # noqa: E402
import database as db  # noqa: E402
import messages as msg  # noqa: E402
import settings  # noqa: E402
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
        self.chats = {}
        self.next_id = 100
        self.down = set()        # chat ids whose sends fail
        self.too_long = False    # refuse anything over Telegram's limit

    async def send_message(self, chat_id, text, reply_markup=None, **kwargs):
        if chat_id in self.down:
            raise RuntimeError("proxy 503")
        if self.too_long and len(text) > 4096:
            raise RuntimeError("Message is too long")
        self.next_id += 1
        self.sent.append({'chat_id': chat_id, 'text': text, 'reply_markup': reply_markup})
        self.chats[(chat_id, self.next_id)] = {'text': text, 'reply_markup': reply_markup}
        return Sent(chat_id, self.next_id)

    async def edit_message_text(self, text, chat_id, message_id, reply_markup=None, **kwargs):
        self.chats[(chat_id, message_id)] = {'text': text, 'reply_markup': reply_markup}


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
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


class FakeQuery:
    def __init__(self, user_id, data, message=None, fail_edit=False):
        self.from_user = FakeUser(user_id)
        self.data = data
        self.message = message
        self.edits = []
        self.fail_edit = fail_edit

    async def answer(self, text=None):
        pass

    async def edit_message_text(self, text=None, **kwargs):
        if self.fail_edit:
            raise RuntimeError("proxy 503")
        self.edits.append(text)

    async def edit_message_reply_markup(self, reply_markup=None):
        pass


class CallbackUpdate:
    def __init__(self, query):
        self.callback_query = query
        self.effective_user = query.from_user


class ContactUpdate:
    def __init__(self, user_id, phone):
        self.effective_user = FakeUser(user_id)
        self.message = TextMessage()
        self.message.contact = type('C', (), {'user_id': user_id, 'phone_number': phone})()


class FakeContext:
    def __init__(self):
        self.user_data = {}


def run(coro):
    return asyncio.run(coro)


def share(user_id, phone):
    update = ContactUpdate(user_id, phone)
    run(app.contact_handler(update, FakeContext()))
    return update.message.replies


EMP, EMP2, A1, A2 = 300, 301, 401, 402
db.init_db()
db.add_user(EMP, '998501704456', 'Mohir')
db.add_user(EMP2, '998900000301', 'Ali <&> Vali')
db.add_user(A1, 'AdminPhone', 'Odilbek', role='admin')
db.add_user(A2, 'AdminPhone', 'Abdulaziz Climadens', role='admin')
db.update_rates(EMP, 'per_minute', rate_per_minute=0.02)
db.update_rates(EMP2, 'per_minute', rate_per_minute=0.02)

app.create_application()
app.telegram_app = FakeApp()
bot = app.telegram_app.bot
now = utils.get_now()
yesterday = (now - datetime.timedelta(days=1)).date()

print("1. Сотрудник не открывает меню управления подделанной кнопкой")
ctx = FakeContext()
state = run(app.handle_callback_query(CallbackUpdate(FakeQuery(EMP, f"edit_{EMP}", TextMessage())), ctx))
check("edit_ от сотрудника — отказ", state == ConversationHandler.END and 'edit_user_id' not in ctx.user_data)
state = run(app.employee_action_callback(
    CallbackUpdate(FakeQuery(EMP, f"act_rates_{EMP}", TextMessage())), FakeContext()))
check("act_rates_ от сотрудника — отказ", state == ConversationHandler.END)
state = run(app.handle_callback_query(CallbackUpdate(FakeQuery(A1, f"edit_{EMP}", TextMessage())), ctx))
check("админ по-прежнему открывает меню", state == app.ACTION_MENU)

print("\n2. Номер с теми же 9 цифрами из другой страны — не сотрудник")
check("same_phone: +7 950… ≠ +998 50…", not db.same_phone('998501704456', '79501704456'))
check("same_phone: без кода сравнивает 9 цифр", db.same_phone('501704456', '998501704456'))
replies = share(9000001, '+79501704456')
check("чужой номер получает «нет в списке»", replies == [msg.MSG_NOT_AUTHORIZED])
check("админам ничего не ушло", not bot.sent)

print("\n3. В запросе виден номер, который прислали")
replies = share(9000002, '+998501704456')
request = [m for m in bot.sent if m['chat_id'] == A1]
check("запрос ушёл", replies == [msg.MSG_RELINK_SENT] and request)
check("в запросе оба номера", request and request[0]['text'].count('+998501704456') == 2)

print("\n4. Запрос, не дошедший ни до одного админа, можно отправить снова")
bot.down = {A1, A2}
replies = share(9000003, '998501704456')
check("человеку сказано повторить позже", replies == [msg.MSG_RELINK_RETRY])
check("запрос не повис", not settings.get_flag(app._relink_flag(9000003)))
bot.down = set()
replies = share(9000003, '998501704456')
check("повтор доходит", replies == [msg.MSG_RELINK_SENT])

print("\n5. Неудачный перенос — человеку сообщают")
db.add_user(9000004, 'AdminPhone', 'Busy', role='employee')  # the new id is taken
settings.set_flag(app._relink_flag(9000004), EMP)
bot.sent.clear()
run(app.relink_callback(CallbackUpdate(FakeQuery(A1, "relink:ok:9000004", TextMessage())), FakeContext()))
check("ему пришло «не удалось»",
      any(m['chat_id'] == 9000004 and m['text'] == msg.MSG_RELINK_FAILED for m in bot.sent))
db.delete_user(9000004)

print("\n6. Кнопка на старом (недоступном) сообщении не теряет уведомление")
req_id = db.create_correction_request(EMP, yesterday.isoformat(), '09:00', '18:00')
run(app._send_to_admins('correction', req_id, "so'rov", None))
bot.sent.clear()
old = InaccessibleMessage(chat=Chat(A1, 'private'), message_id=1)
run(app.approve_request_callback(CallbackUpdate(FakeQuery(A1, f"approve_req_{req_id}", old)), FakeContext()))
check("одобрено", db.get_correction_request(req_id)['status'] == 'APPROVED')
check("сотрудник узнал", any(m['chat_id'] == EMP for m in bot.sent))

print("\n7. Имя с < и & не ломает запрос")
bot.sent.clear()
upd = type('U', (), {})()
upd.effective_user = FakeUser(EMP2)
upd.message = TextMessage('✅ Tasdiqlash')
cctx = FakeContext()
cctx.user_data.update({'req_date': yesterday.isoformat(), 'req_in': '09:00', 'req_out': '18:00'})
run(app.correction_request_confirm(upd, cctx))
to_admin = [m for m in bot.sent if m['chat_id'] == A1]
check("имя экранировано", to_admin and 'Ali &lt;&amp;&gt; Vali' in to_admin[0]['text'])

print("\n8. Отмена аванса пересчитывает итог в копиях")
first = db.add_advance(EMP, 100, None, now)
second = db.add_advance(EMP, 50, None, now)
run(app._notify_admins_of_advance(second))
copies = [k for k, m in bot.chats.items() if m['reply_markup'] is not None
          and any(b.callback_data == f"adv:void:{second}" for row in m['reply_markup'].inline_keyboard for b in row)]
check("копии у обоих админов", len(copies) == 2)
run(app.advance_void_callback(CallbackUpdate(FakeQuery(A1, f"adv:void:{second}", TextMessage())), FakeContext()))
texts = [bot.chats[k]['text'] for k in copies]
check("итог без отменённого аванса", all('$100.00' in t.split('jami avans')[1] for t in texts),
      texts[0].split('jami avans')[1][:20] if texts else '')
check("кто отменил — указано", all('Bekor qilindi' in t and 'Odilbek' in t for t in texts))

print("\n9. Удаление: уведомление уходит даже если экран не обновился; заявки закрыты")
pending = db.create_correction_request(EMP2, yesterday.isoformat(), '10:00', '17:00')
run(app._send_to_admins('correction', pending, "so'rov 2", app.InlineKeyboardMarkup([[
    app.InlineKeyboardButton('ok', callback_data=f"approve_req_{pending}")]])))
bot.sent.clear()
query = FakeQuery(A1, f"delok:{EMP2}", TextMessage(), fail_edit=True)
run(app.delete_confirm_callback(CallbackUpdate(query), FakeContext()))
check("удалён", db.get_user(EMP2) is None)
check("второй админ получил уведомление", any(m['chat_id'] == A2 and "o'chirildi" in m['text'] for m in bot.sent))
check("заявка отменена", db.get_correction_request(pending)['status'] == 'CANCELLED')
check("кнопки заявки закрыты у всех",
      not [m for m in bot.chats.values() if m['reply_markup'] is not None and any(
          b.callback_data == f"approve_req_{pending}" for row in m['reply_markup'].inline_keyboard for b in row)])

print("\n10. Сводка открытых смен: тёзки раздельно, длинная — по частям")
same1, same2 = 500, 501
db.add_user(same1, '998900000500', 'Aziz')
db.add_user(same2, '998900000501', 'Aziz')
rows = [{'user_id': same1, 'full_name': 'Aziz', 'date': yesterday, 'check_in': now},
        {'user_id': same2, 'full_name': 'Aziz', 'date': yesterday, 'check_in': now}]
check("два блока «Aziz»", ''.join(ui.open_shifts_admin_texts(rows)).count('👤 <b>Aziz</b>') == 2)
long_rows = [{'user_id': same1, 'full_name': 'Aziz', 'date': yesterday - datetime.timedelta(days=i),
              'check_in': now} for i in range(200)]
parts = ui.open_shifts_admin_texts(long_rows)
check("200 дней — несколько сообщений, каждое < 4096", len(parts) > 1 and all(len(p) < 4096 for p in parts),
      f"{len(parts)} частей")

print("\n11. Пока админы не получили сводку — сотрудника не трогаем и всё повторим")
for i in range(150):
    db.check_in_user(same1, datetime.datetime.combine(yesterday - datetime.timedelta(days=i),
                                                      datetime.time(9, 0)))
bot.sent.clear()
bot.down = {A1, A2}
settings.set_flag(app.OPEN_SHIFTS_FLAG, '')
run(app._alert_open_shifts())
check("сотруднику ничего", not any(m['chat_id'] == same1 for m in bot.sent))
check("ничего не помечено", len(db.get_unreported_open_shifts(now.date())) >= 150)
bot.down = set()
bot.too_long = True
settings.set_flag(app.OPEN_SHIFTS_FLAG, '')
run(app._alert_open_shifts())
check("длинная сводка дошла частями и всё помечено", not db.get_unreported_open_shifts(now.date()))
check("сотрудник узнал один раз", sum(1 for m in bot.sent if m['chat_id'] == same1) == 1)

print("\n12. Ночью проверка не запускается")
settings.set_flag(app.OPEN_SHIFTS_FLAG, '')
night = datetime.datetime.combine(now.date(), datetime.time(0, 30))
morning = datetime.datetime.combine(now.date(), settings.get_time('work_start'))
check("00:30 — рано", not app._open_shifts_due(night))
check("к началу работы — пора", app._open_shifts_due(morning))
settings.set_flag(app.OPEN_SHIFTS_FLAG, now.date().isoformat())
check("второй раз за день — нет", not app._open_shifts_due(morning))

print()
if failures:
    print(f"ПРОВАЛЕНО: {len(failures)}")
    sys.exit(1)
print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
