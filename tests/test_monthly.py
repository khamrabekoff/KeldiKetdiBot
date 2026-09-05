import datetime, os, sys, tempfile

os.environ['BOT_TOKEN'] = 'test:token'
os.environ['ADMIN_SECRET'] = 'test_secret'
os.environ['DATABASE_PATH'] = os.path.join(tempfile.mkdtemp(), 'test.db')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database as db, workdays, utils

db.init_db()

SALARY = 5_000_000
rates = {'salary_type': 'monthly', 'monthly_salary': SALARY, 'overtime_per_minute': 0}

def dt(day, h, m=0):
    return datetime.datetime(2026, 9, day, h, m)

def wage(day, h1, m1, h2, m2, r=rates):
    w, details, _ = utils.calculate_wage(dt(day, h1, m1), dt(day, h2, m2), r)
    return w, details

ok = True
def check(label, got, want, tol=0.02):
    global ok
    good = abs(got - want) <= tol
    ok = ok and good
    print(f"  {'PASS' if good else 'FAIL'}  {label}: {got:,.2f} (ожидалось {want:,.2f})")

# --- Сентябрь 2026: 30 дней, воскресенья 6/13/20/27 ---
print("Сентябрь 2026 без праздников: рабочих дней =", workdays.working_days_in_month(2026, 9))
db.add_holiday(datetime.date(2026, 9, 8), 'Mustaqillik kuni', 1)
db.add_holiday(datetime.date(2026, 9, 9), 'Bayram', 1)
wd = workdays.working_days_in_month(2026, 9)
print("После двух официальных выходных: рабочих дней =", wd)
check("пример клиента (30 - 4 вс - 2 празд)", wd, 24)

ctx = workdays.month_context(datetime.date(2026, 9, 7))
rate = workdays.base_rate_per_minute(SALARY, ctx)
print(f"\nСтавка: {rate:,.4f} за минуту, стандартный день {ctx['standard_minutes']} мин\n")

print("Обычный рабочий день (понедельник 7 сентября):")
w, d = wage(7, 9, 0, 18, 0); check("ровно 09:00-18:00 = оклад/24", w, SALARY / 24); print(f"        details: {d}")
check("24 таких дня = полный оклад", w * 24, SALARY, tol=0.5)

w, d = wage(7, 9, 30, 18, 0); check("пришёл в 09:30 (-30 мин)", w, 510 * rate); print(f"        details: {d}")
w, d = wage(7, 9, 0, 17, 0);  check("ушёл в 17:00 (-60 мин)", w, 480 * rate); print(f"        details: {d}")
w, d = wage(7, 8, 30, 18, 30); check("08:30-18:30 (+60 мин)", w, 600 * rate); print(f"        details: {d}")
w, d = wage(7, 8, 30, 17, 0);  check("08:30-17:00 (+30 -60)", w, 510 * rate); print(f"        details: {d}")

print("\nВыходные:")
w, d = wage(6, 10, 0, 14, 0); check("воскресенье 10:00-14:00", w, 240 * rate); print(f"        details: {d}")
w, d = wage(8, 10, 0, 14, 0); check("праздник 10:00-14:00", w, 240 * rate); print(f"        details: {d}")

print("\nОтдельная ставка переработки (админ задал 1000/мин):")
custom = dict(rates, overtime_per_minute=1000)
w, d = wage(7, 8, 0, 18, 0, custom); check("08:00-18:00, переработка по 1000", w, 540 * rate + 60 * 1000)
print(f"        details: {d}")

print("\nПересчёт месяца при добавлении праздника задним числом:")
db.add_user(777, '998900000000', 'Test Xodim')
db.update_rates(777, 'monthly', monthly_salary=SALARY)
db.check_in_user(777, dt(7, 9, 0))
conn = db.get_connection()
conn.execute("UPDATE attendance SET date = ?, check_in = ? WHERE user_id = 777", (datetime.date(2026, 9, 7), dt(7, 9, 0)))
conn.commit(); conn.close()
res = db.check_out_user(777, dt(7, 18, 0))
stored_before = db.get_user_month_wage(777, datetime.date(2026, 9, 1))
check("день записан по 24 рабочим дням", stored_before, SALARY / 24)

db.add_holiday(datetime.date(2026, 9, 10), 'Yangi bayram', 1)
changed = db.recalculate_month_wages(2026, 9)
stored_after = db.get_user_month_wage(777, datetime.date(2026, 9, 1))
print(f"  пересчитано строк: {changed}, рабочих дней теперь: {workdays.working_days_in_month(2026, 9)}")
check("день подорожал до оклад/23", stored_after, SALARY / 23)

print("\n" + ("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ" if ok else "ЕСТЬ ПАДЕНИЯ"))
sys.exit(0 if ok else 1)
