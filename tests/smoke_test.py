"""End-to-end smoke test: build the real bot app and drive the holiday flows."""
import asyncio
import datetime
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The Windows console is not UTF-8 by default and the screens carry emoji
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

os.environ['BOT_TOKEN'] = '123456:AAHtesttokenAAHtesttokenAAHtesttoken'
os.environ['ADMIN_SECRET'] = 'test_secret'
os.environ['DATABASE_PATH'] = os.path.join(tempfile.mkdtemp(), 'smoke.db')

import app  # noqa: E402
import database as db  # noqa: E402
import ui  # noqa: E402
import utils  # noqa: E402
import workdays  # noqa: E402

failures = []


def check(label, condition, detail=''):
    print(f"  {'PASS' if condition else 'FAIL'}  {label}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures.append(label)


print("1. Сборка приложения и регистрация обработчиков")
db.init_db()
application = app.create_application()
check("create_application() отработал", application is not None)

patterns = []
for group in application.handlers.values():
    for handler in group:
        pattern = getattr(handler, 'pattern', None)
        if pattern is not None:
            patterns.append(pattern.pattern)
        for state_handlers in getattr(handler, 'states', {}).values():
            for inner in state_handlers:
                inner_pattern = getattr(inner, 'pattern', None)
                if inner_pattern is not None:
                    patterns.append(inner_pattern.pattern)
        for entry in getattr(handler, 'entry_points', []):
            entry_pattern = getattr(entry, 'pattern', None)
            if entry_pattern is not None:
                patterns.append(entry_pattern.pattern)

for needed in ['^hol:open$', '^hol:m:', '^hol:del:', '^hol:add:', '^pdel:']:
    check(f"зарегистрирован {needed}", needed in patterns)

print("\n2. Карточка настроек ведёт на праздники")
text, keyboard = ui.settings_card()
callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]
check("кнопка 'Rasmiy dam olish kunlari' на месте", 'hol:open' in callbacks)

print("\n3. Карточка праздников за сентябрь 2026")
text, keyboard = ui.holidays_card(2026, 9)
check("считает 26 рабочих дней без праздников", 'Ish kunlari: <b>26</b>' in text, text.splitlines()[3])
callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]
check("есть кнопка добавления", 'hol:add:2026-09' in callbacks)
check("есть переход на предыдущий месяц", 'hol:m:2026-08' in callbacks)
check("есть переход на следующий месяц", 'hol:m:2026-10' in callbacks)

print("\n4. Разбор ввода админа")


class FakeMessage:
    def __init__(self, text):
        self.text = text
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


class FakeUser:
    id = 42


class FakeUpdate:
    def __init__(self, text):
        self.message = FakeMessage(text)
        self.effective_user = FakeUser()


class FakeContext:
    def __init__(self):
        self.user_data = {'holiday_month': (2026, 9)}


db.add_user(42, '998900000001', 'Admin', role='admin')

update = FakeUpdate('8, 9 | Mustaqillik kuni')
context = FakeContext()
asyncio.run(app.holidays_add_value(update, context))
check("два дня добавлены", workdays.working_days_in_month(2026, 9) == 24,
      f"рабочих дней: {workdays.working_days_in_month(2026, 9)}")
check("ответ подтверждает добавление", 'Qo' in update.message.replies[0], update.message.replies[0])
rows = db.list_holidays(2026, 9)
check("изоh сохранён", rows and rows[0]['note'] == 'Mustaqillik kuni',
      rows[0]['note'] if rows else 'нет строк')

update = FakeUpdate('8, 31, abc, 2026-10-05')
context = FakeContext()
asyncio.run(app.holidays_add_value(update, context))
reply = update.message.replies[0]
check("повтор распознан как уже добавленный", 'Allaqachon' in reply, reply.replace('\n', ' | '))
check("31 сентября отвергнут", 'Tushunarsiz' in reply and '31' in reply)
check("чужой месяц отвергнут", '2026-10-05' in reply)

print("\n5. Воскресенья не нужно вводить руками")
check("6 сентября — выходной сам по себе", workdays.is_rest_day(datetime.date(2026, 9, 6)))
check("7 сентября — рабочий", not workdays.is_rest_day(datetime.date(2026, 9, 7)))

print("\n6. Подсказка ставки переработки")
prompt, auto_keyboard = app._overtime_rate_prompt(5_000_000)
check("в подсказке 24 рабочих дня", '24 ish kuni' in prompt)
check("в подсказке 540 минут", '540 daqiqa' in prompt)
check("кнопка автоставки приложена",
      any('Avtomatik' in button.text for row in auto_keyboard.keyboard for button in row))
print("     " + prompt.replace('\n', '\n     '))

print("\n7. Напоминания молчат в выходной")


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append(chat_id)


class FakeApp:
    def __init__(self, bot):
        self.bot = bot


db.add_user(555, '998900000555', 'Xodim')

real_app, real_now = app.telegram_app, utils.get_now


def run_morning(day):
    """The morning job as it would run on `day`, with a bot that only counts."""
    bot = FakeBot()
    app.telegram_app = FakeApp(bot)
    utils.get_now = lambda: datetime.datetime.combine(day, datetime.time(8, 30))
    asyncio.run(app._send_reminders_job('morning'))
    return bot.sent


try:
    # 6 сентября 2026 — воскресенье, 8-е добавлено праздником выше,
    # 10-е — обычный четверг.
    check("в воскресенье никому не пишет", run_morning(datetime.date(2026, 9, 6)) == [])
    check("в праздник никому не пишет", run_morning(datetime.date(2026, 9, 8)) == [])
    check("в рабочий день пишет", run_morning(datetime.date(2026, 9, 10)) == [555])
finally:
    app.telegram_app, utils.get_now = real_app, real_now

print("\n8. Добавленный сотрудник виден до того, как открыл бота")
db.add_pending_user('998901112233', 'Yangi Xodim', 'monthly', monthly_salary=5_000_000)
text, keyboard = ui.admin_employee_list()
callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]
check("имя в списке", 'Yangi Xodim' in text)
check("помечен как ожидающий", 'Kutilmoqda' in text)
check("сказано, что нужно прислать номер", 'raqam' in text)
check("есть кнопка отмены приглашения", 'pdel:998901112233' in callbacks)

check("приглашение снимается", db.delete_pending_user('998901112233'))
text, _ = ui.admin_employee_list()
check("после отмены его нет", 'Yangi Xodim' not in text)

print("\n" + ("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ" if not failures else f"ПАДЕНИЙ: {len(failures)} -> {failures}"))
sys.exit(0 if not failures else 1)
