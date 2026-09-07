"""Does the per-client switch actually keep pay away from employees?

The code is shared by every client, so the switch has to hide money on every
employee-facing surface at once while leaving the admin's screens alone.
"""
import asyncio
import datetime
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['BOT_TOKEN'] = '123456:AAHtesttokenAAHtesttokenAAHtesttoken'
os.environ['ADMIN_SECRET'] = 'test_secret'
os.environ['DATABASE_PATH'] = os.path.join(tempfile.mkdtemp(), 'visibility.db')

import app  # noqa: E402
import database as db  # noqa: E402
import settings  # noqa: E402
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
    def __init__(self):
        self.user_data = {}


EMP = 901
ADMIN = 902

db.init_db()
db.add_user(EMP, '998900000010', 'Sardor Umarov')
db.add_user(ADMIN, '998900000011', 'Boss', role='admin')
db.update_rates(EMP, 'per_minute', rate_per_minute=400)

now = utils.get_now()
db.check_in_user(EMP, now.replace(hour=9, minute=0, second=0, microsecond=0))


def employee_surfaces():
    """Every text an employee can reach that could carry money."""
    update = FakeUpdate(EMP)
    asyncio.run(app.employee_month_handler(update, FakeContext()))
    return {
        'holat (ishdasiz)': ui.employee_status_card(EMP, 'Sardor Umarov'),
        'hisobim': ui.employee_stats_card(EMP),
        'oylik hisobot': update.message.replies[0],
    }


print("1. По умолчанию всё как раньше — первый клиент не задет")
check("настройка включена по умолчанию", settings.get_bool('show_employee_earnings'))
for name, text in employee_surfaces().items():
    check(f"деньги видны: {name}", '$' in text, text.splitlines()[0][:40])

print("\n2. Выключаем для этого клиента")
settings.set_bool('show_employee_earnings', False)
check("настройка выключилась", not settings.get_bool('show_employee_earnings'))

for name, text in employee_surfaces().items():
    check(f"денег нет: {name}", '$' not in text and '💰' not in text)

card = ui.employee_status_card(EMP, 'Sardor Umarov')
check("время работы осталось", 'Ishlagan' in card)
check("статус остался", 'ISHDASIZ' in card)

print("\n3. Карточка после ухода")
db.check_out_user(EMP, now.replace(hour=18, minute=0, second=0, microsecond=0))
card = ui.employee_status_card(EMP, 'Sardor Umarov')
check("денег нет после ухода", '$' not in card and '💰' not in card)
check("время прихода и ухода на месте", 'Kelish' in card and 'Ketish' in card)

stats = ui.employee_stats_card(EMP)
check("в hisobim нет сумм", '$' not in stats)
check("в hisobim остались дни и часы", 'Ishlangan kunlar' in stats and 'Jami vaqt' in stats)
print("     " + stats.split('So\'nggi')[0].replace('\n', '\n     '))

print("\n4. Админ по-прежнему видит деньги")
admin_card = ui.admin_employee_card(EMP)
check("админу суммы видны", '$' in admin_card)
report = ui.admin_month_report_card(now.replace(day=1).date())
check("в отчёте админа суммы видны", '$' in report)

print("\n5. Переключатель в панели настроек")
text, keyboard = ui.settings_card()
callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]
check("кнопка переключателя есть", 'flag:show_employee_earnings' in callbacks)
check("состояние показано в тексте", "Yo'q" in text)

application = app.create_application()
patterns = []
for group in application.handlers.values():
    for handler in group:
        pattern = getattr(handler, 'pattern', None)
        if pattern is not None:
            patterns.append(pattern.pattern)
check("обработчик переключателя зарегистрирован", '^flag:' in patterns)

print("\n6. Включаем обратно — деньги возвращаются")
settings.set_bool('show_employee_earnings', True)
check("суммы вернулись", '$' in ui.employee_stats_card(EMP))

print("\n" + ("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ" if not failures else f"ПАДЕНИЙ: {len(failures)} -> {failures}"))
sys.exit(0 if not failures else 1)
