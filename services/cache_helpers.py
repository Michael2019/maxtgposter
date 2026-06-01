"""Хуки сброса кэшей, связанных с Google Sheets (без циклических импортов app ↔ sheets)."""

_template_change_hooks = []


def register_template_change_hook(callback):
    _template_change_hooks.append(callback)


def notify_template_changed():
    for callback in _template_change_hooks:
        try:
            callback()
        except Exception:
            pass
