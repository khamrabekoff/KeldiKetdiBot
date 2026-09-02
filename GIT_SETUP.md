# 🎯 GIT РЕПОЗИТОРИЙ - ИНСТРУКЦИЯ

Этот бот готов к использованию с Git! Это значит:
- ✅ Легко обновляться (`git pull`)
- ✅ История всех изменений
- ✅ Можешь откатываться на старые версии
- ✅ Если что-то сломается - восстановишь

---

## 🚀 БЫСТРЫЙ СТАРТ (5 минут)

### На PythonAnywhere в Bash Console:

```bash
# 1. Перейди в домашнюю папку
cd /home/your-username

# 2. Если уже есть старая папка bot - удали/переименуй
# rm -rf bot_v2
# или
# mv bot_v2 bot_v2_old

# 3. Клонируй репозиторий (ЗАМЕНИ ВСЕ your-xxx НА СВОИ ЗНАЧЕНИЯ)
git clone https://github.com/YOUR-USERNAME/bot_v2.git bot_v2

# 4. Перейди в папку
cd bot_v2

# 5. Запусти установку
chmod +x install.sh
./install.sh

# 6. Отредактируй .env (если нужно)
nano .env
# Замени: your-username на твой username
# Ctrl+O → Enter → Ctrl+X

# 7. Установи webhook
python set_webhook.py

# 8. Готово! Перезагрузи Web App на PythonAnywhere
```

---

## 📋 ВСЕ КОМАНДЫ

### Первая установка:
```bash
cd /home/your-username
git clone https://github.com/YOUR-USERNAME/bot_v2.git bot_v2
cd bot_v2
chmod +x install.sh
./install.sh
```

### Обновиться на новую версию:
```bash
cd /home/your-username/bot_v2
git pull
pip install -r requirements.txt
# Reload на PythonAnywhere
```

### Если что-то сломалось - откатись:
```bash
cd /home/your-username/bot_v2
git log --oneline  # Смотрю историю
git revert COMMIT_HASH  # Откатываюсь
```

### Посмотреть текущий статус:
```bash
cd /home/your-username/bot_v2
git status
git log --oneline -5
```

---

## 🔧 СОЗДАНИЕ РЕПОЗИТОРИЯ

Если репозитория ещё нет, нужно его создать. Двигаюсь:

### Шаг 1: Создай репозиторий на GitHub

1. Открой https://github.com/new
2. Назови: `bot_v2`
3. Описание: `Telegram Bot for Attendance Tracking`
4. Выбери: Public или Private
5. Нажми: "Create repository"
6. НЕ добавляй README, .gitignore, LICENSE (мы их уже создали)

### Шаг 2: Локально подготовь папку

На компьютере (в папке bot_v2):

```bash
# Инициализируй git
git init

# Добавь все файлы
git add .

# Коммит
git commit -m "Initial commit: Keldi-Ketdi Bot v5.1"

# Добавь remote (замени USERNAME и REPO на свои)
git remote add origin https://github.com/YOUR-USERNAME/bot_v2.git

# Отправь на GitHub
git branch -M main
git push -u origin main
```

### Шаг 3: На PythonAnywhere клонируй

```bash
cd /home/your-username
git clone https://github.com/YOUR-USERNAME/bot_v2.git bot_v2
cd bot_v2
./install.sh
```

---

## 📝 ОБНОВЛЕНИЯ

Когда выходит новая версия:

```bash
cd /home/your-username/bot_v2
git pull  # Скачиваешь обновления
pip install -r requirements.txt  # Если новые зависимости
# Reload Web App
```

---

## 🔐 БЕЗОПАСНОСТЬ

### .env НЕ коммитится! ✅
```
# .gitignore уже содержит:
.env
.env.local
```

### Если случайно закоммитил пароль:
```bash
# Удали из истории
git rm --cached .env
git commit --amend

# Измени пароль в Telegram BotFather!
/revoke
/newbot
```

---

## 🎯 РАБОЧИЙ ПРОЦЕСС

### Локально на компьютере:
```bash
# Изменил файл app.py
git status  # Вижу что изменилось
git diff app.py  # Вижу конкретные изменения

# Закоммитил
git add app.py
git commit -m "Fix: slow analytics query"

# Отправил на GitHub
git push
```

### На PythonAnywhere:
```bash
cd /home/your-username/bot_v2
git pull  # Скачал изменения
pip install -r requirements.txt
# Reload Web App
```

---

## 💡 ПОЛЕЗНЫЕ КОМАНДЫ

```bash
# История коммитов
git log --oneline -10

# Кто что написал
git blame app.py

# Разница между версиями
git diff v1.0 v2.0

# Теги (версии)
git tag v5.1
git push --tags

# Отменить последний коммит (осторожно!)
git reset --soft HEAD~1
```

---

## 🆘 ЕСЛИ ЧТО-ТО СЛОМАЛОСЬ

### Вернуться на версию назад:
```bash
git log --oneline  # Найди хороший коммит
git checkout COMMIT_HASH  # Вернись на него
git checkout main  # Или вернись обратно в main
```

### Очистить все изменения:
```bash
git reset --hard HEAD  # ВНИМАНИЕ: потеряются все локальные изменения!
```

### Посмотреть что было изменено:
```bash
git diff HEAD~1  # Разница с предыдущим коммитом
git show COMMIT_HASH  # Показать конкретный коммит
```

---

## 📞 ПОМОЩЬ

Если git выдаёт ошибку:

```bash
# Проверь статус
git status

# Если проблемы с fetch
git fetch origin

# Если ошибка merge - просто pull с rebase
git pull --rebase

# Очистить кэш
git gc
```

---

## 🎉 ГОТОВО!

Теперь:
- ✅ Бот в Git репозитории
- ✅ Легко обновляться
- ✅ История всех изменений
- ✅ Можешь делиться с другими
- ✅ Резервные копии на GitHub

**Начни отсюда:** `./install.sh`
