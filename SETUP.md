# 🚀 Инструкция деплоя на PythonAnywhere

## Шаг 1: Подготовка на локальной машине

### 1.1 Получить новый токен бота
1. Откройте Telegram и найдите `@BotFather`
2. Отправьте `/start`
3. Отправьте `/revoke` и выберите старого бота (чтобы отозвать старый токен)
4. Отправьте `/newbot` чтобы создать нового бота
5. Выберите имя и username
6. Скопируйте новый токен (формат: `123456789:ABCdefGHIjklMNOpqrSTUvwxYZ-1A2b3C4d5E`)

### 1.2 Подготовить переменные окружения

1. Откройте файл `.env.example` в bot_v2 папке
2. Скопируйте его в `.env`
3. Заполните значения:

```
BOT_TOKEN=<ВАШ_НОВЫЙ_ТОКЕН_ЗДЕСЬ>
WEBHOOK_DOMAIN=your-username.pythonanywhere.com
WEBHOOK_URL=https://your-username.pythonanywhere.com/webhook
ADMIN_SECRET=your_super_secret_password_min_16_chars_make_it_complex_use_numbers_and_symbols_L1k3_Th1s!
DATABASE_PATH=/home/your-username/keldi_ketdi.db
FLASK_PORT=5000
```

**Важно:**
- `your-username` - это ваш username на pythonanywhere.com
- ADMIN_SECRET должен быть минимум 16 символов, сложный
- FLASK_PORT оставьте 5000 для бесплатного аккаунта

---

## Шаг 2: На PythonAnywhere

### 2.1 Создать веб-приложение

1. Откройте https://www.pythonanywhere.com
2. Залогиньтесь в аккаунт
3. Перейдите в **Web** > **Add a new web app**
4. Выберите:
   - Manual configuration
   - Python 3.9 (или новее)
5. Нажмите Next

### 2.2 Загрузить файлы бота

**Способ 1: Через Git (РЕКОМЕНДУЕТСЯ)**

1. Откройте **Bash console** на PythonAnywhere
2. Выполните:

```bash
cd /home/your-username
git clone https://github.com/YOUR_USERNAME/your-bot-repo.git bot_v2

# ИЛИ если используешь мой код без git:
# Скопируй все файлы вручную через File Manager
```

**Способ 2: Через File Manager**

1. Откройте **Files**
2. Нажмите **Upload a file**
3. Загрузите все файлы из папки bot_v2:
   - config.py
   - database.py
   - messages.py
   - utils.py
   - app.py
   - wsgi.py
   - requirements.txt
   - .env (с заполненными значениями!)
   - keldi_ketdi.db (если хотишь перенести старую БД)

### 2.3 Установить зависимости

1. Откройте **Bash console**
2. Выполните:

```bash
cd /home/your-username/bot_v2

# Создать virtual environment
mkvirtualenv --python=/usr/bin/python3.9 bot_v2_env

# Установить зависимости
pip install -r requirements.txt

# Инициализировать БД
python -c "import database; database.init_db()"
```

### 2.4 Настроить веб-приложение

1. Откройте **Web** > выберите ваше приложение
2. В разделе **WSGI configuration file** нажмите на ссылку
3. Удалите весь содержимое и замените на:

```python
import os
import sys

# Setup path
path = '/home/your-username/bot_v2'
if path not in sys.path:
    sys.path.insert(0, path)

# Activate virtual environment
os.chdir(path)
exec(open('/home/your-username/.virtualenvs/bot_v2_env/bin/activate_this.py').read(), {'__file__': '/home/your-username/.virtualenvs/bot_v2_env/bin/activate_this.py'})

from app import app as application
```

**Убедитесь, что заменили `your-username` на ваш реальный username!**

4. Нажмите **Save**

### 2.5 Настроить virtualenv

1. В разделе **Virtualenv** выберите **/home/your-username/.virtualenvs/bot_v2_env**
2. Нажмите на папку, чтобы применить

### 2.6 Добавить переменные окружения

1. Откройте **Web** > ваше приложение > **Web app settings**
2. Прокрутите вниз до **Environment variables**
3. Нажмите **Add a new variable**
4. Добавьте все переменные из вашего .env файла:
   - `BOT_TOKEN` 
   - `WEBHOOK_DOMAIN`
   - `WEBHOOK_URL`
   - `ADMIN_SECRET`
   - `DATABASE_PATH`
   - `FLASK_PORT`

### 2.7 Перезагрузить веб-приложение

1. В верхнем правом углу нажмите кнопку **Reload** (зелёная)
2. Дождитесь "✓ Site is online"

---

## Шаг 3: Настроить Webhook в Telegram

1. Откройте **Bash console** на PythonAnywhere
2. Выполните:

```bash
cd /home/your-username/bot_v2

python << 'EOF'
import requests
import config

url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/setWebhook"
data = {"url": config.WEBHOOK_URL}

response = requests.post(url, data=data)
print(f"Webhook response: {response.json()}")

# Проверить что webhook установлен
check_url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/getWebhookInfo"
check_response = requests.get(check_url)
print(f"Webhook info: {check_response.json()}")
EOF
```

**Если видишь ошибку - проверь:**
- BOT_TOKEN правильный
- WEBHOOK_URL правильный (https://your-username.pythonanywhere.com/webhook)
- Веб-приложение на PythonAnywhere запущено

---

## Шаг 4: Тестирование

### 4.1 Проверить здоровье приложения

Откройте в браузере:
```
https://your-username.pythonanywhere.com/health
```

Должны увидеть:
```json
{"status": "ok", "bot": "running"}
```

### 4.2 Тестировать бота

1. Найдите бота в Telegram (его username)
2. Отправьте `/start`
3. Должен запросить телефон
4. Отправьте `/admin <SECRET_CODE>` чтобы стать администратором
5. Проверьте что меню работает

### 4.3 Проверить логи

Если что-то не работает:

1. Откройте **Web** > ваше приложение > **Log files**
2. Нажмите на **error.log**
3. Ищите последние ошибки

---

## Шаг 5: Обслуживание

### Резервное копирование БД

Каждый день делайте бэкап базы данных:

```bash
# В Bash console
cd /home/your-username

# Создать архив
tar -czf bot_v2_backup_$(date +%Y%m%d).tar.gz bot_v2/keldi_ketdi.db

# Скачать архив через File Manager
```

### Обновление бота

Если нужно обновить код:

1. Измените файлы (через File Manager или Git)
2. Откройте **Web** > ваше приложение
3. Нажмите **Reload**

### Мониторинг

Рекомендуется периодически:
1. Проверять логи (ошибки)
2. Проверять размер БД
3. Тестировать функциональность

---

## ⚠️ Частые ошибки

### "Webhook error: Cannot decode request data"
- Проверьте что BOT_TOKEN правильный в конфиге
- Перезагрузите веб-приложение

### "Database connection error"
- Проверьте что DATABASE_PATH правильный
- Проверьте права доступа к файлу
- БД должна находиться в папке пользователя (/home/your-username/)

### "ModuleNotFoundError: No module named 'telegram'"
- Виртуальное окружение не активировано
- Переустановите зависимости
- Перезагрузите веб-приложение

### Бот не отвечает на сообщения
- Проверьте webhook в Telegram (Step 3)
- Проверьте логи на ошибки
- Убедитесь что приложение online

### "Import errors"
- Проверьте что все файлы (config.py, database.py и т.д.) находятся в bot_v2 папке
- Перезагрузите приложение

---

## 🎉 Готово!

Ваш бот должен быть запущен и работать! 

**Проверить статус:**
- Открыть https://your-username.pythonanywhere.com/health
- Должно показать `{"status": "ok", "bot": "running"}`

**Первый администратор:**
- Откройте чат с ботом
- Отправьте `/admin <SECRET_CODE>`
- Должны увидеть сообщение "Табriklaymiz! Siz endi administratorsiz."

---

## 📞 Помощь

Если что-то не работает:
1. Проверьте логи (/Web > Log files > error.log)
2. Проверьте что все переменные окружения заполнены
3. Переустановите зависимости
4. Перезагрузите приложение

**Useful commands:**

```bash
# В Bash console

# Проверить что БД работает
python -c "import database; db = database.get_connection(); print('✅ DB OK')"

# Проверить конфиг
python -c "import config; print(f'Bot: {config.BOT_VERSION}')"

# Посмотреть какие админы в БД
python << 'EOF'
import database
conn = database.get_connection()
c = conn.cursor()
c.execute("SELECT id, full_name FROM users WHERE role='admin'")
for row in c.fetchall():
    print(f"Admin: {row['full_name']} (ID: {row['id']})")
conn.close()
EOF

# Переинициализировать БД (БУДУТ ПОТЕРЯНЫ ВСЕ ДАННЫЕ!)
python -c "import database; database.init_db(); print('✅ DB Reset')"
```

**Happy botting! 🤖**
