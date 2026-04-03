# maxtgposter (tildatest)

Подробная инструкция: как развернуть сервис с нуля, подключить Google Sheets, Telegram, MAX и запустить локально/на сервере.

---

## 1) Что это за сервис

Сервис на Flask для подготовки и отправки постов:

- в **Telegram**;
- в **MAX**;
- с веб-интерфейсом для сотрудников;
- с админкой (`пользователи`, `шаблоны`, `каналы`, `история отправок`, `отчет`).

Основные страницы:

- `/login` - вход;
- `/test` - форма "Занятия";
- `/camp` - форма "Каникулы";
- `/admin` - админ-панель.

---

## 2) Что нужно заранее

Перед установкой убедитесь, что у коллеги есть:

1. **Python 3.10+** (желательно 3.11).
2. **Git**.
3. Доступ к репозиторию.
4. Доступ к Google-аккаунту, где будет таблица.
5. Токены:
   - Telegram bot token (`BOT_TOKEN`);
   - MAX bot token (`MAX_BOT_TOKEN`) - если нужен MAX.

---

## 3) Клонирование проекта

Открыть терминал и выполнить:

```bash
git clone https://github.com/Michael2019/maxtgposter.git
cd maxtgposter
```

Если папка уже есть:

```bash
cd maxtgposter
git pull
```

---

## 4) Создание виртуального окружения и установка зависимостей

### Windows (PowerShell)

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
```

### macOS/Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 5) Подготовка Google Sheets (обязательно)

Сервис читает/пишет данные в Google Sheets.

### 5.1 Создайте Google Spreadsheet

Создайте одну таблицу и добавьте листы (вкладки) с такими именами:

- `users`
- `templates`
- `channels`
- `camp_channels`

Если хотите другие названия, потом укажете их через env-переменные.

### 5.2 Структура листа `users`

Минимально нужные колонки (строка 1):

- `username`
- `password_hash`
- `role`
- `family`
- `email`
- `is_admin`

Пример строки пользователя:

- `username`: `ivanov`
- `password_hash`: SHA256 от пароля (как сделать - ниже)
- `role`: `Иван`
- `family`: `Иванов`
- `email`: `ivanov@example.com`
- `is_admin`: `true` (или `false`)

### 5.3 Структура листа `templates`

Минимальные колонки:

- `name`
- `category`
- `module`
- `lesson`
- `post_text`

### 5.4 Структура листа `channels`

Минимальные колонки:

- `name`
- `label`
- `emoji`
- `telegram_chat_id`
- `max_chat_id`

### 5.5 Структура листа `camp_channels`

Такая же, как у `channels`:

- `name`
- `label`
- `emoji`
- `telegram_chat_id`
- `max_chat_id`

### 5.6 Как получить `password_hash` для пользователя

Пароль в таблице должен быть в SHA256.

Пример команды:

```bash
python -c "import hashlib; print(hashlib.sha256('ВашПароль123'.encode('utf-8')).hexdigest())"
```

Скопируйте результат в колонку `password_hash`.

---

## 6) Настройка Google Service Account

### 6.1 Создайте service account в Google Cloud

1. Откройте Google Cloud Console.
2. Создайте проект (или используйте существующий).
3. Включите Google Sheets API.
4. Создайте Service Account.
5. Создайте JSON ключ и скачайте файл.

### 6.2 Выдайте доступ к таблице

Откройте Google Spreadsheet -> "Поделиться" -> добавьте email service account (вида `xxx@xxx.iam.gserviceaccount.com`) с правами **Editor**.

### 6.3 Получите `GOOGLE_SPREADSHEET_ID`

ID берется из URL таблицы:

`https://docs.google.com/spreadsheets/d/<ЭТОТ_ID>/edit`

---

## 7) Telegram и MAX: что настроить

### 7.1 Telegram

1. Создать бота через BotFather.
2. Получить `BOT_TOKEN`.
3. Добавить бота в нужные каналы/чаты.
4. Дать права на публикацию.
5. Убедиться, что в листах `channels` / `camp_channels` корректный `telegram_chat_id`.

### 7.2 MAX

1. Получить `MAX_BOT_TOKEN`.
2. Убедиться, что `max_chat_id` заполнены там, где нужен MAX.
3. Если MAX не нужен - можно оставить `MAX_BOT_TOKEN` пустым.

---

## 8) Создание `.env` файла (главный шаг)

В корне проекта создайте файл `.env` и вставьте:

```env
# Flask / Security
SECRET_KEY=replace-this-secret-key
JWT_SECRET_KEY=replace-this-jwt-secret

# Telegram / MAX
BOT_TOKEN=123456:telegram_token_here
MAX_BOT_TOKEN=max_token_here

# Google Sheets credentials (вариант 1: путь к json файлу)
GOOGLE_SERVICE_ACCOUNT_FILE=C:/path/to/service-account.json

# Google Spreadsheet
GOOGLE_SPREADSHEET_ID=your_spreadsheet_id_here
GOOGLE_USERS_SHEET=users
GOOGLE_TEMPLATES_SHEET=templates
GOOGLE_CHANNELS_SHEET=channels
GOOGLE_CAMP_CHANNELS_SHEET=camp_channels

# Fallback read-only CSV (необязательно, но полезно)
SHEETS_CSV_URL=
USERS_CSV_URL=

# Caching
CACHE_DEFAULT_TIMEOUT=1800
TEMPLATE_CSV_TTL_SEC=1800
```

### Альтернатива для Google credentials

Вместо `GOOGLE_SERVICE_ACCOUNT_FILE` можно использовать:

- `GOOGLE_SERVICE_ACCOUNT_JSON` (содержимое JSON одной строкой).

Обычно проще и безопаснее использовать файл + переменную `GOOGLE_SERVICE_ACCOUNT_FILE`.

---

## 9) Первый запуск локально

Активируйте окружение и выполните:

```bash
python app.py
```

Откройте в браузере:

- `http://localhost:10000/login`

Если нужно другой порт:

```bash
PORT=8080 python app.py
```

На Windows PowerShell:

```powershell
$env:PORT=8080
python app.py
```

---

## 10) Проверка после запуска (чеклист)

Сделайте по порядку:

1. Открыть `/login`, войти под пользователем из `users`.
2. Проверить `/test`:
   - выбрать канал;
   - отправить тестовый пост.
3. Проверить `/camp` аналогично.
4. Проверить `/admin`:
   - открываются пользователи/шаблоны/каналы;
   - открывается история отправок;
   - по кнопке "Открыть отчет" открывается новая вкладка с отчетом.
5. Проверить фактическую доставку в Telegram (и MAX, если включен).

---

## 11) Частые ошибки и как чинить

### Ошибка входа "Неверный логин или пароль"

- Проверьте `username` в `users`.
- Проверьте, что `password_hash` реально SHA256 от пароля.
- Убедитесь, что нет лишних пробелов.

### Ошибка доступа к Google Sheets

- Проверить `GOOGLE_SPREADSHEET_ID`.
- Проверить, что service account добавлен в "Поделиться".
- Проверить путь `GOOGLE_SERVICE_ACCOUNT_FILE`.

### Пост не уходит в Telegram

- Проверить `BOT_TOKEN`.
- Проверить `telegram_chat_id`.
- Проверить, что бот добавлен в канал с правами публикации.

### MAX не отправляет

- Проверить `MAX_BOT_TOKEN`.
- Проверить `max_chat_id`.
- Если MAX временно не нужен - можно оставить пустым.

### Не подгружаются пользователи/шаблоны

- Проверить имена листов в env:
  - `GOOGLE_USERS_SHEET`
  - `GOOGLE_TEMPLATES_SHEET`
  - `GOOGLE_CHANNELS_SHEET`
  - `GOOGLE_CAMP_CHANNELS_SHEET`

---

## 12) Запуск на Render (если нужен деплой)

В репозитории есть `render.yaml`:

- build: `pip install -r requirements.txt`
- start: `gunicorn app:app`

Для деплоя на Render:

1. Подключить репозиторий.
2. Создать Web Service.
3. Выставить все env-переменные из раздела 8.
4. Задеплоить.
5. Проверить `/login` и отправку тестового поста.

---

## 13) Что передать коллеге вместе с этим README

Чтобы коллега точно запустил без созвона, передайте:

1. Ссылку на репозиторий.
2. Готовый `.env` (или шаблон без секретов).
3. JSON ключ service account (без публикации в git).
4. Ссылку на рабочую Google таблицу.
5. Логин/пароль тестового пользователя.
6. Список тестовых каналов для проверки.

---

## 14) Безопасность (важно)

- Никогда не коммитьте:
  - `.env`
  - `service-account.json`
  - токены ботов.
- Секреты хранить только в локальных env или в секретах хостинга.
- При утечке токена - сразу перевыпустить.

---

## 15) Быстрая памятка "запуск за 5 минут"

```bash
git clone https://github.com/Michael2019/maxtgposter.git
cd maxtgposter
python -m venv .venv
# activate venv
pip install -r requirements.txt
# создать .env
python app.py
```

Открыть `http://localhost:10000/login`.

---

Если что-то не запускается, сначала проверьте: `users` лист, хэш пароля, `BOT_TOKEN`, `GOOGLE_SPREADSHEET_ID`, права service account на таблицу.
