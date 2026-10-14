import string
import secrets


def generate_password(length=12):
    # Characters: letters, digits, and punctuation
    alphabet = string.ascii_letters + string.digits
    # Use secrets.choice for cryptographically strong randomness
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _persist(config, key, value):
    """Write a generated secret to the project settings file.

    `settings` is the merged run file that every `odoo reload` rebuilds from
    scratch. A value set only there is rolled again on the next reload, and the
    password already handed out stops working.
    """
    files = getattr(config, "files", None) or {}
    if "project_settings" not in files:
        return
    from zodoo.tools import update_setting

    update_setting(config, key, value)


def after_settings(settings, config):
    if not settings.get("LOGS_PASSWORD") and settings["DEVMODE"] != "1":
        settings["LOGS_PASSWORD"] = generate_password(12)
        _persist(config, "LOGS_PASSWORD", settings["LOGS_PASSWORD"])
