"""Full month with overtime: does the split reach every report?"""
import calendar
import datetime
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The Windows console is not UTF-8 by default and the reports carry emoji
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

os.environ['BOT_TOKEN'] = '123456:AAHtesttokenAAHtesttokenAAHtesttoken'
os.environ['ADMIN_SECRET'] = 'test_secret'
os.environ['DATABASE_PATH'] = os.path.join(tempfile.mkdtemp(), 'reports.db')

import analytics  # noqa: E402
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


def close(a, b, tol=1.0):
    return abs(a - b) <= tol


SALARY = 5_000_000
YEAR, MONTH = 2026, 9
EMP = 555

db.init_db()
db.add_user(EMP, '998900000002', 'Alisher Karimov')
db.update_rates(EMP, 'monthly', monthly_salary=SALARY)
db.add_holiday(datetime.date(YEAR, MONTH, 8), 'Bayram', 1)
db.add_holiday(datetime.date(YEAR, MONTH, 9), 'Bayram', 1)

working_days = workdays.working_days_in_month(YEAR, MONTH)
rate = workdays.base_rate_per_minute(SALARY, workdays.month_context(datetime.date(YEAR, MONTH, 7)))
print(f"Сентябрь 2026: {working_days} рабочих дней, ставка {rate:,.4f}/мин\n")

# Отрабатывает каждый рабочий день 09:00-18:00; в пяти из них сидит до 20:00.
overtime_days = 0
rates = db.get_db_rates(EMP)
for day_number in range(1, calendar.monthrange(YEAR, MONTH)[1] + 1):
    day = datetime.date(YEAR, MONTH, day_number)
    if workdays.is_rest_day(day):
        continue
    check_in = datetime.datetime(YEAR, MONTH, day_number, 9, 0)
    if overtime_days < 5:
        check_out = datetime.datetime(YEAR, MONTH, day_number, 20, 0)
        overtime_days += 1
    else:
        check_out = datetime.datetime(YEAR, MONTH, day_number, 18, 0)
    wage, _, breakdown = utils.calculate_wage(check_in, check_out, rates)
    db.update_attendance_manual(EMP, day, check_in, check_out, wage, breakdown)

expected_overtime = 5 * 120 * rate
expected_total = SALARY + expected_overtime
print(f"Ожидаем: оклад {SALARY:,.2f} + переработка {expected_overtime:,.2f} = {expected_total:,.2f}\n")

print("1. Хранение разбивки в базе")
rows = db.get_user_month_details(EMP, datetime.date(YEAR, MONTH, 1))
stored_total = sum(r['total_wage'] or 0 for r in rows)
stored_base = sum(r['base_wage'] or 0 for r in rows)
stored_overtime = sum(r['overtime_wage'] or 0 for r in rows)
check("итог за месяц сходится", close(stored_total, expected_total), f"{stored_total:,.2f}")
check("база равна окладу", close(stored_base, SALARY), f"{stored_base:,.2f}")
check("переработка посчитана", close(stored_overtime, expected_overtime), f"{stored_overtime:,.2f}")
check("база + переработка = итог", close(stored_base + stored_overtime, stored_total, 0.01))

print("\n2. Карточка сотрудника (её видит сам сотрудник)")
card = ui.employee_stats_card(EMP)
check("показывает отработанные дни из рабочих", f"<b>{working_days}</b> / {working_days}" in card)
check("есть строка 'Asosiy'", 'Asosiy' in card)
check("есть строка 'Qo\\'shimcha'", "Qo'shimcha" in card)
check("есть итог 'Jami'", 'Jami' in card)
print("     " + card.replace('\n', '\n     ')[:700])

print("\n3. Карточка админа по сотруднику")
admin_card = ui.admin_employee_card(EMP)
check("разбивка видна админу", 'Asosiy' in admin_card and "Qo'shim" in admin_card)
check("дни показаны как X / Y", f"{working_days} / {working_days}" in admin_card)

print("\n4. Месячный отчёт админа")
report = ui.admin_month_report_card(datetime.date(YEAR, MONTH, 1))
check("в отчёте есть подпись 'qo\\'shimcha'", "qo'shimcha" in report)
check("есть общий итог по бонусам", "Qo'shimcha:" in report)
check("есть JAMI", 'JAMI' in report)
print("     " + report.replace('\n', '\n     ')[:600])

print("\n5. Аналитика и PDF")
stats = analytics.get_employee_stats(EMP, days=40)
check("total_base есть в статистике", close(stats['total_base'], SALARY), f"{stats['total_base']:,.2f}")
check("total_overtime есть в статистике", close(stats['total_overtime'], expected_overtime),
      f"{stats['total_overtime']:,.2f}")

print("\n6. Кнопка автоставки")
prompt, keyboard = app._overtime_rate_prompt(SALARY)
buttons = [button.text for row in keyboard.keyboard for button in row]
check("кнопка на клавиатуре", buttons and 'Avtomatik' in buttons[0], str(buttons))
check("в тексте есть посчитанная ставка", f"{rate:.4f}" in prompt)

print("\n7. Минутная ставка не сломалась")
db.add_user(556, '998900000003', 'Minutchi')
db.update_rates(556, 'per_minute', rate_per_minute=400)
check_in = datetime.datetime(YEAR, MONTH, 7, 9, 0)
check_out = datetime.datetime(YEAR, MONTH, 7, 18, 0)
pm_rates = db.get_db_rates(556)
wage, _, breakdown = utils.calculate_wage(check_in, check_out, pm_rates)
db.update_attendance_manual(556, datetime.date(YEAR, MONTH, 7), check_in, check_out, wage, breakdown)
check("минутная считает как раньше", close(wage, 540 * 400, 0.01), f"{wage:,.2f}")
pm_card = ui.employee_stats_card(556)
check("у минутной нет лишней разбивки", 'Asosiy' not in pm_card)
check("у минутной нет счётчика рабочих дней", ' / ' not in pm_card.split('Jami vaqt')[0])

print("\n" + ("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ" if not failures else f"ПАДЕНИЙ: {len(failures)} -> {failures}"))
sys.exit(0 if not failures else 1)
