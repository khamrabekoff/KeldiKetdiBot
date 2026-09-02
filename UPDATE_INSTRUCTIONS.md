# 🚀 ИНСТРУКЦИЯ ОБНОВЛЕНИЯ НА PYTHONYWHERE

## 📋 Что нужно сделать

Я создал 4 новых модуля с функциями. Нужно обновить на PythonAnywhere.

---

## ⚡ БЫСТРОЕ ОБНОВЛЕНИЕ (5 минут)

### Шаг 1: Загрузить новые файлы

На PythonAnywhere откройте **Files** → папка `/home/your-username/bot_v2/`

Загрузите эти новые файлы:
- ✅ `analytics.py` (аналитика)
- ✅ `audit.py` (логирование)
- ✅ `excel_export.py` (Excel отчеты)
- ✅ `pdf_export.py` (PDF отчеты)
- ✅ `FEATURES_ADDED.md` (документация)

### Шаг 2: Обновить requirements.txt

Откройте файл `requirements.txt` на PythonAnywhere и замените его на:

```
python-telegram-bot[job-queue,all]>=20.8
python-dotenv>=1.0.0
flask>=2.3.0
flask-cors>=4.0.0
pytz>=2023.3
openpyxl>=3.1.0
requests>=2.31.0
reportlab>=4.0.0
```

### Шаг 3: Установить новую зависимость

Откройте **Bash console** и выполните:

```bash
cd /home/your-username/bot_v2
source /home/your-username/.virtualenvs/bot_v2_env/bin/activate
pip install reportlab
```

### Шаг 4: Перезагрузить

Web → кнопка **Reload** (зелёная)

---

## ✅ ГОТОВО!

Все новые функции теперь доступны! 🎉

**Проверить:**
- Отправь боту `/analytics`
- Должен показать статистику

---

## 📚 НОВЫЕ КОМАНДЫ

Админ может использовать:
- `/analytics` - статистика по всем
- `/employee_stats Иван` - статистика по Ивану
- `/export_excel` - выгрузить Excel
- `/export_pdf` - выгрузить PDF

Все сотрудники:
- `/in` - быстрый приход
- `/out` - быстрый уход
- `/stats` - мой счёт

---

## 🔍 ЕСЛИ ЧТО-ТО НЕ РАБОТАЕТ

1. **Проверь логи:**
   - Web → Log files → error.log

2. **Проверь что все файлы загружены:**
   - Files → /home/your-username/bot_v2/
   - Должны быть: analytics.py, audit.py, excel_export.py, pdf_export.py

3. **Проверь что reportlab установлен:**
   ```bash
   pip list | grep reportlab
   ```

4. **Перезагрузись:**
   - Web → Reload

---

## 📝 ЕСЛИ ХОЧЕШЬ ДОБАВИТЬ АВТОМАТИЧЕСКИЕ НАПОМИНАНИЯ

Я создал файл `reminders.py` готовый к использованию. Напиши когда понадобится!

---

**Вопросы?** Смотри FEATURES_ADDED.md

**Готово к работе!** 🚀
