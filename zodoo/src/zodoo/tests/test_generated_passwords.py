"""Generated gate passwords must survive the next `odoo reload`.

The run settings file is rebuilt from scratch on every reload. A password that
only lands there is rolled again each time, so the one already handed out
(dashboard, log view, editor) stops working after any update.
"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]

CASES = [
    ("dashboard", "DASHBOARD_PASSWORD"),
    ("logsio_web", "LOGS_PASSWORD"),
    ("coding", "CODING_PASSWORD"),
]


def _after_settings(service):
    path = REPO_ROOT / service / "__after_settings.py"
    spec = importlib.util.spec_from_file_location(f"{service}_after", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.after_settings


def _config(tmp_path):
    project_settings = tmp_path / "settings.proj"
    project_settings.write_text("")
    return SimpleNamespace(files={"project_settings": project_settings})


def _read(path):
    from zodoo.myconfigparser import MyConfigParser

    return MyConfigParser(path)


@pytest.mark.parametrize("service,key", CASES)
def test_generated_password_is_persisted(tmp_path, service, key):
    config = _config(tmp_path)
    settings = {"DEVMODE": "0"}
    _after_settings(service)(settings, config)

    assert len(settings[key]) == 12
    assert _read(config.files["project_settings"])[key] == settings[key]


@pytest.mark.parametrize("service,key", CASES)
def test_existing_password_is_left_alone(tmp_path, service, key):
    config = _config(tmp_path)
    settings = {"DEVMODE": "0", key: "handed-out"}
    _after_settings(service)(settings, config)

    assert settings[key] == "handed-out"
    assert key not in _read(config.files["project_settings"]).keys()


@pytest.mark.parametrize("service,key", CASES)
def test_devmode_stays_open_and_writes_nothing(tmp_path, service, key):
    config = _config(tmp_path)
    settings = {"DEVMODE": "1"}
    _after_settings(service)(settings, config)

    assert not settings.get(key)
    assert key not in _read(config.files["project_settings"]).keys()
