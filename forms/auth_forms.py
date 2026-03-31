from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Length


class LoginForm(FlaskForm):
    username = StringField("Логин", validators=[DataRequired(), Length(min=2, max=64)])
    password = PasswordField("Пароль", validators=[DataRequired(), Length(min=4, max=128)])
    submit = SubmitField("Войти")
