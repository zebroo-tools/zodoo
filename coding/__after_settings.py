import secrets
import string


def generate_password(length=12):
    alphabet = string.ascii_letters + string.digits
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
    # Same rule as the dashboard and the log view: a real instance gets a
    # password of its own, DEVMODE stays open. The editor is a shell on this
    # machine -- an instance that reaches the internet must not serve it
    # without asking.
    if not settings.get("CODING_PASSWORD") and settings["DEVMODE"] != "1":
        settings["CODING_PASSWORD"] = generate_password(12)
        _persist(config, "CODING_PASSWORD", settings["CODING_PASSWORD"])
