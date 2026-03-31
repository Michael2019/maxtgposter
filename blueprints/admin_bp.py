from flask import Blueprint, flash, redirect, render_template, request, url_for

from auth import admin_required, web_login_required
from forms.admin_forms import TemplateForm, UserForm
from services.sheets import sheets_service

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.route("/")
@web_login_required
@admin_required
def dashboard():
    users = sheets_service.get_users()
    templates = sheets_service.get_templates()
    return render_template("admin/dashboard.html", users_count=len(users), templates_count=len(templates))


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
                "role": form.role.data,
                "is_admin": str(bool(form.is_admin.data)),
                "password": form.password.data,
            }
        )
        flash("Пользователь создан", "success")
        return redirect(url_for("admin.users_list"))
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
    form = UserForm(data=user)
    if request.method == "GET":
        form.is_admin.data = str(user.get("is_admin", "")).lower() in {"true", "1", "yes"}
    if form.validate_on_submit():
        sheets_service.update_user(
            row_number,
            {
                "username": form.username.data,
                "email": form.email.data,
                "role": form.role.data,
                "is_admin": str(bool(form.is_admin.data)),
                "password": form.password.data,
            },
        )
        flash("Пользователь обновлен", "success")
        return redirect(url_for("admin.users_list"))
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
    return render_template("admin/templates.html", templates=templates)


@admin_bp.route("/templates/new", methods=["GET", "POST"])
@web_login_required
@admin_required
def templates_create():
    form = TemplateForm()
    if form.validate_on_submit():
        sheets_service.create_template(
            {
                "name": form.name.data,
                "category": form.category.data,
                "module": form.module.data,
                "lesson": form.lesson.data,
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
        sheets_service.update_template(
            row_number,
            {
                "name": form.name.data,
                "category": form.category.data,
                "module": form.module.data,
                "lesson": form.lesson.data,
                "post_text": form.post_text.data,
            },
        )
        flash("Шаблон обновлен", "success")
        return redirect(url_for("admin.templates_list"))
    return render_template("admin/template_form.html", form=form, mode="edit", row_number=row_number)


@admin_bp.route("/templates/<int:row_number>/delete", methods=["POST"])
@web_login_required
@admin_required
def templates_delete(row_number):
    sheets_service.delete_template(row_number)
    flash("Шаблон удален", "info")
    return redirect(url_for("admin.templates_list"))
