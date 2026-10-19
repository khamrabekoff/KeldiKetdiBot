"""An employee on a new Telegram account, deleting an employee, and days
left open overnight.

Mohir deleted a hacked account and came back on the same number: the bot
knew only his old Telegram id and turned him away. Deleting Ibrohim dropped
his unpaid balance from every report without anyone seeing it. And sixteen
of Mohir's days had no «Ketdim» - zero pay - before anybody looked.
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
os.environ['DATABASE_PATH'] = os.path.join(tempfile.mkdtemp(), 'relink.db')

import analytics  # noqa: E402
import app  # noqa: E402
import database as db  # noqa: E402
import messages as msg  # noqa: E402
import settings  # noqa: E402
import utils  # noqa: E402

failures = []


def check(label, condition, detail=''):
    print(f"  {'PASS' if condition else 'FAIL'}  {label}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures.append(label)


class FakeMessage:
    def __init__(self, contact=None):
        self.contact = contact
        self.text = ''
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append({'text': text, **kwargs})


class FakeUser:
    def __init__(self, user_id, username=None, full_name='Someone'):
        self.id = user_id
        self.username = username
        self.full_name = full_name


class FakeContact:
    def __init__(self, user_id, phone):
        self.user_id = user_id
        self.phone_number = phone


class FakeUpdate:
    def __init__(self, user_id, contact):
        self.message = FakeMessage(contact)
        self.effective_user = FakeUser(user_id, username='mohir_new')


class FakeContext:
    def __init__(self):
        self.user_data = {}


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append({'chat_id': chat_id, 'text': text, **kwargs})


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()


class FakeQuery:
    def __init__(self, user_id, data):
        self.from_user = FakeUser(user_id)
        self.data = data
        self.answers = []
        self.edits = []

    async def answer(self, text=None):
        self.answers.append(text)

    async def edit_message_text(self, text, **kwargs):
        self.edits.append({'text': text, **kwargs})

    async def edit_message_reply_markup(self, reply_markup=None):
        self.edits.append({'text': None, 'reply_markup': reply_markup})


class FakeCallbackUpdate:
    def __init__(self, user_id, data):
        self.callback_query = FakeQuery(user_id, data)
        self.effective_user = FakeUser(user_id)


def share_contact(user_id, contact_owner, phone):
    update = FakeUpdate(user_id, FakeContact(contact_owner, phone))
    asyncio.run(app.contact_handler(update, FakeContext()))
    return update.message.replies


def press(handler, user_id, data):
    update = FakeCallbackUpdate(user_id, data)
    asyncio.run(handler(update, FakeContext()))
    return update.callback_query


def callbacks(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


OLD, NEW, STRANGER = 8516173030, 9100000001, 9100000002
IBROHIM = 6010102524
ADMIN, ADMIN2 = 1549049728, 889181741

db.init_db()
db.add_user(OLD, '998501704456', 'Mohir')
db.add_user(IBROHIM, '998900000077', 'Ibrohim')
db.add_user(ADMIN, 'AdminPhone', 'Abdulaziz Climadens', role='admin')
db.add_user(ADMIN2, 'AdminPhone', 'Odilbek', role='admin')
db.update_rates(OLD, 'per_minute', rate_per_minute=0.02136)
db.update_rates(IBROHIM, 'per_minute', rate_per_minute=0.0125)

today = utils.get_now().date()
month_start = today.replace(day=1)


def work_day(user_id, day, wage):
    start = datetime.datetime.combine(day, datetime.time(9, 0))
    db.update_attendance_manual(user_id, day, start, start.replace(hour=18), wage)


def open_day(user_id, day):
    db.check_in_user(user_id, datetime.datetime.combine(day, datetime.time(9, 40)))


work_day(OLD, month_start, 10.0)
db.add_advance(OLD, 5, 'avans', datetime.datetime.combine(month_start, datetime.time(12)))
db.create_correction_request(OLD, month_start.isoformat(), '09:00', '18:00')
open_day(OLD, today - datetime.timedelta(days=60))   # stale - admins only
open_day(OLD, today - datetime.timedelta(days=1))    # yesterday - he can still fix it
work_day(IBROHIM, month_start, 103.0)
db.add_advance(IBROHIM, 100, None, datetime.datetime.combine(month_start, datetime.time(12)))

application = app.create_application()
app.telegram_app = FakeApp()
sent = app.telegram_app.bot.sent

patterns = []
for group in application.handlers.values():
    for handler in group:
        for h in [handler] + list(getattr(handler, 'entry_points', [])):
            pattern = getattr(h, 'pattern', None)
            if pattern is not None:
                patterns.append(pattern.pattern)
for needed in ['^relink:', '^delok:']:
    check(f"зарегистрирован {needed}", needed in patterns)

print("\n1. Чужая карточка контакта ничего не даёт")
replies = share_contact(STRANGER, OLD, '+998501704456')
check("отказ: нужен свой номер", replies and replies[0]['text'] == msg.MSG_OWN_CONTACT_ONLY)
check("админам ничего не ушло", not sent)

print("\n2. Новый аккаунт на номер сотрудника — запрос админам")
replies = share_contact(NEW, NEW, '+998501704456')
check("сотруднику: запрос отправлен", replies and replies[0]['text'] == msg.MSG_RELINK_SENT)
to_admins = [m for m in sent if m['chat_id'] in (ADMIN, ADMIN2)]
check("запрос получили оба админа", len(to_admins) == 2)
check("в запросе имя и оба ID", 'Mohir' in to_admins[0]['text'] and str(OLD) in to_admins[0]['text']
      and str(NEW) in to_admins[0]['text'])
check("кнопки Ulash / Rad etish",
      callbacks(to_admins[0]['reply_markup']) == [f"relink:ok:{NEW}", f"relink:no:{NEW}"])
check("новый аккаунт ещё не сотрудник", db.get_user(NEW) is None)

sent.clear()
replies = share_contact(NEW, NEW, '998501704456')
check("повторное нажатие: «ждите», без нового спама", replies[0]['text'] == msg.MSG_RELINK_WAIT and not sent)

print("\n3. Сотрудник не может сам себя одобрить")
press(app.relink_callback, NEW, f"relink:ok:{NEW}")
check("всё ещё на старом ID", db.get_user(OLD) and db.get_user(NEW) is None)

print("\n4. Админ одобряет — вся история переезжает")
query = press(app.relink_callback, ADMIN, f"relink:ok:{NEW}")
check("старого ID больше нет", db.get_user(OLD) is None)
moved = db.get_user(NEW)
check("сотрудник на новом ID с тем же именем и номером",
      moved and moved['full_name'] == 'Mohir' and moved['phone'] == '998501704456')
check("ставка переехала", db.get_db_rates(NEW).get('rate_per_minute') == 0.02136)
entry = analytics.employee_month(NEW, today)
check("дни и аванс переехали", entry and entry['wage'] == 10.0 and entry['advance'] == 5)
check("запрос на исправление переехал",
      any(r['user_id'] == NEW for r in db.get_pending_correction_requests()))
check("сотруднику пришло приветствие с клавиатурой",
      any(m['chat_id'] == NEW and 'Mohir' in m['text'] and m.get('reply_markup') for m in sent))
check("админу показано «ulandi»", query.edits and 'ulandi' in query.edits[-1]['text'])

query = press(app.relink_callback, ADMIN2, f"relink:ok:{NEW}")
check("второй админ: уже рассмотрено", "Allaqachon ko'rib chiqilgan" in query.answers)

print("\n5. Отказ")
STRANGER2 = 9100000003
db.add_user(9100000010, '998900000088', 'Aziz')
share_contact(STRANGER2, STRANGER2, '998900000088')
sent.clear()
press(app.relink_callback, ADMIN, f"relink:no:{STRANGER2}")
check("Aziz остался на своём ID", db.get_user(9100000010) and db.get_user(STRANGER2) is None)
check("заявителю сообщили об отказе",
      any(m['chat_id'] == STRANGER2 and m['text'] == msg.MSG_NOT_AUTHORIZED for m in sent))

print("\n6. Незакрытые смены")
sent.clear()
asyncio.run(app._alert_open_shifts())
admin_msgs = [m for m in sent if m['chat_id'] in (ADMIN, ADMIN2)]
check("оба админа получили сводку", len(admin_msgs) == 2)
stale = (today - datetime.timedelta(days=60)).strftime('%d.%m.%y')
yesterday = (today - datetime.timedelta(days=1)).strftime('%d.%m.%y')
check("в сводке обе даты", stale in admin_msgs[0]['text'] and yesterday in admin_msgs[0]['text'])
to_emp = [m for m in sent if m['chat_id'] == NEW]
check("сотруднику — только вчерашний день",
      len(to_emp) == 1 and (today - datetime.timedelta(days=1)).strftime('%d.%m') in to_emp[0]['text']
      and (today - datetime.timedelta(days=60)).strftime('%d.%m') not in to_emp[0]['text'])
check("смены помечены", not db.get_unreported_open_shifts(today))
sent.clear()
settings.set_flag(app.OPEN_SHIFTS_FLAG, '')
asyncio.run(app._alert_open_shifts())
check("второй запуск никого не дёргает", not sent)
open_day(NEW, today)
check("сегодняшняя открытая смена не считается", not db.get_unreported_open_shifts(today))

query = press(app.employee_action_callback, ADMIN, f"act_att_{NEW}")
offered = callbacks(query.edits[-1]['reply_markup'])
stale_day = (today - datetime.timedelta(days=60)).isoformat()
check("админ может открыть старый незакрытый день в «📝 Vaqt»", f"edt_dt_{stale_day}" in offered,
      f"{len(offered)} кнопок")
check("и обычные 7 дней на месте", f"edt_dt_{today.isoformat()}" in offered and len(offered) == 8)

print("\n7. Удаление: сначала подтверждение с остатком")
sent.clear()
query = press(app.handle_callback_query, ADMIN, f"del_{IBROHIM}")
check("ещё не удалён", db.get_user(IBROHIM) is not None)
card = query.edits[-1]
check("в карточке заработок, аванс и остаток",
      '103' in card['text'] and '100' in card['text'] and 'Qoldiq' in card['text'])
check("кнопки «Ha» и «Yo'q»", callbacks(card['reply_markup']) == [f"delok:{IBROHIM}", f"edit_{IBROHIM}"])

press(app.handle_callback_query, IBROHIM, f"del_{IBROHIM}")
press(app.delete_confirm_callback, IBROHIM, f"delok:{IBROHIM}")
check("сотрудник не может удалить сам себя", db.get_user(IBROHIM) is not None)

query = press(app.delete_confirm_callback, ADMIN, f"delok:{IBROHIM}")
check("удалён", db.get_user(IBROHIM) is None)
check("удалившему показан остаток", query.edits and 'Qoldiq' in query.edits[-1]['text'])
notices = [m for m in sent if m['chat_id'] == ADMIN2]
check("второму админу пришло уведомление с остатком",
      notices and 'Ibrohim' in notices[0]['text'] and 'Qoldiq' in notices[0]['text']
      and 'Abdulaziz Climadens' in notices[0]['text'])
check("удалившему отдельное уведомление не шлётся", not any(m['chat_id'] == ADMIN for m in sent))

print()
if failures:
    print(f"ПРОВАЛЕНО: {len(failures)}")
    sys.exit(1)
print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
