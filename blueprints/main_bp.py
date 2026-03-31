from flask import Blueprint, render_template, session

from auth import web_login_required
from forms.main_forms import PostForm
from services.sheets import sheets_service

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
@web_login_required
def index():
    return render_template(
        "test.html",
        form=PostForm(),
        page_title="Занятия",
        form_type="lessons",
        user=session.get("user", {}),
        channels=sheets_service.get_main_channels(),
    )


@main_bp.route("/test")
@web_login_required
def test_page():
    return render_template(
        "test.html",
        form=PostForm(),
        page_title="Занятия",
        form_type="lessons",
        user=session.get("user", {}),
        channels=sheets_service.get_main_channels(),
    )


@main_bp.route("/camp")
@web_login_required
def camp_page():
    return render_template(
        "camp.html",
        form=PostForm(),
        page_title="Каникулы",
        form_type="camp",
        user=session.get("user", {}),
        channels=sheets_service.get_camp_channels(),
    )
