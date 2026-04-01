from flask import Blueprint, flash, redirect, render_template, request, url_for

from auth import admin_required, web_login_required
from forms.admin_forms import ChannelForm, TemplateForm, UserForm, validate_template_location
from services.publish_queue import list_history
from services.sheets import sheets_service

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.route("/")
@web_login_required
@admin_required
def dashboard():
    users = sheets_service.get_users()
    templates = sheets_service.get_templates()
    return render_template(
        "admin/dashboard.html",
        users_count=len(users),
        templates_count=len(templates),
        channels_count=len(sheets_service.get_main_channels()),
        camp_channels_count=len(sheets_service.get_camp_channels()),
        history_count=len(list_history(200)),
    )


@admin_bp.route("/users")
@web_login_required
@admin_required
def users_list():
    users = sheets_service.get_users()
    return render_template("admin/users.html", users=users)


@admin_bp.route("/users/new", methods=["GET", "POST"])
@web_login_required
@admin_required
def users_create():
    form = UserForm()
    if form.validate_on_submit():
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
        flash("Пользователь создан", "success")
        return redirect(url_for("admin.users_list"))
    if form.errors:
        flash(str(form.errors), "danger")
    return render_template("admin/user_form.html", form=form, mode="create")


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
        sheets_service.update_user(
            row_number,
            {
                "username": form.username.data,
                "email": form.email.data,
                "role": form.name.data,
                "family": form.family.data,
                "is_admin": str(bool(form.is_admin.data)),
                "password": form.password.data,
            },
        )
        flash("Пользователь обновлен", "success")
        return redirect(url_for("admin.users_list"))
    if form.errors:
        flash(str(form.errors), "danger")
    return render_template("admin/user_form.html", form=form, mode="edit", row_number=row_number)


@admin_bp.route("/users/<int:row_number>/delete", methods=["POST"])
@web_login_required
@admin_required
def users_delete(row_number):
    sheets_service.delete_user(row_number)
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
        sheets_service.create_template(
            {
                "name": form.name.data,
                "category": category,
                "module": module,
                "lesson": lesson,
                "post_text": form.post_text.data,
            }
        )
        flash("Шаблон создан", "success")
        return redirect(url_for("admin.templates_list"))
    return render_template("admin/template_form.html", form=form, mode="create")


@admin_bp.route("/templates/<int:row_number>/edit", methods=["GET", "POST"])
@web_login_required
@admin_required
def templates_edit(row_number):
    templates = sheets_service.get_templates()
    tpl = next((x for x in templates if int(x.get("row_number", 0)) == row_number), None)
    if not tpl:
        flash("Шаблон не найден", "danger")
        return redirect(url_for("admin.templates_list"))
    form = TemplateForm(data=tpl)
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
        flash("Шаблон обновлен", "success")
        return redirect(url_for("admin.templates_list"))
    return render_template(
        "admin/template_form.html",
        form=form,
        mode="edit",
        row_number=row_number,
        initial_category=(tpl.get("category") or "").strip(),
        initial_module=(tpl.get("module") or "").strip(),
        initial_lesson=(tpl.get("lesson") or "").strip(),
    )


@admin_bp.route("/templates/<int:row_number>/delete", methods=["POST"])
@web_login_required
@admin_required
def templates_delete(row_number):
    sheets_service.delete_template(row_number)
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
        sheets_service.create_main_channel(_channel_payload(form))
        flash("Канал добавлен", "success")
        return redirect(url_for("admin.channels_list"))
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
    form = ChannelForm(data=item)
    if form.validate_on_submit():
        sheets_service.update_main_channel(row_number, _channel_payload(form))
        flash("Канал обновлен", "success")
        return redirect(url_for("admin.channels_list"))
    return render_template("admin/channel_form.html", form=form, mode="edit", endpoint="admin.channels_edit", row_number=row_number)


@admin_bp.route("/channels/<int:row_number>/delete", methods=["POST"])
@web_login_required
@admin_required
def channels_delete(row_number):
    sheets_service.delete_main_channel(row_number)
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
        sheets_service.create_camp_channel(_channel_payload(form))
        flash("Канал КШ добавлен", "success")
        return redirect(url_for("admin.camp_channels_list"))
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
    form = ChannelForm(data=item)
    if form.validate_on_submit():
        sheets_service.update_camp_channel(row_number, _channel_payload(form))
        flash("Канал КШ обновлен", "success")
        return redirect(url_for("admin.camp_channels_list"))
    return render_template("admin/channel_form.html", form=form, mode="edit", endpoint="admin.camp_channels_edit", row_number=row_number)


@admin_bp.route("/camp-channels/<int:row_number>/delete", methods=["POST"])
@web_login_required
@admin_required
def camp_channels_delete(row_number):
    sheets_service.delete_camp_channel(row_number)
    flash("Канал КШ удален", "info")
    return redirect(url_for("admin.camp_channels_list"))


@admin_bp.route("/history")
@web_login_required
@admin_required
def publish_history():
    return render_template("admin/history.html", items=list_history(200))
