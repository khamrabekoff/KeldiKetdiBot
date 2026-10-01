"""Abandoned conversations must not lock up the main menu or the employee cards."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

os.environ['BOT_TOKEN'] = '123456:AAHtesttokenAAHtesttokenAAHtesttoken'
os.environ['ADMIN_SECRET'] = 'test_secret'
os.environ['DATABASE_PATH'] = os.path.join(tempfile.mkdtemp(), 'menu_exit.db')

from telegram import Update  # noqa: E402

import app  # noqa: E402
import database as db  # noqa: E402
import ui  # noqa: E402

failures = []


def check(label, condition, detail=''):
    print(f"  {'PASS' if condition else 'FAIL'}  {label}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures.append(label)


db.init_db()
application = app.create_application()
convs = {h.name: h for group in application.handlers.values() for h in group
         if getattr(h, 'name', None)}

USER = {'id': 42, 'is_bot': False, 'first_name': 'Admin'}
CHAT = {'id': 42, 'type': 'private'}


def text_update(text):
    return Update.de_json({'update_id': 1, 'message': {
        'message_id': 1, 'date': 0, 'chat': CHAT, 'from': USER, 'text': text}}, application.bot)


def callback_update(data):
    return Update.de_json({'update_id': 2, 'callback_query': {
        'id': '1', 'from': USER, 'chat_instance': 'x', 'data': data,
        'message': {'message_id': 1, 'date': 0, 'chat': CHAT, 'from': USER, 'text': '.'}}},
        application.bot)


def picked(conv, state, update):
    """The callback the conversation would run for this update in this state, or None."""
    conv._update_state(state, conv._get_key(update))
    result = conv.check_update(update)
    return result[2].callback if result else None


print("1. Брошенный выбор даты не блокирует карточки сотрудников")
manage = convs['manage_emp_conv']
check("тап по сотруднику открывает его карточку заново",
      picked(manage, app.EDIT_ATT_DATE, callback_update('edit_5')) is app.handle_callback_query)
check("из меню действий тоже",
      picked(manage, app.ACTION_MENU, callback_update('edit_7')) is app.handle_callback_query)

print("\n2. Кнопка меню закрывает разговор, а не идёт как ответ")
check("'Xodimlar' во время ввода времени",
      picked(manage, app.EDIT_ATT_IN, text_update(ui.BTN_ADMIN_EMPLOYEES)) is app.leave_to_menu)
check("'Xodimlar' во время выбора даты",
      picked(manage, app.EDIT_ATT_DATE, text_update(ui.BTN_ADMIN_EMPLOYEES)) is app.leave_to_menu)
check("обычный ввод времени по-прежнему принимается",
      picked(manage, app.EDIT_ATT_IN, text_update('09:00')) is app.edit_att_in_handler)

add = convs['add_emp_conv']
check("'Bugun' при вводе имени нового сотрудника",
      picked(add, app.ADD_NAME, text_update(ui.BTN_ADMIN_TODAY)) is app.leave_to_menu)
check("имя по-прежнему принимается",
      picked(add, app.ADD_NAME, text_update('Ali Valiyev')) is app.add_emp_name)

for name, conv in convs.items():
    if not conv.states:
        continue
    state = next(iter(conv.states))
    check(f"{name}: 'KETDIM' выходит из разговора",
          picked(conv, state, text_update(ui.BTN_CHECK_OUT)) is app.leave_to_menu)

print()
if failures:
    print(f"FAILED: {len(failures)}")
    sys.exit(1)
print("ALL PASSED")
