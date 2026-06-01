import csv
import hashlib
import json
from io import StringIO

import gspread
import requests
from flask import current_app
from gspread.exceptions import WorksheetNotFound

from extensions import cache
from services.cache_helpers import notify_template_changed


SHEETS_CACHE_TTL_SEC = 1800

# Значения payload → возможные имена колонок в таблице
_PAYLOAD_HEADER_ALIASES = {
    "telegram_chat_id": ("telegram_chat_id", "telegram_id"),
    "telegram_id": ("telegram_chat_id", "telegram_id"),
    "max_chat_id": ("max_chat_id", "max_id"),
    "max_id": ("max_chat_id", "max_id"),
}

DEFAULT_MAIN_CHANNELS = [
    {"name": "test", "label": "Тестовый канал", "emoji": "🔵", "telegram_chat_id": "-1003547986217", "max_chat_id": "-72270757000562"},
    {"name": "APT", "label": "АПТ", "emoji": "💊", "telegram_chat_id": "-1001431896570", "max_chat_id": "-72124844461510"},
    {"name": "BALK", "label": "БАЛК", "emoji": "🚧", "telegram_chat_id": "-1001636810645", "max_chat_id": "-72216528342470"},
    {"name": "BER", "label": "БЕР", "emoji": "🏦", "telegram_chat_id": "-1001206432088", "max_chat_id": "-72125847227846"},
    {"name": "VET", "label": "ВЕТ", "emoji": "🐾", "telegram_chat_id": "-1001364376632", "max_chat_id": "-72216262659526"},
    {"name": "GZHAT", "label": "ГЖАТ", "emoji": "💎", "telegram_chat_id": "-1001192640037", "max_chat_id": "-72125294497222"},
    {"name": "GRAZH", "label": "ГРАЖ", "emoji": "🚗", "telegram_chat_id": "-1002227664922", "max_chat_id": "-72125939699142"},
    {"name": "ESEN", "label": "ЕСЕН", "emoji": "✍️", "telegram_chat_id": "-1001315412232", "max_chat_id": "-72125062303174"},
    {"name": "KAZ", "label": "КАЗ", "emoji": "🕌", "telegram_chat_id": "-1001243940302", "max_chat_id": "-72125139045830"},
    {"name": "KOS", "label": "КОС", "emoji": "🚀", "telegram_chat_id": "-1001344014377", "max_chat_id": "-72124689075654"},
    {"name": "KOM", "label": "КОМ", "emoji": "🔑", "telegram_chat_id": "-1001106933247", "max_chat_id": "-72125427469766"},
    {"name": "KRYL", "label": "КРЫЛ", "emoji": "🦅", "telegram_chat_id": "-1001501560640", "max_chat_id": "-72124587167174"},
    {"name": "KUSH", "label": "КУШ", "emoji": "💰", "telegram_chat_id": "-1003034352804", "max_chat_id": "-72125579120070"},
    {"name": "MAR", "label": "МАР", "emoji": "🔴", "telegram_chat_id": "-1001210093595", "max_chat_id": "-72125357870534"},
    {"name": "OHT", "label": "ОХТ", "emoji": "🔫", "telegram_chat_id": "-1001961394671", "max_chat_id": "-72125223325126"},
    {"name": "ROS", "label": "РОС", "emoji": "🇷🇺", "telegram_chat_id": "-1001358173677", "max_chat_id": "-72124130250182"},
    {"name": "SOLN", "label": "СОЛН", "emoji": "☀️", "telegram_chat_id": "-1002366401046", "max_chat_id": "-72216461036998"},
    {"name": "YAHT", "label": "ЯХТ", "emoji": "⛵", "telegram_chat_id": "-1001304002178", "max_chat_id": "-72125725527494"},
    {"name": "KOM2", "label": "КОМ2", "emoji": "🛡️", "telegram_chat_id": "-1002989757095", "max_chat_id": "-72216207150534"},
]

DEFAULT_CAMP_CHANNELS = [
    {"name": "test", "label": "Тестовый канал", "emoji": "🔵", "telegram_chat_id": "-1003547986217", "max_chat_id": "-72270757000562"},
    {"name": "SOLN", "label": "СОЛН", "emoji": "☀️", "telegram_chat_id": "-1002265440531", "max_chat_id": "-72220373405126"},
    {"name": "GRAZH", "label": "ГРАЖ", "emoji": "🚗", "telegram_chat_id": "-1002230741730", "max_chat_id": "-72220454997446"},
    {"name": "DYB", "label": "ДЫБ", "emoji": "🦅", "telegram_chat_id": "-1003694491475", "max_chat_id": "-75417084153286"},
    {"name": "BER", "label": "БЕР", "emoji": "🏦", "telegram_chat_id": "-1002132174810", "max_chat_id": "-72220627029446"},
    {"name": "MAR", "label": "МАР", "emoji": "🔴", "telegram_chat_id": "-1001974376961", "max_chat_id": "-72220691713478"},
    {"name": "KOS", "label": "КОС", "emoji": "🚀", "telegram_chat_id": "-1001707280364", "max_chat_id": "-72220777958854"},
    {"name": "ROS", "label": "РОС", "emoji": "🇷🇺", "telegram_chat_id": "-1001939033374", "max_chat_id": "-72220987280838"},
    {"name": "KOM", "label": "КОМ", "emoji": "🔑", "telegram_chat_id": "-1001514344312", "max_chat_id": "-72221044035014"},
    {"name": "APT", "label": "АПТ", "emoji": "💊", "telegram_chat_id": "-1001921279740", "max_chat_id": "-72221090041286"},
    {"name": "ESEN", "label": "ЕСЕН", "emoji": "✍️", "telegram_chat_id": "-1001981369423", "max_chat_id": "-72221140176326"},
    {"name": "KAZ", "label": "КАЗ", "emoji": "🕌", "telegram_chat_id": "-1001952039872", "max_chat_id": "-72221214690758"},
]


class GoogleSheetsService:
    def __init__(self):
        self._client = None
        self._spreadsheet = None

    def _get_client(self):
        if self._client:
            return self._client

        cfg = current_app.config
        raw_json = cfg.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        json_file = cfg.get("GOOGLE_SERVICE_ACCOUNT_FILE")

        if raw_json:
            credentials = json.loads(raw_json)
            self._client = gspread.service_account_from_dict(credentials)
            current_app.logger.info("Sheets: using GOOGLE_SERVICE_ACCOUNT_JSON")
            return self._client

        if json_file:
            self._client = gspread.service_account(filename=json_file)
            current_app.logger.info("Sheets: using GOOGLE_SERVICE_ACCOUNT_FILE=%s", json_file)
            return self._client

        current_app.logger.warning("Sheets: no service account configured; fallback mode may be used")
        return None

    def _get_spreadsheet(self):
        if self._spreadsheet:
            return self._spreadsheet
        client = self._get_client()
        spreadsheet_id = current_app.config.get("GOOGLE_SPREADSHEET_ID")
        if not client or not spreadsheet_id:
            current_app.logger.warning(
                "Sheets: spreadsheet unavailable client=%s spreadsheet_id_present=%s",
                bool(client),
                bool(spreadsheet_id),
            )
            return None
        self._spreadsheet = client.open_by_key(spreadsheet_id)
        current_app.logger.info("Sheets: opened spreadsheet id=%s", spreadsheet_id)
        return self._spreadsheet

    def _get_sheet(self, sheet_name):
        spreadsheet = self._get_spreadsheet()
        if not spreadsheet:
            return None
        try:
            return spreadsheet.worksheet(sheet_name)
        except WorksheetNotFound:
            current_app.logger.warning("Sheets: worksheet not found: %s (fallback will be used)", sheet_name)
            return None

    def _read_csv_users_fallback(self):
        users_csv_url = current_app.config.get("USERS_CSV_URL")
        if not users_csv_url:
            current_app.logger.warning("Sheets: USERS_CSV_URL is missing")
            return []
        try:
            current_app.logger.info("Sheets: reading users from CSV fallback url=%s", users_csv_url)
            response = requests.get(users_csv_url, timeout=10)
            response.raise_for_status()
            decoded = response.content.decode("utf-8")
            reader = csv.DictReader(StringIO(decoded))
            current_app.logger.info("Sheets: users CSV headers=%r", reader.fieldnames)
            rows = []
            for idx, row in enumerate(reader, start=2):
                clean = {str(k).strip(): v for k, v in row.items()}
                clean["row_number"] = idx
                clean["id"] = clean.get("id") or str(idx)
                rows.append(clean)
            current_app.logger.info("Sheets: users CSV rows loaded=%s", len(rows))
            return rows
        except Exception as e:
            current_app.logger.exception("Sheets: users CSV fallback failed: %s", e)
            return []

    def _read_csv_templates_fallback(self):
        sheets_csv_url = current_app.config.get("SHEETS_CSV_URL")
        if not sheets_csv_url:
            current_app.logger.warning("Sheets: SHEETS_CSV_URL is missing")
            return []
        try:
            current_app.logger.info("Sheets: reading templates from CSV fallback url=%s", sheets_csv_url)
            response = requests.get(sheets_csv_url, timeout=10)
            response.raise_for_status()
            decoded = response.content.decode("utf-8")
            reader = csv.DictReader(StringIO(decoded))
            current_app.logger.info("Sheets: templates CSV headers=%r", reader.fieldnames)
            rows = []
            for idx, row in enumerate(reader, start=2):
                clean = {str(k).strip(): v for k, v in row.items()}
                clean["row_number"] = idx
                clean["id"] = clean.get("id") or str(idx)
                rows.append(clean)
            current_app.logger.info("Sheets: templates CSV rows loaded=%s", len(rows))
            return rows
        except Exception as e:
            current_app.logger.exception("Sheets: templates CSV fallback failed: %s", e)
            return []

    def _normalize_records(self, records):
        normalized = []
        for idx, row in enumerate(records, start=2):
            clean = {str(k).strip(): v for k, v in row.items()}
            clean["row_number"] = idx
            clean["id"] = clean.get("id") or str(idx - 1)
            normalized.append(clean)
        return normalized

    def get_users(self):
        cache_key = "users_records"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        sheet_name = current_app.config.get("GOOGLE_USERS_SHEET")
        sheet = self._get_sheet(sheet_name)
        if not sheet:
            current_app.logger.warning("Sheets: users sheet unavailable (%s); using fallback", sheet_name)
            records = self._read_csv_users_fallback()
        else:
            current_app.logger.info("Sheets: reading users from worksheet=%s", sheet_name)
            records = sheet.get_all_records()
            current_app.logger.info("Sheets: users rows from worksheet=%s", len(records))
            records = self._normalize_records(records)
            if records:
                current_app.logger.info("Sheets: users columns in first row=%r", list(records[0].keys()))
        self._cache_set(cache_key, records)
        return records

    def get_templates(self):
        cache_key = "template_records"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        sheet = self._get_sheet(current_app.config.get("GOOGLE_TEMPLATES_SHEET"))
        if not sheet:
            records = self._read_csv_templates_fallback()
        else:
            try:
                records = self._normalize_records(sheet.get_all_records())
            except Exception as e:
                current_app.logger.exception("Sheets: templates worksheet read failed: %s", e)
                records = self._read_csv_templates_fallback()
        self._cache_set(cache_key, records)
        return records

    def _get_channels(self, sheet_name, cache_key, defaults):
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        sheet = self._get_sheet(sheet_name)
        if not sheet:
            records = self._normalize_records([dict(x) for x in defaults])
        else:
            records = sheet.get_all_records()
            if not records:
                records = self._normalize_records([dict(x) for x in defaults])
            else:
                records = self._normalize_records(records)
        self._cache_set(cache_key, records)
        return records

    def get_main_channels(self):
        return self._get_channels(current_app.config.get("GOOGLE_CHANNELS_SHEET"), "channels_records_main", DEFAULT_MAIN_CHANNELS)

    def get_camp_channels(self):
        return self._get_channels(current_app.config.get("GOOGLE_CAMP_CHANNELS_SHEET"), "channels_records_camp", DEFAULT_CAMP_CHANNELS)

    def _ensure_write_sheet(self, name):
        sheet = self._get_sheet(name)
        if not sheet:
            raise RuntimeError("Google Sheets write mode is not configured.")
        return sheet

    def _worksheet_headers(self, sheet):
        return [str(h or "").strip() for h in sheet.row_values(1)]

    def _payload_value(self, header, payload):
        if header in payload:
            return payload.get(header, "")
        for alias in _PAYLOAD_HEADER_ALIASES.get(header, ()):
            if alias in payload:
                return payload.get(alias, "")
        return None

    def _cache_get(self, key):
        return cache.get(key)

    def _cache_set(self, key, value):
        cache.set(key, value, timeout=SHEETS_CACHE_TTL_SEC)

    def _cache_delete(self, key):
        cache.delete(key)

    def _invalidate_templates_cache(self):
        self._cache_delete("template_records")
        notify_template_changed()

    def _column_letter(self, col_number):
        result = ""
        while col_number:
            col_number, remainder = divmod(col_number - 1, 26)
            result = chr(65 + remainder) + result
        return result

    def _row_from_payload(self, headers, payload):
        row = []
        for header in headers:
            value = self._payload_value(header, payload)
            row.append("" if value is None else value)
        return row

    def _apply_payload_to_row(self, headers, existing, payload):
        for idx, header in enumerate(headers):
            value = self._payload_value(header, payload)
            if value is not None:
                existing[idx] = value
        return existing

    def create_user(self, payload):
        sheet = self._ensure_write_sheet(current_app.config.get("GOOGLE_USERS_SHEET"))
        headers = self._worksheet_headers(sheet)
        row = self._row_from_payload(headers, payload)
        if "password_hash" in headers and payload.get("password"):
            row[headers.index("password_hash")] = hashlib.sha256(payload["password"].encode()).hexdigest()
        sheet.append_row(row, value_input_option="USER_ENTERED")
        self._cache_delete("users_records")

    def update_user(self, row_number, payload):
        sheet = self._ensure_write_sheet(current_app.config.get("GOOGLE_USERS_SHEET"))
        headers = self._worksheet_headers(sheet)
        existing = sheet.row_values(row_number)
        existing = existing + [""] * max(0, len(headers) - len(existing))
        existing = self._apply_payload_to_row(headers, existing, payload)
        if "password_hash" in headers and payload.get("password"):
            existing[headers.index("password_hash")] = hashlib.sha256(payload["password"].encode()).hexdigest()
        end_col = self._column_letter(len(headers))
        sheet.update(f"A{row_number}:{end_col}{row_number}", [existing[: len(headers)]], value_input_option="USER_ENTERED")
        self._cache_delete("users_records")

    def delete_user(self, row_number):
        sheet = self._ensure_write_sheet(current_app.config.get("GOOGLE_USERS_SHEET"))
        sheet.delete_rows(row_number)
        self._cache_delete("users_records")

    def create_template(self, payload):
        sheet = self._ensure_write_sheet(current_app.config.get("GOOGLE_TEMPLATES_SHEET"))
        headers = self._worksheet_headers(sheet)
        row = self._row_from_payload(headers, payload)
        sheet.append_row(row, value_input_option="USER_ENTERED")
        self._invalidate_templates_cache()

    def update_template(self, row_number, payload):
        sheet = self._ensure_write_sheet(current_app.config.get("GOOGLE_TEMPLATES_SHEET"))
        headers = self._worksheet_headers(sheet)
        existing = sheet.row_values(row_number)
        existing = existing + [""] * max(0, len(headers) - len(existing))
        existing = self._apply_payload_to_row(headers, existing, payload)
        end_col = self._column_letter(len(headers))
        sheet.update(f"A{row_number}:{end_col}{row_number}", [existing[: len(headers)]], value_input_option="USER_ENTERED")
        self._invalidate_templates_cache()

    def delete_template(self, row_number):
        sheet = self._ensure_write_sheet(current_app.config.get("GOOGLE_TEMPLATES_SHEET"))
        sheet.delete_rows(row_number)
        self._invalidate_templates_cache()

    def _create_channel(self, sheet_name, payload, cache_key):
        sheet = self._ensure_write_sheet(sheet_name)
        headers = self._worksheet_headers(sheet)
        row = self._row_from_payload(headers, payload)
        sheet.append_row(row, value_input_option="USER_ENTERED")
        self._cache_delete(cache_key)

    def _update_channel(self, sheet_name, row_number, payload, cache_key):
        sheet = self._ensure_write_sheet(sheet_name)
        headers = self._worksheet_headers(sheet)
        existing = sheet.row_values(row_number)
        existing = existing + [""] * max(0, len(headers) - len(existing))
        existing = self._apply_payload_to_row(headers, existing, payload)
        end_col = self._column_letter(len(headers))
        sheet.update(f"A{row_number}:{end_col}{row_number}", [existing[: len(headers)]], value_input_option="USER_ENTERED")
        self._cache_delete(cache_key)

    def _delete_channel(self, sheet_name, row_number, cache_key):
        sheet = self._ensure_write_sheet(sheet_name)
        sheet.delete_rows(row_number)
        self._cache_delete(cache_key)

    def create_main_channel(self, payload):
        self._create_channel(current_app.config.get("GOOGLE_CHANNELS_SHEET"), payload, "channels_records_main")

    def update_main_channel(self, row_number, payload):
        self._update_channel(current_app.config.get("GOOGLE_CHANNELS_SHEET"), row_number, payload, "channels_records_main")

    def delete_main_channel(self, row_number):
        self._delete_channel(current_app.config.get("GOOGLE_CHANNELS_SHEET"), row_number, "channels_records_main")

    def create_camp_channel(self, payload):
        self._create_channel(current_app.config.get("GOOGLE_CAMP_CHANNELS_SHEET"), payload, "channels_records_camp")

    def update_camp_channel(self, row_number, payload):
        self._update_channel(current_app.config.get("GOOGLE_CAMP_CHANNELS_SHEET"), row_number, payload, "channels_records_camp")

    def delete_camp_channel(self, row_number):
        self._delete_channel(current_app.config.get("GOOGLE_CAMP_CHANNELS_SHEET"), row_number, "channels_records_camp")


sheets_service = GoogleSheetsService()
