from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional


class UserForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), Length(min=2, max=64)])
    email = StringField("Email", validators=[Optional(), Length(max=120)])
    name = StringField("Имя", validators=[DataRequired(), Length(max=64)])
    family = StringField("Фамилия", validators=[Optional(), Length(max=64)])
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


class ChannelForm(FlaskForm):
    name = StringField("Код канала", validators=[DataRequired(), Length(max=64)])
    label = StringField("Отображаемое название", validators=[DataRequired(), Length(max=128)])
    emoji = StringField("Эмодзи", validators=[Optional(), Length(max=8)])
    telegram_chat_id = StringField("Telegram chat id", validators=[DataRequired(), Length(max=64)])
    max_chat_id = StringField("MAX chat id", validators=[Optional(), Length(max=64)])
    submit = SubmitField("Сохранить")
