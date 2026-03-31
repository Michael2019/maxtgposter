import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-web-secret-change-in-production")
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "dev-secret-key-change-in-production")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(days=7)
    WTF_CSRF_TIME_LIMIT = None
    
    # Ссылка на лист с шаблонами постов
    SHEETS_CSV_URL = os.environ.get("SHEETS_CSV_URL")
    
    # Ссылка на лист с пользователями
    USERS_CSV_URL = os.environ.get("USERS_CSV_URL")

    # Google Sheets credentials / spreadsheet config
    GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    GOOGLE_SERVICE_ACCOUNT_FILE = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
    GOOGLE_SPREADSHEET_ID = os.environ.get("GOOGLE_SPREADSHEET_ID")
    GOOGLE_USERS_SHEET = os.environ.get("GOOGLE_USERS_SHEET", "users")
    GOOGLE_TEMPLATES_SHEET = os.environ.get("GOOGLE_TEMPLATES_SHEET", "templates")
    GOOGLE_CHANNELS_SHEET = os.environ.get("GOOGLE_CHANNELS_SHEET", "channels")
    GOOGLE_CAMP_CHANNELS_SHEET = os.environ.get("GOOGLE_CAMP_CHANNELS_SHEET", "camp_channels")

    # Caching
    CACHE_TYPE = "SimpleCache"
    CACHE_DEFAULT_TIMEOUT = int(os.environ.get("CACHE_DEFAULT_TIMEOUT", "600"))

config = Config()
