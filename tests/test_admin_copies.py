"""Requests every admin gets must show, in every admin's chat, that one of
them already dealt with it - and who.

With two or three admins, a correction approved by one stayed live for the
others: they couldn't tell it was done.
"""
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
os.environ['DATABASE_PATH'] = os.path.join(tempfile.mkdtemp(), 'admin_copies.db')

import app  # noqa: E402
import database as db  # noqa: E402
import utils  # noqa: E402

failures = []


def check(label, condition, detail=''):
    print(f"  {'PASS' if condition else 'FAIL'}  {label}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures.append(label)


class SentMessage:
    def __init__(self, chat_id, message_id, text):
        self.chat_id = chat_id
        self.message_id = message_id
        self.text = text


class FakeBot:
    """Keeps every chat's messages by id, so edits can be checked the way an
    admin would see them."""

    def __init__(self):
        self.sent = []
        self.chats = {}
        self.next_id = 100

    async def send_message(self, chat_id, text, reply_markup=None, **kwargs):
        self.next_id += 1
        message = {'chat_id': chat_id, 'text': text, 'reply_markup': reply_markup}
        self.sent.append(message)
        self.chats[(chat_id, self.next_id)] = message
        return SentMessage(chat_id, self.next_id, text)

    async def edit_message_text(self, text, chat_id, message_id, reply_markup=None, **kwargs):
        self.chats[(chat_id, message_id)] = {'chat_id': chat_id, 'text': text,
                                             'reply_markup': reply_markup}


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()


class FakeUser:
    def __init__(self, user_id):
        self.id = user_id
        self.username = None
        self.full_name = 'New account'


class FakeQuery:
    """A press on one admin's own copy: editing it edits that copy in the bot."""

    def __init__(self, bot, user_id, chat_id, message_id, data):
        self.bot = bot
        self.from_user = FakeUser(user_id)
        self.data = data
        self.answers = []
        self.message = SentMessage(chat_id, message_id, bot.chats[(chat_id, message_id)]['text'])

    async def answer(self, text=None):
        self.answers.append(text)

    async def edit_message_text(self, text, reply_markup=None, **kwargs):
        await self.bot.edit_message_text(text, self.message.chat_id, self.message.message_id,
                                         reply_markup=reply_markup)

    async def edit_message_reply_markup(self, reply_markup=None):
        current = self.bot.chats[(self.message.chat_id, self.message.message_id)]
        current['reply_markup'] = reply_markup


class FakeCallbackUpdate:
    def __init__(self, query):
        self.callback_query = query
        self.effective_user = query.from_user


class FakeContext:
    def __init__(self):
        self.user_data = {}


def copies_of(prefix):
    """(chat_id, message_id) of every message whose buttons start with prefix."""
    found = []
    for key, m in bot.chats.items():
        markup = m['reply_markup']
        if hasattr(markup, 'inline_keyboard') and any(b.callback_data.startswith(prefix)
                          for row in markup.inline_keyboard for b in row):
            found.append(key)
    return found


def press(handler, admin_id, key, data):
    query = FakeQuery(bot, admin_id, key[0], key[1], data)
    asyncio.run(handler(FakeCallbackUpdate(query), FakeContext()))
    return query


EMP, A1, A2, A3 = 501, 601, 602, 603
db.init_db()
db.add_user(EMP, '998900000101', 'Mustafo')
db.add_user(A1, 'AdminPhone', 'Odilbek', role='admin')
db.add_user(A2, 'AdminPhone', 'Abdulaziz Climadens', role='admin')
db.add_user(A3, 'AdminPhone', 'Uchinchi', role='admin')
db.update_rates(EMP, 'per_minute', rate_per_minute=0.04)

app.create_application()
app.telegram_app = FakeApp()
bot = app.telegram_app.bot

yesterday = (utils.get_now() - datetime.timedelta(days=1)).date().isoformat()

print("1. Исправление: одобрил один — видно у всех")
req_id = db.create_correction_request(EMP, yesterday, '09:00', '18:00')
asyncio.run(app._send_to_admins('correction', req_id, f"🆕 <b>Tuzatish so'rovi</b> #{req_id}",
                                app.InlineKeyboardMarkup([[
                                    app.InlineKeyboardButton('ok', callback_data=f"approve_req_{req_id}"),
                                    app.InlineKeyboardButton('no', callback_data=f"reject_req_{req_id}"),
                                ]])))
live = copies_of(f"approve_req_{req_id}")
check("у трёх админов по копии с кнопками", sorted(k[0] for k in live) == [A1, A2, A3])

press(app.approve_request_callback, A1, next(k for k in live if k[0] == A1), f"approve_req_{req_id}")
check("день записан", db.get_correction_request(req_id)['status'] == 'APPROVED')
check("кнопок больше ни у кого нет", not copies_of(f"approve_req_{req_id}"))
for admin in (A1, A2, A3):
    text = next(m['text'] for k, m in bot.chats.items() if k in live and k[0] == admin)
    check(f"у админа {admin}: «Tasdiqlandi — Odilbek» и сам запрос",
          'Tasdiqlandi' in text and 'Odilbek' in text and 'Tuzatish' in text)

print("\n2. Отказ тоже виден у всех")
req2 = db.create_correction_request(EMP, yesterday, '10:00', '17:00')
asyncio.run(app._send_to_admins('correction', req2, f"🆕 so'rov #{req2}",
                                app.InlineKeyboardMarkup([[
                                    app.InlineKeyboardButton('no', callback_data=f"reject_req_{req2}")]])))
live2 = copies_of(f"reject_req_{req2}")
press(app.reject_request_callback, A2, next(k for k in live2 if k[0] == A2), f"reject_req_{req2}")
texts = [bot.chats[k]['text'] for k in live2]
check("у всех «Rad etildi — Abdulaziz Climadens»",
      len(texts) == 3 and all('Rad etildi' in t and 'Abdulaziz Climadens' in t for t in texts))

print("\n3. Список «🔔 Tuzatishlar» тоже закрывается")
req3 = db.create_correction_request(EMP, yesterday, '09:30', '18:00')


class ListUpdate:
    def __init__(self, user_id):
        self.effective_user = FakeUser(user_id)
        self.message = self

    async def reply_text(self, text, **kwargs):
        pass


asyncio.run(app.admin_correction_list_handler(ListUpdate(A3), FakeContext()))
listed = copies_of(f"approve_req_{req3}")
check("в списке у A3 есть кнопки", [k[0] for k in listed] == [A3])
asyncio.run(app._send_to_admins('correction', req3, "so'rov",
                                app.InlineKeyboardMarkup([[
                                    app.InlineKeyboardButton('ok', callback_data=f"approve_req_{req3}")]])))
first = next(k for k in copies_of(f"approve_req_{req3}") if k[0] == A1)
press(app.approve_request_callback, A1, first, f"approve_req_{req3}")
check("и копия из списка, и рассылка закрыты", not copies_of(f"approve_req_{req3}"))

print("\n4. Аванс: отменил один — видно у всех")
advance_id = db.add_advance(EMP, 50, 'yo\'l', utils.get_now())
asyncio.run(app._notify_admins_of_advance(advance_id))
adv_live = copies_of(f"adv:void:{advance_id}")
check("у трёх админов кнопка «Bekor qilish»", len(adv_live) == 3)
press(app.advance_void_callback, A3, next(k for k in adv_live if k[0] == A3), f"adv:void:{advance_id}")
check("аванс отменён", db.get_advance(advance_id)['status'] != 'ACTIVE')
check("кнопок не осталось", not copies_of(f"adv:void:{advance_id}"))
check("у всех «Bekor qilindi — Uchinchi»",
      all('Bekor qilindi' in bot.chats[k]['text'] and 'Uchinchi' in bot.chats[k]['text'] for k in adv_live))

print("\n5. Перенос аккаунта: решение одного видно у всех")
NEW = 9200000001


class ContactUpdate:
    def __init__(self):
        self.effective_user = FakeUser(NEW)
        self.message = self
        self.contact = type('C', (), {'user_id': NEW, 'phone_number': '+998900000101'})()

    async def reply_text(self, text, **kwargs):
        pass


asyncio.run(app.contact_handler(ContactUpdate(), FakeContext()))
rel_live = copies_of(f"relink:ok:{NEW}")
check("запрос у трёх админов", len(rel_live) == 3)
press(app.relink_callback, A2, next(k for k in rel_live if k[0] == A2), f"relink:ok:{NEW}")
check("перенесён", db.get_user(NEW) is not None and db.get_user(EMP) is None)
check("у всех «Ulandi — Abdulaziz Climadens», без кнопок",
      not copies_of(f"relink:") and
      all('Ulandi' in bot.chats[k]['text'] and 'Abdulaziz Climadens' in bot.chats[k]['text']
          for k in rel_live))

print("\n6. Сообщение, отправленное до обновления, тоже закрывается")
req4 = db.create_correction_request(NEW, yesterday, '09:00', '17:00')
bot.next_id += 1
old_key = (A1, bot.next_id)
bot.chats[old_key] = {'chat_id': A1, 'text': 'Tuzatish so\'rovi <eski>', 'reply_markup': None}
press(app.approve_request_callback, A1, old_key, f"approve_req_{req4}")
check("нажатое старое сообщение переписано с итогом",
      'Tasdiqlandi' in bot.chats[old_key]['text'] and '&lt;eski&gt;' in bot.chats[old_key]['text'])

print()
if failures:
    print(f"ПРОВАЛЕНО: {len(failures)}")
    sys.exit(1)
print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
