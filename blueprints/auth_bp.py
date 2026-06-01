from flask import Blueprint, flash, redirect, render_template, request, session, url_for

import auth
from extensions import csrf
from forms.auth_forms import LoginForm

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
@csrf.exempt
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = auth.authenticate_user(form.username.data.strip(), form.password.data)
        if user:
            session["user"] = auth.user_for_session(user)
            flash("Успешный вход", "success")
            next_url = request.args.get("next")
            return redirect(next_url or url_for("main.index"))
        flash("Неверный логин или пароль", "danger")
    return render_template("login.html", form=form)


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Вы вышли из аккаунта", "info")
    return redirect(url_for("auth.login"))
