from flask import Blueprint, render_template, session

from auth import web_login_required
from forms.main_forms import PostForm

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
@web_login_required
def index():
    return render_template("test.html", form=PostForm(), page_title="Основная форма", form_type="lessons", user=session.get("user", {}))


@main_bp.route("/test")
@web_login_required
def test_page():
    return render_template("test.html", form=PostForm(), page_title="Основная форма", form_type="lessons", user=session.get("user", {}))


@main_bp.route("/camp")
@web_login_required
def camp_page():
    return render_template("camp.html", form=PostForm(), page_title="Лагерная форма", form_type="camp", user=session.get("user", {}))
