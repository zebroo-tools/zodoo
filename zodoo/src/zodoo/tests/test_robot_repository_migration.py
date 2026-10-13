# Part of Zebroo GmbH. See LICENSE file for full copyright and licensing details (www.zebroo.de/license).
"""Robot setup stays idempotent across the repository transfer."""

import inspect
from types import SimpleNamespace

import pytest
import yaml

from zodoo import lib_robot
from zodoo import odoo_config


def run_setup(tmp_path, monkeypatch, repos):
    config_file = tmp_path / "gimera.yml"
    config_file.write_text(yaml.safe_dump({"repos": repos}))
    monkeypatch.setattr(odoo_config, "customs_dir", lambda: tmp_path)
    monkeypatch.setattr(
        odoo_config,
        "MANIFEST",
        lambda: {"install": [], "addons_paths": []},
    )
    monkeypatch.setattr(lib_robot, "_setup_robot_env", lambda *args: None)
    monkeypatch.setenv("SILENT_ROBOT_SETUP", "1")
    monkeypatch.setenv("GIMERA_NO_PRECOMMIT", "0")
    context = SimpleNamespace(invoke=lambda *args, **kwargs: None)
    setup = inspect.unwrap(lib_robot.setup.callback)
    setup(context, SimpleNamespace())
    setup(context, SimpleNamespace())
    return yaml.safe_load(config_file.read_text())["repos"]


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:zebroo-tools/odoo-robot_utils.git",
        "https://github.com/zebroo-tools/odoo-robot_utils",
        "git@github.com:Odoo-Ninjas/odoo-robot_utils",
        "https://github.com/Odoo-Ninjas/odoo-robot_utils.git",
        "git@github.com:marcwimmer/odoo-robot_utils.git",
    ],
)
def test_setup_preserves_existing_repository_and_pin(
    tmp_path, monkeypatch, url
):
    existing = {
        "url": url,
        "path": "custom_robot_path",
        "branch": "15.0",
        "sha": "0123456789abcdef0123456789abcdef01234567",
        "type": "integrated",
    }
    assert run_setup(tmp_path, monkeypatch, [existing]) == [existing]


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/Odoo-Ninjas/odoo-robot_utils_common.git",
        "https://example.org/Odoo-Ninjas/odoo-robot_utils.git",
        "https://github.com/another-owner/odoo-robot_utils.git",
    ],
)
def test_setup_keeps_unrelated_repositories_and_adds_canonical_one(
    tmp_path, monkeypatch, url
):
    unrelated = {"url": url, "path": "other", "branch": "main"}
    repos = run_setup(tmp_path, monkeypatch, [unrelated])
    assert repos[0] == unrelated
    assert len(repos) == 2
    assert repos[1] == {
        "branch": "main",
        "path": "addons_robot",
        "type": "integrated",
        "url": "git@github.com:zebroo-tools/odoo-robot_utils",
    }
