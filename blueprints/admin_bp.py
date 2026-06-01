from datetime import datetime, time, timezone

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from auth import admin_required, web_login_required
from forms.admin_forms import ChannelForm, TemplateForm, UserForm, sheet_cell_str, validate_template_location
from services.publish_queue import list_history, list_history_between
from services.sheets import sheets_service

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def _flash_form_errors(form):
    for field, errors in form.errors.items():
        for err in errors:
            flash(f"{field}: {err}", "danger")


def _channel_form_data(item):
    data = dict(item)
    if not data.get("telegram_chat_id") and data.get("telegram_id"):
        data["telegram_chat_id"] = data["telegram_id"]
    if not data.get("max_chat_id") and data.get("max_id"):
        data["max_chat_id"] = data["max_id"]
    return data


def _sheets_write_error_message(exc):
    msg = str(exc)
    if "not configured" in msg.lower():
        return "Запись в Google Sheets недоступна: проверьте GOOGLE_SPREADSHEET_ID и ключ сервисного аккаунта."
    return f"Ошибка сохранения: {msg}"


@admin_bp.route("/")
@web_login_required
@admin_required
def dashboard():
    try:
        users = sheets_service.get_users()
        templates = sheets_service.get_templates()
        main_channels = sheets_service.get_main_channels()
        camp_channels = sheets_service.get_camp_channels()
        # Счётчик без запроса к Sheets — иначе админка падает/виснет при проблемах с API.
        history_items = list_history(200, use_sheets=False)
    except Exception as exc:
        current_app.logger.exception("admin dashboard failed: %s", exc)
        flash(f"Ошибка загрузки данных админки: {exc}", "danger")
        users, templates, main_channels, camp_channels, history_items = [], [], [], [], []
    return render_template(
        "admin/dashboard.html",
        users_count=len(users),
        templates_count=len(templates),
        channels_count=len(main_channels),
        camp_channels_count=len(camp_channels),
        history_count=len(history_items),
    )


@admin_bp.route("/users")
@web_login_required
@admin_required
def users_list():
    users = sheets_service.get_users()
    users = sorted(
        users,
        key=lambda x: (
            str(x.get("family") or "").strip().lower(),
            str(x.get("role") or "").strip().lower(),
            str(x.get("username") or "").strip().lower(),
        ),
    )
    return render_template("admin/users.html", users=users)


@admin_bp.route("/users/new", methods=["GET", "POST"])
@web_login_required
@admin_required
def users_create():
    form = UserForm()
    if form.validate_on_submit():
        try:
            sheets_service.create_user(
                {
                    "username": form.username.data,
                    "email": form.email.data,
                    "role": form.name.data,
                    "family": form.family.data,
                    "is_admin": str(bool(form.is_admin.data)),
                    "password": form.password.data,
                }
            )
        except RuntimeError as exc:
            flash(_sheets_write_error_message(exc), "danger")
            return render_template("admin/user_form.html", form=form, mode="create", old_password="")
        flash("Пользователь создан", "success")
        return redirect(url_for("admin.users_list"))
    if form.errors:
        _flash_form_errors(form)
    return render_template("admin/user_form.html", form=form, mode="create", old_password="")


@admin_bp.route("/users/<int:row_number>/edit", methods=["GET", "POST"])
@web_login_required
@admin_required
def users_edit(row_number):
    users = sheets_service.get_users()
    user = next((x for x in users if int(x.get("row_number", 0)) == row_number), None)
    if not user:
        flash("Пользователь не найден", "danger")
        return redirect(url_for("admin.users_list"))
    user_data = dict(user)
    user_data["name"] = user.get("role", "")
    form = UserForm(data=user_data)
    if request.method == "GET":
        form.is_admin.data = str(user.get("is_admin", "")).lower() in {"true", "1", "yes"}
    if form.validate_on_submit():
        payload = {
            "username": form.username.data,
            "email": form.email.data,
            "role": form.name.data,
            "family": form.family.data,
            "is_admin": str(bool(form.is_admin.data)),
        }
        new_password = (form.password.data or "").strip()
        if new_password:
            payload["password"] = new_password
        try:
            sheets_service.update_user(row_number, payload)
        except RuntimeError as exc:
            flash(_sheets_write_error_message(exc), "danger")
            return render_template(
                "admin/user_form.html",
                form=form,
                mode="edit",
                row_number=row_number,
                old_password=str(user.get("password_plain") or user.get("password") or "").strip(),
            )
        flash("Пользователь обновлен", "success")
        return redirect(url_for("admin.users_list"))
    if form.errors:
        _flash_form_errors(form)
    return render_template(
        "admin/user_form.html",
        form=form,
        mode="edit",
        row_number=row_number,
        old_password=str(user.get("password_plain") or user.get("password") or "").strip(),
    )


@admin_bp.route("/users/<int:row_number>/delete", methods=["POST"])
@web_login_required
@admin_required
def users_delete(row_number):
    try:
        sheets_service.delete_user(row_number)
    except RuntimeError as exc:
        flash(_sheets_write_error_message(exc), "danger")
        return redirect(url_for("admin.users_list"))
    flash("Пользователь удален", "info")
    return redirect(url_for("admin.users_list"))


@admin_bp.route("/templates")
@web_login_required
@admin_required
def templates_list():
    templates = sheets_service.get_templates()
    templates = sorted(
        templates,
        key=lambda x: (
            str(x.get("category") or "Без категории"),
            str(x.get("module") or "Без модуля"),
            str(x.get("lesson") or "Без занятия"),
            str(x.get("name") or ""),
        ),
    )
    return render_template("admin/templates.html", templates=templates)


@admin_bp.route("/templates/new", methods=["GET", "POST"])
@web_login_required
@admin_required
def templates_create():
    form = TemplateForm()
    if form.validate_on_submit():
        category = request.form.get("category", "").strip()
        module = request.form.get("module", "").strip()
        lesson = request.form.get("lesson", "").strip()
        ok, err = validate_template_location(category, module, lesson)
        if not ok:
            flash(err or "Проверьте категорию, модуль и занятие", "danger")
            return render_template(
                "admin/template_form.html",
                form=form,
                mode="create",
                initial_category=category,
                initial_module=module,
                initial_lesson=lesson,
            )
        try:
            sheets_service.create_template(
                {
                    "name": form.name.data,
                    "category": category,
                    "module": module,
                    "lesson": lesson,
                    "post_text": form.post_text.data,
                }
            )
        except RuntimeError as exc:
            flash(_sheets_write_error_message(exc), "danger")
            return render_template(
                "admin/template_form.html",
                form=form,
                mode="create",
                initial_category=category,
                initial_module=module,
                initial_lesson=lesson,
            )
        flash("Шаблон создан", "success")
        return redirect(url_for("admin.templates_list"))
    if form.errors:
        _flash_form_errors(form)
    return render_template("admin/template_form.html", form=form, mode="create")


def _template_form_data(tpl: dict) -> dict:
    return {
        "name": sheet_cell_str(tpl.get("name")),
        "post_text": sheet_cell_str(tpl.get("post_text")),
    }


def _template_initial_location(tpl: dict) -> tuple:
    return (
        sheet_cell_str(tpl.get("category")),
        sheet_cell_str(tpl.get("module")),
        sheet_cell_str(tpl.get("lesson")),
    )


@admin_bp.route("/templates/<int:row_number>/edit", methods=["GET", "POST"])
@web_login_required
@admin_required
def templates_edit(row_number):
    try:
        templates = sheets_service.get_templates()
        tpl = next((x for x in templates if int(x.get("row_number", 0)) == row_number), None)
        if not tpl:
            flash("Шаблон не найден", "danger")
            return redirect(url_for("admin.templates_list"))
        init_category, init_module, init_lesson = _template_initial_location(tpl)
        form = TemplateForm(data=_template_form_data(tpl))
    except Exception as exc:
        current_app.logger.exception("templates_edit load failed row=%s: %s", row_number, exc)
        flash(f"Не удалось открыть шаблон: {exc}", "danger")
        return redirect(url_for("admin.templates_list"))

    if form.validate_on_submit():
        category = request.form.get("category", "").strip()
        module = request.form.get("module", "").strip()
        lesson = request.form.get("lesson", "").strip()
        ok, err = validate_template_location(category, module, lesson)
        if not ok:
            flash(err or "Проверьте категорию, модуль и занятие", "danger")
            return render_template(
                "admin/template_form.html",
                form=form,
                mode="edit",
                row_number=row_number,
                initial_category=category,
                initial_module=module,
                initial_lesson=lesson,
            )
        try:
            sheets_service.update_template(
                row_number,
                {
                    "name": form.name.data,
                    "category": category,
                    "module": module,
                    "lesson": lesson,
                    "post_text": form.post_text.data,
                },
            )
        except RuntimeError as exc:
            flash(_sheets_write_error_message(exc), "danger")
            return render_template(
                "admin/template_form.html",
                form=form,
                mode="edit",
                row_number=row_number,
                initial_category=category,
                initial_module=module,
                initial_lesson=lesson,
            )
        flash("Шаблон обновлен", "success")
        return redirect(url_for("admin.templates_list"))
    if form.errors:
        _flash_form_errors(form)
    return render_template(
        "admin/template_form.html",
        form=form,
        mode="edit",
        row_number=row_number,
        initial_category=init_category,
        initial_module=init_module,
        initial_lesson=init_lesson,
    )


@admin_bp.route("/templates/<int:row_number>/delete", methods=["POST"])
@web_login_required
@admin_required
def templates_delete(row_number):
    try:
        sheets_service.delete_template(row_number)
    except RuntimeError as exc:
        flash(_sheets_write_error_message(exc), "danger")
        return redirect(url_for("admin.templates_list"))
    flash("Шаблон удален", "info")
    return redirect(url_for("admin.templates_list"))


def _channel_payload(form):
    tg_id = form.telegram_chat_id.data
    mx_id = form.max_chat_id.data
    return {
        "name": form.name.data,
        "label": form.label.data,
        "emoji": form.emoji.data,
        "telegram_chat_id": tg_id,
        "telegram_id": tg_id,
        "max_chat_id": mx_id,
        "max_id": mx_id,
    }


@admin_bp.route("/channels")
@web_login_required
@admin_required
def channels_list():
    return render_template("admin/channels.html", channels=sheets_service.get_main_channels(), list_title="Каналы")


@admin_bp.route("/channels/new", methods=["GET", "POST"])
@web_login_required
@admin_required
def channels_create():
    form = ChannelForm()
    if form.validate_on_submit():
        try:
            sheets_service.create_main_channel(_channel_payload(form))
        except RuntimeError as exc:
            flash(_sheets_write_error_message(exc), "danger")
            return render_template("admin/channel_form.html", form=form, mode="create", endpoint="admin.channels_create")
        flash("Канал добавлен", "success")
        return redirect(url_for("admin.channels_list"))
    if form.errors:
        _flash_form_errors(form)
    return render_template("admin/channel_form.html", form=form, mode="create", endpoint="admin.channels_create")


@admin_bp.route("/channels/<int:row_number>/edit", methods=["GET", "POST"])
@web_login_required
@admin_required
def channels_edit(row_number):
    items = sheets_service.get_main_channels()
    item = next((x for x in items if int(x.get("row_number", 0)) == row_number), None)
    if not item:
        flash("Канал не найден", "danger")
        return redirect(url_for("admin.channels_list"))
    form = ChannelForm(data=_channel_form_data(item))
    if form.validate_on_submit():
        try:
            sheets_service.update_main_channel(row_number, _channel_payload(form))
        except RuntimeError as exc:
            flash(_sheets_write_error_message(exc), "danger")
            return render_template(
                "admin/channel_form.html",
                form=form,
                mode="edit",
                endpoint="admin.channels_edit",
                row_number=row_number,
            )
        flash("Канал обновлен", "success")
        return redirect(url_for("admin.channels_list"))
    if form.errors:
        _flash_form_errors(form)
    return render_template("admin/channel_form.html", form=form, mode="edit", endpoint="admin.channels_edit", row_number=row_number)


@admin_bp.route("/channels/<int:row_number>/delete", methods=["POST"])
@web_login_required
@admin_required
def channels_delete(row_number):
    try:
        sheets_service.delete_main_channel(row_number)
    except RuntimeError as exc:
        flash(_sheets_write_error_message(exc), "danger")
        return redirect(url_for("admin.channels_list"))
    flash("Канал удален", "info")
    return redirect(url_for("admin.channels_list"))


@admin_bp.route("/camp-channels")
@web_login_required
@admin_required
def camp_channels_list():
    return render_template("admin/channels.html", channels=sheets_service.get_camp_channels(), list_title="Каналы КШ")


@admin_bp.route("/camp-channels/new", methods=["GET", "POST"])
@web_login_required
@admin_required
def camp_channels_create():
    form = ChannelForm()
    if form.validate_on_submit():
        try:
            sheets_service.create_camp_channel(_channel_payload(form))
        except RuntimeError as exc:
            flash(_sheets_write_error_message(exc), "danger")
            return render_template(
                "admin/channel_form.html",
                form=form,
                mode="create",
                endpoint="admin.camp_channels_create",
            )
        flash("Канал КШ добавлен", "success")
        return redirect(url_for("admin.camp_channels_list"))
    if form.errors:
        _flash_form_errors(form)
    return render_template("admin/channel_form.html", form=form, mode="create", endpoint="admin.camp_channels_create")


@admin_bp.route("/camp-channels/<int:row_number>/edit", methods=["GET", "POST"])
@web_login_required
@admin_required
def camp_channels_edit(row_number):
    items = sheets_service.get_camp_channels()
    item = next((x for x in items if int(x.get("row_number", 0)) == row_number), None)
    if not item:
        flash("Канал КШ не найден", "danger")
        return redirect(url_for("admin.camp_channels_list"))
    form = ChannelForm(data=_channel_form_data(item))
    if form.validate_on_submit():
        try:
            sheets_service.update_camp_channel(row_number, _channel_payload(form))
        except RuntimeError as exc:
            flash(_sheets_write_error_message(exc), "danger")
            return render_template(
                "admin/channel_form.html",
                form=form,
                mode="edit",
                endpoint="admin.camp_channels_edit",
                row_number=row_number,
            )
        flash("Канал КШ обновлен", "success")
        return redirect(url_for("admin.camp_channels_list"))
    if form.errors:
        _flash_form_errors(form)
    return render_template("admin/channel_form.html", form=form, mode="edit", endpoint="admin.camp_channels_edit", row_number=row_number)


@admin_bp.route("/camp-channels/<int:row_number>/delete", methods=["POST"])
@web_login_required
@admin_required
def camp_channels_delete(row_number):
    try:
        sheets_service.delete_camp_channel(row_number)
    except RuntimeError as exc:
        flash(_sheets_write_error_message(exc), "danger")
        return redirect(url_for("admin.camp_channels_list"))
    flash("Канал КШ удален", "info")
    return redirect(url_for("admin.camp_channels_list"))


def _format_history_datetime(iso_value: str) -> str:
    if not iso_value:
        return "—"
    try:
        dt = datetime.fromisoformat(str(iso_value).replace("Z", "+00:00"))
        return dt.strftime("%d.%m.%Y %H:%M")
    except (TypeError, ValueError):
        return str(iso_value)[:19]


def _enrich_history_items(items):
    for item in items:
        item["created_at_display"] = _format_history_datetime(item.get("created_at"))
        item["finished_at_display"] = _format_history_datetime(item.get("finished_at"))
        summary = item.get("summary") or {}
        if isinstance(summary, dict):
            if summary.get("error"):
                item["summary_short"] = str(summary.get("error") or "")[:120]
            elif summary.get("ok") is False:
                parts = []
                if summary.get("telegram_error"):
                    parts.append(f"TG: {str(summary.get('telegram_error'))[:60]}")
                if summary.get("max_error"):
                    parts.append(f"MAX: {str(summary.get('max_error'))[:60]}")
                item["summary_short"] = "; ".join(parts) or "ошибка публикации"
            else:
                item["summary_short"] = "OK"
        else:
            item["summary_short"] = str(summary)[:120]
    return items


@admin_bp.route("/history")
@web_login_required
@admin_required
def publish_history():
    start_date_raw, end_date_raw, start_dt, end_dt, filter_error = _parse_history_dates(request.args)

    try:
        if filter_error:
            items = list_history(500, use_sheets=True)
        else:
            items = list_history_between(start_dt=start_dt, end_dt=end_dt, limit=500, use_sheets=True)
        items = _enrich_history_items(items)
    except Exception as exc:
        current_app.logger.exception("publish_history page failed: %s", exc)
        flash("Не удалось загрузить историю. Проверьте лист publish_history в таблице.", "danger")
        items = []

    return render_template(
        "admin/history.html",
        items=items,
        start_date=start_date_raw,
        end_date=end_date_raw,
        filter_error=filter_error,
        history_total=len(items),
    )


def _parse_history_dates(args):
    start_date_raw = (args.get("start_date") or "").strip()
    end_date_raw = (args.get("end_date") or "").strip()

    start_dt = None
    end_dt = None
    filter_error = None
    try:
        if start_date_raw:
            start_dt = datetime.strptime(start_date_raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if end_date_raw:
            end_day = datetime.strptime(end_date_raw, "%Y-%m-%d").date()
            end_dt = datetime.combine(end_day, time.max).replace(tzinfo=timezone.utc)
        if start_dt and end_dt and start_dt > end_dt:
            filter_error = "Начальная дата не может быть больше конечной"
    except ValueError:
        filter_error = "Неверный формат даты"
    return start_date_raw, end_date_raw, start_dt, end_dt, filter_error


def _build_posts_report_rows(items):
    users = sheets_service.get_users()
    channels = [*sheets_service.get_main_channels(), *sheets_service.get_camp_channels()]
    users_by_username = {str(u.get("username", "")).strip(): u for u in users}
    channel_labels = {}
    for channel in channels:
        label = str(channel.get("label") or channel.get("name") or "").strip()
        if not label:
            continue
        for key in (
            channel.get("name"),
            channel.get("telegram_chat_id"),
            channel.get("telegram_id"),
            channel.get("max_chat_id"),
            channel.get("max_id"),
        ):
            normalized = str(key or "").strip()
            if normalized and normalized not in channel_labels:
                channel_labels[normalized] = label
    report_map = {}

    for item in items:
        if item.get("status") != "done":
            continue
        username = str((item.get("user") or {}).get("username", "")).strip()
        user_row = users_by_username.get(username, {})
        family = str(user_row.get("family", "")).strip()
        name = str(user_row.get("role", "")).strip()
        if not family and not name:
            name = username or "—"
        key = (family, name)
        row_data = report_map.setdefault(key, {"posts_count": 0, "channel_counts": {}})
        row_data["posts_count"] += 1

        channel_key = str(item.get("channel") or "").strip()
        if channel_key:
            channel_label = channel_labels.get(channel_key, channel_key)
            row_data["channel_counts"][channel_label] = row_data["channel_counts"].get(channel_label, 0) + 1

    report_rows = [
        {
            "family": family,
            "name": name,
            "posts_count": data["posts_count"],
            "posts_by_channels": ", ".join(
                f"{cnt} {label}"
                for label, cnt in sorted(
                    data["channel_counts"].items(),
                    key=lambda x: (-x[1], x[0].lower()),
                )
            ),
        }
        for (family, name), data in sorted(
            report_map.items(),
            key=lambda x: (-x[1]["posts_count"], (x[0][0] or "").lower(), (x[0][1] or "").lower()),
        )
    ]
    return report_rows


@admin_bp.route("/history/report")
@web_login_required
@admin_required
def publish_history_report():
    start_date_raw, end_date_raw, start_dt, end_dt, filter_error = _parse_history_dates(request.args)

    if filter_error:
        items = []
    else:
        items = list_history_between(start_dt=start_dt, end_dt=end_dt, limit=500)
    report_rows = _build_posts_report_rows(items)

    return render_template(
        "admin/history_report.html",
        report_rows=report_rows,
        start_date=start_date_raw,
        end_date=end_date_raw,
        filter_error=filter_error,
    )
