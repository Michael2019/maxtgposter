import csv
import hashlib
import json
from io import StringIO

import gspread
import requests
from flask import current_app

from extensions import cache


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
        return spreadsheet.worksheet(sheet_name)

    def _read_csv_users_fallback(self):
        users_csv_url = current_app.config.get("USERS_CSV_URL")
        if not users_csv_url:
            current_app.logger.warning("Sheets: USERS_CSV_URL is missing")
            return []
        current_app.logger.info("Sheets: reading users from CSV fallback url=%s", users_csv_url)
        response = requests.get(users_csv_url, timeout=10)
        response.raise_for_status()
        decoded = response.content.decode("utf-8")
        reader = csv.DictReader(StringIO(decoded))
        current_app.logger.info("Sheets: users CSV headers=%r", reader.fieldnames)
        rows = []
        for idx, row in enumerate(reader, start=2):
            row["row_number"] = idx
            row["id"] = row.get("id") or str(idx)
            rows.append(row)
        current_app.logger.info("Sheets: users CSV rows loaded=%s", len(rows))
        return rows

    def _read_csv_templates_fallback(self):
        sheets_csv_url = current_app.config.get("SHEETS_CSV_URL")
        if not sheets_csv_url:
            current_app.logger.warning("Sheets: SHEETS_CSV_URL is missing")
            return []
        current_app.logger.info("Sheets: reading templates from CSV fallback url=%s", sheets_csv_url)
        response = requests.get(sheets_csv_url, timeout=10)
        response.raise_for_status()
        decoded = response.content.decode("utf-8")
        reader = csv.DictReader(StringIO(decoded))
        current_app.logger.info("Sheets: templates CSV headers=%r", reader.fieldnames)
        rows = []
        for idx, row in enumerate(reader, start=2):
            row["row_number"] = idx
            row["id"] = row.get("id") or str(idx)
            rows.append(row)
        current_app.logger.info("Sheets: templates CSV rows loaded=%s", len(rows))
        return rows

    @cache.cached(timeout=600, key_prefix="users_records")
    def get_users(self):
        sheet_name = current_app.config.get("GOOGLE_USERS_SHEET")
        sheet = self._get_sheet(sheet_name)
        if not sheet:
            current_app.logger.warning("Sheets: users sheet unavailable (%s); using fallback", sheet_name)
            return self._read_csv_users_fallback()
        current_app.logger.info("Sheets: reading users from worksheet=%s", sheet_name)
        records = sheet.get_all_records()
        current_app.logger.info("Sheets: users rows from worksheet=%s", len(records))
        for idx, row in enumerate(records, start=2):
            row["row_number"] = idx
            row["id"] = row.get("id") or str(idx)
        if records:
            current_app.logger.info("Sheets: users columns in first row=%r", list(records[0].keys()))
        return records

    @cache.cached(timeout=600, key_prefix="template_records")
    def get_templates(self):
        sheet = self._get_sheet(current_app.config.get("GOOGLE_TEMPLATES_SHEET"))
        if not sheet:
            return self._read_csv_templates_fallback()
        records = sheet.get_all_records()
        for idx, row in enumerate(records, start=2):
            row["row_number"] = idx
            row["id"] = row.get("id") or str(idx)
        return records

    def _ensure_write_sheet(self, name):
        sheet = self._get_sheet(name)
        if not sheet:
            raise RuntimeError("Google Sheets write mode is not configured.")
        return sheet

    def _worksheet_headers(self, sheet):
        return sheet.row_values(1)

    def _column_letter(self, col_number):
        result = ""
        while col_number:
            col_number, remainder = divmod(col_number - 1, 26)
            result = chr(65 + remainder) + result
        return result

    def create_user(self, payload):
        sheet = self._ensure_write_sheet(current_app.config.get("GOOGLE_USERS_SHEET"))
        headers = self._worksheet_headers(sheet)
        row = [payload.get(header, "") for header in headers]
        if "password_hash" in headers and payload.get("password"):
            row[headers.index("password_hash")] = hashlib.sha256(payload["password"].encode()).hexdigest()
        sheet.append_row(row, value_input_option="USER_ENTERED")
        cache.delete("users_records")

    def update_user(self, row_number, payload):
        sheet = self._ensure_write_sheet(current_app.config.get("GOOGLE_USERS_SHEET"))
        headers = self._worksheet_headers(sheet)
        existing = sheet.row_values(row_number)
        existing = existing + [""] * max(0, len(headers) - len(existing))
        for idx, header in enumerate(headers):
            if header in payload:
                existing[idx] = payload.get(header, "")
        if "password_hash" in headers and payload.get("password"):
            existing[headers.index("password_hash")] = hashlib.sha256(payload["password"].encode()).hexdigest()
        end_col = self._column_letter(len(headers))
        sheet.update(f"A{row_number}:{end_col}{row_number}", [existing[: len(headers)]], value_input_option="USER_ENTERED")
        cache.delete("users_records")

    def delete_user(self, row_number):
        sheet = self._ensure_write_sheet(current_app.config.get("GOOGLE_USERS_SHEET"))
        sheet.delete_rows(row_number)
        cache.delete("users_records")

    def create_template(self, payload):
        sheet = self._ensure_write_sheet(current_app.config.get("GOOGLE_TEMPLATES_SHEET"))
        headers = self._worksheet_headers(sheet)
        row = [payload.get(header, "") for header in headers]
        sheet.append_row(row, value_input_option="USER_ENTERED")
        cache.delete("template_records")

    def update_template(self, row_number, payload):
        sheet = self._ensure_write_sheet(current_app.config.get("GOOGLE_TEMPLATES_SHEET"))
        headers = self._worksheet_headers(sheet)
        existing = sheet.row_values(row_number)
        existing = existing + [""] * max(0, len(headers) - len(existing))
        for idx, header in enumerate(headers):
            if header in payload:
                existing[idx] = payload.get(header, "")
        end_col = self._column_letter(len(headers))
        sheet.update(f"A{row_number}:{end_col}{row_number}", [existing[: len(headers)]], value_input_option="USER_ENTERED")
        cache.delete("template_records")

    def delete_template(self, row_number):
        sheet = self._ensure_write_sheet(current_app.config.get("GOOGLE_TEMPLATES_SHEET"))
        sheet.delete_rows(row_number)
        cache.delete("template_records")


sheets_service = GoogleSheetsService()
