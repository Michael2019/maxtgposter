# tildatest

Flask-приложение для генерации и отправки постов в Telegram/MAX с авторизацией и админ-панелью.

## Что добавлено

- Веб-страницы: `/login`, `/test`, `/camp`
- Админ-панель: `/admin`, `/admin/users`, `/admin/templates`
- CRUD для пользователей и шаблонов через Google Sheets
- `Blueprints`: `auth`, `main`, `admin`
- Формы на Flask-WTF + CSRF
- Кэширование запросов к Google Sheets через Flask-Caching
- Обновленный UI на Bootstrap 5 с анимациями и light/dark toggle

## Переменные окружения

- `SECRET_KEY`
- `JWT_SECRET_KEY`
- `BOT_TOKEN`
- `MAX_BOT_TOKEN`
- `SHEETS_CSV_URL` (fallback read-only для шаблонов)
- `USERS_CSV_URL` (fallback read-only для пользователей)
- `GOOGLE_SERVICE_ACCOUNT_JSON` или `GOOGLE_SERVICE_ACCOUNT_FILE`
- `GOOGLE_SPREADSHEET_ID`
- `GOOGLE_USERS_SHEET` (по умолчанию `users`)
- `GOOGLE_TEMPLATES_SHEET` (по умолчанию `templates`)

## Запуск

1. `pip install -r requirements.txt`
2. Заполните env-переменные
3. `python app.py`
