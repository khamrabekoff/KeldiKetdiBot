# 🔄 Миграция данных со старого бота

Если у вас уже есть рабочий бот со своими данными, используйте эту инструкцию чтобы перенести данные на новый бот.

## 📋 Что переносится

✅ **Переносятся:**
- Все сотрудники (users)
- Все информация о ставках (rates)
- История посещаемости (attendance)
- Все заявки на исправление (correction_requests)
- Все настройки (settings)

❌ **НЕ переносится:**
- Состояние conversations (ConversationHandler) - нормально
- Admin токены BotFather - они не нужны

---

## Способ 1: Копирование БД (РЕКОМЕНДУЕТСЯ)

### Шаг 1: На старом боте (PythonAnywhere)

1. Откройте **Files** на PythonAnywhere
2. Найдите файл `keldi_ketdi.db`
3. Нажмите на него и скачайте его на локальную машину

### Шаг 2: На новом боте (PythonAnywhere)

1. Откройте **Files** на PythonAnywhere
2. Перейдите в папку `/home/your-username/bot_v2/`
3. Удалите старый `keldi_ketdi.db` (если он есть)
4. Нажмите **Upload a file**
5. Выберите скачанный `keldi_ketdi.db` со старого бота
6. Загрузите его

### Шаг 3: Проверить миграцию

1. Откройте **Bash console** на PythonAnywhere
2. Выполните:

```bash
cd /home/your-username/bot_v2

# Проверить что данные загрузились
python << 'EOF'
import database

conn = database.get_connection()
c = conn.cursor()

# Считать количество пользователей
c.execute("SELECT COUNT(*) as cnt FROM users")
users_count = c.fetchone()['cnt']

# Считать количество посещаемости
c.execute("SELECT COUNT(*) as cnt FROM attendance")
attendance_count = c.fetchone()['cnt']

conn.close()

print(f"✅ Пользователи: {users_count}")
print(f"✅ Записи посещаемости: {attendance_count}")

if users_count > 0 and attendance_count > 0:
    print("\n✅ Миграция успешна!")
else:
    print("\n⚠️  Проверьте что БД загружена правильно")
EOF
```

4. Перезагрузите веб-приложение на PythonAnywhere

---

## Способ 2: Экспорт/Импорт через SQL

Используйте этот способ если прямое копирование не работает.

### Шаг 1: Экспортировать старую БД

1. На старом боте откройте **Bash console**
2. Выполните:

```bash
cd /home/your-username

# Экспортировать БД в SQL
sqlite3 keldi_ketdi.db .dump > db_backup.sql

# Проверить что файл создался
ls -lh db_backup.sql
```

3. Скачайте `db_backup.sql` файл через **Files**

### Шаг 2: Импортировать в новую БД

1. На новом боте откройте **Bash console**
2. Выполните:

```bash
cd /home/your-username/bot_v2

# Загрузить SQL дамп в новую БД
sqlite3 keldi_ketdi.db < /path/to/db_backup.sql

# Проверить
python -c "import database; database.init_db(); print('✅ DB imported')"
```

---

## Способ 3: Вручную через скрипт

Если нужна более гибкая миграция (например, изменить ID администратора).

### Создать скрипт миграции

1. Создайте файл `migrate.py` в папке bot_v2:

```python
#!/usr/bin/env python3
"""Migrate data from old bot database to new one"""
import sqlite3

def migrate_users(old_db_path, new_db_path):
    """Copy all users from old DB to new DB"""
    old_conn = sqlite3.connect(old_db_path)
    new_conn = sqlite3.connect(new_db_path)
    
    old_conn.row_factory = sqlite3.Row
    old_c = old_conn.cursor()
    new_c = new_conn.cursor()
    
    # Copy users
    old_c.execute("SELECT * FROM users")
    users = old_c.fetchall()
    for user in users:
        new_c.execute(
            "INSERT OR REPLACE INTO users (id, phone, full_name, role, is_active) VALUES (?, ?, ?, ?, ?)",
            (user['id'], user['phone'], user['full_name'], user['role'], user['is_active'])
        )
    
    # Copy rates
    old_c.execute("SELECT * FROM rates")
    rates = old_c.fetchall()
    for rate in rates:
        new_c.execute(
            """INSERT OR REPLACE INTO rates 
               (user_id, salary_type, rate_n, rate_m, rate_k, rate_overtime, 
                monthly_salary, overtime_hourly_rate, rate_per_minute) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (rate['user_id'], rate['salary_type'], rate['rate_n'], rate['rate_m'], 
             rate['rate_k'], rate['rate_overtime'], rate['monthly_salary'], 
             rate['overtime_hourly_rate'], rate['rate_per_minute'])
        )
    
    # Copy attendance
    old_c.execute("SELECT * FROM attendance")
    attendance = old_c.fetchall()
    for att in attendance:
        new_c.execute(
            """INSERT OR REPLACE INTO attendance 
               (id, user_id, date, check_in, check_out, total_wage) 
               VALUES (?, ?, ?, ?, ?, ?)""",
            (att['id'], att['user_id'], att['date'], att['check_in'], 
             att['check_out'], att['total_wage'])
        )
    
    new_conn.commit()
    old_conn.close()
    new_conn.close()
    
    print("✅ Migration completed!")

if __name__ == '__main__':
    import sys
    if len(sys.argv) != 3:
        print("Usage: python migrate.py <old_db_path> <new_db_path>")
        sys.exit(1)
    
    migrate_users(sys.argv[1], sys.argv[2])
```

2. На PythonAnywhere выполните:

```bash
cd /home/your-username/bot_v2

# Выполнить миграцию
python migrate.py /path/to/old/keldi_ketdi.db ./keldi_ketdi.db

# Проверить
python << 'EOF'
import database
conn = database.get_connection()
c = conn.cursor()
c.execute("SELECT COUNT(*) as cnt FROM users")
print(f"Users: {c.fetchone()['cnt']}")
conn.close()
EOF
```

---

## ⚠️ Перед миграцией

- [ ] Убедитесь что у вас есть бэкап старой БД
- [ ] Остановите старый бот (if possible) чтобы избежать конфликтов
- [ ] Проверьте что новый бот запущен с пустой БД
- [ ] Используйте способ 1 если просто копировать БД

## 🔍 Проверка после миграции

После миграции выполните эти тесты:

```bash
cd /home/your-username/bot_v2

python << 'EOF'
import database

conn = database.get_connection()
c = conn.cursor()

# Список администраторов
print("=== АДМИНИСТРАТОРЫ ===")
c.execute("SELECT id, full_name FROM users WHERE role='admin'")
for row in c.fetchall():
    print(f"  - {row['full_name']} (ID: {row['id']})")

# Список сотрудников
print("\n=== СОТРУДНИКИ ===")
c.execute("SELECT COUNT(*) as cnt FROM users WHERE role='employee'")
print(f"  Всего: {c.fetchone()['cnt']}")

# Статистика посещаемости
print("\n=== ПОСЕЩАЕМОСТЬ ===")
c.execute("SELECT COUNT(*) as cnt FROM attendance")
print(f"  Записей: {c.fetchone()['cnt']}")

c.execute("SELECT DATE(MAX(date)) as last_date FROM attendance")
last_date = c.fetchone()['last_date']
print(f"  Последняя запись: {last_date}")

# Проверить типы зарплаты
print("\n=== ТИПЫ ЗАРПЛАТЫ ===")
c.execute("SELECT DISTINCT salary_type, COUNT(*) as cnt FROM rates GROUP BY salary_type")
for row in c.fetchall():
    print(f"  - {row['salary_type']}: {row['cnt']} сотрудников")

conn.close()
EOF
```

---

## 🚨 Если что-то пошло не так

### Восстановить из бэкапа

```bash
cd /home/your-username/bot_v2

# Удалить новую БД
rm keldi_ketdi.db

# Загрузить старую БД снова
# (скопировать файл через File Manager)

# Перезагрузить приложение
```

### Проверить целостность БД

```bash
cd /home/your-username/bot_v2

# Проверить что БД не повреждена
python << 'EOF'
import sqlite3
import os

db_path = 'keldi_ketdi.db'

# Проверить что файл существует
if not os.path.exists(db_path):
    print("❌ БД файл не найден")
    exit(1)

# Проверить размер
size = os.path.getsize(db_path)
print(f"✅ Размер БД: {size} bytes")

# Проверить целостность
try:
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    count = c.fetchone()[0]
    conn.close()
    print(f"✅ БД целостна, {count} пользователей")
except Exception as e:
    print(f"❌ Ошибка БД: {e}")
EOF
```

---

## ✅ Готово!

После миграции:
1. Перезагрузите веб-приложение на PythonAnywhere
2. Тестируйте все функции (приход, уход, отчёты)
3. Проверьте что все администраторы могут войти
4. Убедитесь что история данных загружена

**Советы:**
- Сохраняйте бэкапы регулярно
- Используйте способ 1 для простоты
- Тестируйте миграцию на копии БД сначала

---

**Happy migrating! 🚀**
