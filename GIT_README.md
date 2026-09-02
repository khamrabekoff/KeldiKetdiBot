# 🤖 Keldi-Ketdi Bot v5.1

**Telegram Bot для отслеживания посещаемости и расчёта зарплаты**

![Version](https://img.shields.io/badge/version-5.1-blue)
![Python](https://img.shields.io/badge/python-3.9+-green)
![PythonAnywhere](https://img.shields.io/badge/platform-PythonAnywhere-orange)
![License](https://img.shields.io/badge/license-MIT-green)

---

## ✨ Особенности

- 📊 **Аналитика** - статистика по сотрудникам в реальном времени
- 💰 **Поминутная зарплата** - точный расчёт каждой минуты работы
- ⚡ **Быстрые команды** - `/in`, `/out`, `/stats`
- 📈 **Excel отчёты** - с графиками и таблицами
- 📄 **PDF отчёты** - готовые к печати
- 📝 **Логирование** - все действия администратора записываются
- 🚀 **Оптимизирован** - работает на бесплатном PythonAnywhere
- 🔒 **Безопасен** - все токены в .env

---

## 🚀 Быстрый старт

### Требования
- Python 3.9+
- PythonAnywhere аккаунт
- Telegram Bot Token (от @BotFather)

### Установка (на PythonAnywhere)

```bash
# Клонируй репозиторий
git clone https://github.com/YOUR-USERNAME/bot_v2.git bot_v2
cd bot_v2

# Запусти установку
chmod +x install.sh
./install.sh

# Отредактируй конфиг
nano .env

# Установи webhook
python set_webhook.py

# Перезагрузи Web App на PythonAnywhere
```

### Локальное тестирование

```bash
pip install -r requirements.txt
python run_local.py
```

---

## 📋 Команды

### Для сотрудников
- `/start` - начать работу
- `/in` - быстро отметить приход
- `/out` - быстро отметить уход
- `/stats` - посмотреть мой счёт
- `/today` - отчет за сегодня
- `/month` - отчет за месяц

### Для администратора
- `/admin admin2026` - стать администратором
- `/analytics` - статистика по всем
- `/employee_stats Иван` - статистика по одному
- `/export_excel` - выгрузить Excel
- `/export_pdf` - выгрузить PDF

---

## 🏗️ Архитектура

```
bot_v2/
├── app.py                 # Flask + Telegram handlers
├── config.py              # Конфигурация
├── database.py            # SQLite работа
├── utils.py               # Утилиты (расчет зарплаты)
├── messages.py            # Узбекские сообщения
├── analytics.py           # Аналитика
├── audit.py               # Логирование
├── excel_export.py        # Excel отчеты
├── pdf_export.py          # PDF отчеты
├── set_webhook.py         # Установка webhook
├── install.sh             # Автоматическая установка
├── run_local.py           # Локальный запуск
├── requirements.txt       # Зависимости
└── keldi_ketdi.db         # SQLite БД
```

---

## ⚙️ Конфигурация

Создай `.env` файл на основе `.env.example`:

```env
BOT_TOKEN=123456789:AAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
WEBHOOK_DOMAIN=your-username.pythonanywhere.com
WEBHOOK_URL=https://your-username.pythonanywhere.com/webhook
ADMIN_SECRET=admin2026
DATABASE_PATH=/home/your-username/keldi_ketdi.db
FLASK_PORT=5000
```

---

## 📱 Использование

### Администратор видит статистику:
```
/analytics

📊 ОБЩАЯ СТАТИСТИКА (30 дней)

👥 Всего сотрудников: 3
💰 Всего зарплата: $450.50
⏰ Всего часов: 125.5h

═══ РЕЙТИНГ ПО ЗАРПЛАТЕ ═══
1. Иван: $200.00
2. Мария: $150.00
3. Петр: $100.50
```

### Сотрудник видит свой счёт:
```
/stats

📊 Sizning hisobingiz (Bu oy):

📅 Ishlangan kunlar: 20
💰 Jami ish haqi: $150.50
```

---

## 🔄 Обновление

```bash
cd /home/your-username/bot_v2
git pull
pip install -r requirements.txt
# Reload Web App
```

---

## 🐛 Решение проблем

### Бот не отвечает
```bash
# Проверь webhook
python set_webhook.py

# Посмотри логи
tail -f /var/log/your-username.pythonanywhere.com.error.log
```

### Ошибка БД
```bash
# Переинициализируй БД
python -c "import database; database.init_db()"
```

### Модули не загружаются
```bash
# Переустанови зависимости
pip install -r requirements.txt --force-reinstall
```

---

## 📚 Документация

- [GIT_SETUP.md](GIT_SETUP.md) - подробнее про Git
- [SETUP.md](SETUP.md) - полная инструкция деплоя
- [FEATURES_ADDED.md](FEATURES_ADDED.md) - что нового в v5.1
- [QUICK_START.md](QUICK_START.md) - быстрый старт

---

## 🛠️ Технические детали

- **Framework:** python-telegram-bot, Flask
- **Database:** SQLite3
- **Server:** PythonAnywhere (Webhook)
- **Reports:** Excel (openpyxl), PDF (reportlab)

---

## 📊 Производительность

- ⚡ Время ответа: < 100ms
- 🔄 Параллельная обработка
- 💾 Кэширование данных
- 🗄️ Оптимизированные SQL запросы
- ✅ **Работает на бесплатном тарифе PythonAnywhere**

---

## 📝 Лицензия

MIT License - смотри LICENSE файл

---

## 👨‍💻 Автор

**Odilbek** - odilbek532@gmail.com

---

## 🤝 Поддержка

Если нашёл проблему:
1. Проверь документацию
2. Посмотри логи
3. Откройте Issue на GitHub

---

## 🎯 Версии

### v5.1 (Текущая)
- ✅ Аналитика
- ✅ Excel/PDF отчеты
- ✅ Логирование
- ✅ Оптимизировано для бесплатного тарифа

### v5.0
- Webhook вместо polling
- Flask сервер
- Безопасность

### v4.0
- Многоязычность
- Разные типы зарплаты
- Исправления

---

**Made with ❤️ for attendance tracking** 🎉
