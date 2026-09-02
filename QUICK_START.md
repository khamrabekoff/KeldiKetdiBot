# ⚡ Быстрый старт (5 минут)

## Локально

### 1️⃣ Установить
```bash
pip install -r requirements.txt
cp .env.example .env
# Отредактировать .env, вставить BOT_TOKEN
```

### 2️⃣ Запустить
```bash
python run_local.py
```

### 3️⃣ Тестировать
Откройте Telegram, найдите бота, отправьте `/start`

---

## На PythonAnywhere

### 1️⃣ Новый токен
- Откройте Telegram → @BotFather
- `/revoke` → удалить старого бота
- `/newbot` → создать нового бота  
- Скопировать токен

### 2️⃣ Подготовка
```
BOT_TOKEN=<новый_токен>
WEBHOOK_DOMAIN=your-username.pythonanywhere.com
WEBHOOK_URL=https://your-username.pythonanywhere.com/webhook
ADMIN_SECRET=SuperSecretPassword123!@#
DATABASE_PATH=/home/your-username/keldi_ketdi.db
```

### 3️⃣ На PythonAnywhere
1. Web → Add a new web app → Manual → Python 3.9
2. Bash: загрузить файлы в `/home/your-username/bot_v2/`
3. Bash: `pip install -r requirements.txt`
4. Bash: `python -c "import database; database.init_db()"`
5. Web → WSGI configuration file → (смотри SETUP.md)
6. Web → Environment variables → добавить все из .env
7. Reload (зелёная кнопка)

### 4️⃣ Webhook
```bash
cd /home/your-username/bot_v2
python << 'EOF'
import requests, config
url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/setWebhook"
print(requests.post(url, data={"url": config.WEBHOOK_URL}).json())
EOF
```

### 5️⃣ Тест
- Откройте: https://your-username.pythonanywhere.com/health
- Должно показать: `{"status": "ok", "bot": "running"}`

---

## ✅ Готово!

Бот работает! 🎉

**Первый администратор:**
```
/admin <ADMIN_SECRET>
```

**Нужна помощь?** Смотрите:
- SETUP.md (полная инструкция)
- README.md (описание функций)
- CHECKLIST.md (что проверить перед деплоем)

---

## 🚨 Если не работает

1. Проверьте токен: https://api.telegram.org/bot<TOKEN>/getMe
2. Проверьте webhook: https://api.telegram.org/bot<TOKEN>/getWebhookInfo
3. Проверьте логи: Web → Log files → error.log
4. Перезагрузитесь: Web → Reload

**Частая ошибка:** Забыли установить webhook после создания приложения!
