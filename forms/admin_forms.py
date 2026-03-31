from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email, Length, Optional


class UserForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), Length(min=2, max=64)])
    email = StringField("Email", validators=[Optional(), Email(), Length(max=120)])
    role = StringField("Role", validators=[DataRequired(), Length(max=64)])
    is_admin = BooleanField("Администратор")
    password = PasswordField("Новый пароль", validators=[Optional(), Length(min=4, max=128)])
    submit = SubmitField("Сохранить")


class TemplateForm(FlaskForm):
    name = StringField("Название", validators=[DataRequired(), Length(max=120)])
    category = StringField("Категория", validators=[Optional(), Length(max=120)])
    module = StringField("Модуль", validators=[Optional(), Length(max=32)])
    lesson = StringField("Занятие", validators=[Optional(), Length(max=32)])
    post_text = TextAreaField("Содержимое", validators=[DataRequired()])
    submit = SubmitField("Сохранить")
