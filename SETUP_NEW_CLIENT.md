# Развёртывание бота новому клиенту

Код одинаковый для всех клиентов. Отличается только `.env`.
Каждому клиенту — свой аккаунт PythonAnywhere, свой бот, своя база.

Ниже `<user>` — имя нового аккаунта на PythonAnywhere. Оно же становится
доменом `<user>.pythonanywhere.com`, поэтому выбирайте осмысленное.

---

## 1. Завести бота у BotFather

`/newbot` → имя и username → получить токен.

Сразу же: `/setcommands` для бота

```
start - Boshlash
in - Keldim
out - Ketdim
stats - Mening hisobim
today - Bugungi hisobot
month - Oylik hisobot
```

## 2. Завести аккаунт PythonAnywhere

Регистрировать **на почту клиента** — хостинг должен принадлежать ему.
Бесплатный тариф (Beginner).

## 3. Сгенерировать три секрета

Каждому клиенту — свои, не переиспользовать между клиентами:

```bash
for i in 1 2 3; do tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32; echo; done
```

Первый → `ADMIN_SECRET`, второй → `CRON_SECRET`, третий → `DEPLOY_SECRET`.

## 4. Код на сервере

PythonAnywhere → **Consoles** → **Bash**:

```bash
git clone https://github.com/khamrabekoff/KeldiKetdiBot.git bot_v2
cd bot_v2
mkvirtualenv --python=/usr/bin/python3.10 bot_v2_env
pip install -r requirements.txt
```

## 5. Файл .env

В той же консоли `nano ~/bot_v2/.env`, вставить и заполнить:

```
BOT_TOKEN=токен_от_BotFather
WEBHOOK_DOMAIN=<user>.pythonanywhere.com
WEBHOOK_URL=https://<user>.pythonanywhere.com/webhook
ADMIN_SECRET=первый_секрет
CRON_SECRET=второй_секрет
DEPLOY_SECRET=третий_секрет
DATABASE_PATH=/home/<user>/keldi_ketdi.db
FLASK_PORT=5000
```

База лежит **вне** папки с кодом — чтобы `git pull` её не трогал.

## 6. Веб-приложение

**Web** → **Add a new web app** → **Manual configuration** → **Python 3.10**.

Заполнить поля:

| Поле | Значение |
|---|---|
| Source code | `/home/<user>/bot_v2` |
| Working directory | `/home/<user>/bot_v2` |
| Virtualenv | `/home/<user>/.virtualenvs/bot_v2_env` |

Открыть **WSGI configuration file**, стереть всё содержимое и вписать:

```python
import sys
path = '/home/<user>/bot_v2'
if path not in sys.path:
    sys.path.insert(0, path)
from wsgi import app as application
```

Нажать зелёную **Reload**.

Проверить: `https://<user>.pythonanywhere.com/health` должен ответить.

## 7. Привязать webhook

**С обычного компьютера, не из консоли PythonAnywhere** — на бесплатном
тарифе консоль не достучится до `api.telegram.org` (см. DEPLOY.md):

```bash
curl "https://api.telegram.org/bot<ТОКЕН>/setWebhook?url=https://<user>.pythonanywhere.com/webhook"
```

Ответ должен быть `{"ok":true,...}`.

## 8. Утренние напоминания

**Tasks** → создать ежедневную задачу. Время указывается **в UTC**,
Ташкент = UTC+5, значит для 08:30 по Ташкенту ставим **03:30**:

```bash
curl -s "https://<user>.pythonanywhere.com/cron/reminders/<CRON_SECRET>?kind=morning"
```

Вечернее напоминание и недельная сводка отдельной задачи не требуют —
они прицеплены к этому же запуску и к обычному трафику.

Проверить без спама живым людям:

```bash
curl -s "https://<user>.pythonanywhere.com/cron/reminders/<CRON_SECRET>?kind=evening&dry=1"
```

## 9. Назначить админа

В боте отправить: `/admin <ADMIN_SECRET>`

Это должен сделать **сам клиент со своего телефона** — админом станет тот,
кто отправил команду. После этого он добавляет сотрудников через панель.

Секрет остаётся рабочим, так что пароль клиенту передать, но предупредить,
что делиться им нельзя.

## 10. Проверка перед сдачей

- [ ] `/health` отвечает
- [ ] `/status/<DEPLOY_SECRET>` — `updates` растёт при сообщениях боту
- [ ] Клиент стал админом, видит дашборд
- [ ] Тестовый сотрудник добавлен, приход/уход считаются
- [ ] `/backup` присылает файл базы
- [ ] Excel и PDF выгружаются

---

## Обслуживание после сдачи

Правки выкатываются без захода на PythonAnywhere:

```bash
git push origin main
curl -s "https://<user>.pythonanywhere.com/deploy/<DEPLOY_SECRET>"
```

Второй вызов делает `git pull` и перезапуск. Для каждого клиента свой
`DEPLOY_SECRET` — после push дёргать эндпоинт **каждого** клиента.

Общий `main` означает, что сломанный коммит ломает всех клиентов сразу.
Проверять синтаксис до push:

```bash
python -m py_compile app.py ui.py database.py settings.py analytics.py
```

## Что нужно продлевать вручную

Бесплатный тариф периодически «протухает». Раз в месяц зайти и нажать:

- **Web** → Run until N months from today
- **Tasks** → Extend expiry

Иначе бот и напоминания просто перестают работать. Это касается
**каждого** клиентского аккаунта отдельно.
