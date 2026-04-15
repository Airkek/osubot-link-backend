from fastapi import Request

TEXT = {
    "en": {
        "title": "Link your osu! account",
        "subtitle": "Log in with osu! to get a one-time link code.",
        "button": "Continue with osu!",
        "success_title": "Link code ready",
        "success_subtitle": "Send {command} {code} in any chat with the bot to link your account.",
        "code_label": "Command",
        "copy": "Copy command",
        "copied": "Copied",
        "expires": "Code expires in {minutes} min.",
        "error_title": "Link failed",
        "error_subtitle": "Please try again later.",
        "missing_config": "Service is not configured.",
        "back": "Back",
    },
    "ru": {
        "title": "Привяжите аккаунт osu!",
        "subtitle": "Войдите через osu!, чтобы получить одноразовый код привязки.",
        "button": "Продолжить через osu!",
        "success_title": "Код привязки готов",
        "success_subtitle": "Отправьте {command} {code} в любом чате с ботом, чтобы привязать аккаунт.",
        "code_label": "Команда",
        "copy": "Скопировать команду",
        "copied": "Скопировано",
        "expires": "Код действует {minutes} мин.",
        "error_title": "Не удалось привязать",
        "error_subtitle": "Попробуйте еще раз позже.",
        "missing_config": "Сервис не настроен.",
        "back": "Назад",
    },
}


def select_locale(request: Request) -> str:
    accept = (request.headers.get("accept-language") or "").lower()
    if "ru" in accept:
        return "ru"
    return "en"


def tr(locale: str, key: str, **kwargs) -> str:
    dictionary = TEXT.get(locale) or TEXT["en"]
    template = dictionary.get(key, TEXT["en"].get(key, key))
    return template.format(**kwargs)
