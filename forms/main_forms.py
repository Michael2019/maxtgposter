from flask_wtf import FlaskForm
from wtforms import FileField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Optional


class PostForm(FlaskForm):
    user_text = TextAreaField("Текст поста", validators=[Optional()])
    category = StringField("Категория", validators=[Optional()])
    module = StringField("Модуль", validators=[Optional()])
    lesson = StringField("Занятие", validators=[Optional()])
    weekday = SelectField(
        "День недели",
        choices=[("", "—"), ("Понедельник", "Понедельник"), ("Вторник", "Вторник"), ("Среда", "Среда"), ("Четверг", "Четверг"), ("Пятница", "Пятница"), ("Суббота", "Суббота"), ("Воскресенье", "Воскресенье")],
        validators=[Optional()],
    )
    time = StringField("Время", validators=[Optional()])
    chat_id = StringField("Telegram chat id", validators=[DataRequired()])
    max_chat_id = StringField("MAX chat id", validators=[Optional()])
    media_files = FileField("Медиафайл", validators=[Optional()])
    submit = SubmitField("Отправить")
