APP_NAME = "Screenshot Builder"
APP_VERSION = "1.0.0"
APP_AUTHOR = "Thomas F Abrahamsson"
APP_COMPANY = "Alvega & Co AB"
APP_EMAIL = "Thomas@alvega.company"
APP_COPYRIGHT = f"(C) {APP_AUTHOR} at {APP_COMPANY} <{APP_EMAIL}>"


def banner() -> str:
    return f"{APP_NAME} v{APP_VERSION}  —  {APP_COPYRIGHT}"
