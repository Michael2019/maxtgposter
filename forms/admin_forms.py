from typing import Optional, Tuple

from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional as OptionalValidator

# Синхронно со страницей «Занятия» (templates/test.html)
VALID_TEMPLATE_CATEGORIES = frozenset(
    {
        "Робототехника ПМ4",
        "Робототехника ПМ5",
        "Робототехника 0ст",
        "Робототехника 1ст",
        "Робототехника 2ст",
        "Робототехника 3ст",
        "Робототехника 4ст",
        "Робототехника 5ст",
        "Робототехника 6ст",
        "Робототехника 7ст",
        "Робототехника 8ст",
        "Робик 1",
        "Робик 2",
        "Scratch",
        "Python",
        "ОЛиП NEW",
        "ОЛиП",
        "Хакер",
        "Юнити",
    }
)

ROBIK_MONTHS = (
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
)


def validate_template_location(category: str, module: str, lesson: str) -> Tuple[bool, Optional[str]]:
    """Проверка соответствия категории, модуля и занятия правилам формы «Занятия»."""
    category = (category or "").strip()
    module = (module or "").strip()
    lesson = (lesson or "").strip()
    if not category:
        return False, "Выберите категорию"
    if category not in VALID_TEMPLATE_CATEGORIES:
        return False, "Недопустимая категория"
    if not module:
        return False, "Выберите модуль"
    if not lesson:
        return False, "Выберите занятие"

    if category in ("Робик 1", "Робик 2"):
        if module not in ROBIK_MONTHS:
            return False, "Недопустимый модуль для Робик"
        max_lesson = 5
    else:
        if module not in ("1", "2"):
            return False, "Недопустимый модуль"
        max_lesson = 17 if module == "1" else 20

    try:
        n = int(lesson)
    except (TypeError, ValueError):
        return False, "Недопустимое занятие"
    if n < 1 or n > max_lesson:
        return False, "Недопустимое занятие"
    return True, None


class UserForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), Length(min=2, max=64)])
    email = StringField("Email", validators=[OptionalValidator(), Length(max=120)])
    name = StringField("Имя", validators=[DataRequired(), Length(max=64)])
    family = StringField("Фамилия", validators=[OptionalValidator(), Length(max=64)])
    is_admin = BooleanField("Администратор")
    password = PasswordField("Новый пароль", validators=[OptionalValidator(), Length(min=4, max=128)])
    submit = SubmitField("Сохранить")


class TemplateForm(FlaskForm):
    name = StringField("Название", validators=[DataRequired(), Length(max=120)])
    post_text = TextAreaField("Содержимое", validators=[DataRequired()])
    submit = SubmitField("Сохранить")


class ChannelForm(FlaskForm):
    name = StringField("Код канала", validators=[DataRequired(), Length(max=64)])
    label = StringField("Отображаемое название", validators=[DataRequired(), Length(max=128)])
    emoji = StringField("Эмодзи", validators=[OptionalValidator(), Length(max=8)])
    telegram_chat_id = StringField("Telegram chat id", validators=[DataRequired(), Length(max=64)])
    max_chat_id = StringField("MAX chat id", validators=[OptionalValidator(), Length(max=64)])
    submit = SubmitField("Сохранить")
