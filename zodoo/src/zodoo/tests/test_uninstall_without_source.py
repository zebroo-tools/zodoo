"""Modules in the MANIFEST 'uninstall' list whose code is gone (#279).

Before, `odoo update all` crashed with a KeyError after the services were
already stopped. Now such a module is only uninstalled after explicit
approval - a module whose code is just missing by accident must never lose
its tables silently.
"""

from __future__ import annotations

import pytest

from zodoo import lib_module
from zodoo.module_tools import DBModules
from zodoo.module_tools import Module
from zodoo.module_tools import NotInAddonsPath


@pytest.fixture
def db(monkeypatch):
    """Fake database: installed modules and their installed dependents."""
    state = {"installed": {"gone_mod", "has_source"}, "dependents": {}}

    monkeypatch.setattr(
        DBModules,
        "is_module_installed",
        classmethod(lambda cls, m, **kw: m in state["installed"]),
    )
    monkeypatch.setattr(
        DBModules,
        "get_data_footprint",
        classmethod(lambda cls, m: (["x.gone"], 3)),
    )
    monkeypatch.setattr(
        DBModules,
        "get_installed_dependents",
        classmethod(lambda cls, m: state["dependents"].get(m, [])),
    )

    def get_by_name(cls, name, **kw):
        if name == "has_source":
            return object()
        # both lookup failures occur in practice, see #279
        if name == "gone_mod":
            raise KeyError(f"Module not found or not linked: {name}")
        raise NotInAddonsPath(name)

    monkeypatch.setattr(Module, "get_by_name", classmethod(get_by_name))
    return state


@pytest.fixture
def tty(monkeypatch):
    monkeypatch.setattr(lib_module.sys.stdin, "isatty", lambda: True)


def test_modules_with_source_need_no_confirmation(db):
    assert (
        lib_module._confirm_uninstall_without_source(["has_source"], {}, True)
        == []
    )


def test_non_interactive_aborts_instead_of_uninstalling(db):
    with pytest.raises(SystemExit):
        lib_module._confirm_uninstall_without_source(["gone_mod"], {}, True)


def test_manifest_key_approves(db):
    manifest = {"uninstall_without_source": ["gone_mod"]}
    assert lib_module._confirm_uninstall_without_source(
        ["gone_mod"], manifest, True
    ) == ["gone_mod"]


def test_prompt_requires_module_name(db, tty, monkeypatch):
    monkeypatch.setattr(lib_module.click, "prompt", lambda *a, **kw: "y")
    with pytest.raises(SystemExit):
        lib_module._confirm_uninstall_without_source(["gone_mod"], {}, False)

    monkeypatch.setattr(
        lib_module.click, "prompt", lambda *a, **kw: "gone_mod"
    )
    assert lib_module._confirm_uninstall_without_source(
        ["gone_mod"], {}, False
    ) == ["gone_mod"]


def test_installed_dependent_blocks_even_with_approval(db):
    db["dependents"]["gone_mod"] = ["still_used"]
    manifest = {"uninstall_without_source": ["gone_mod"]}
    with pytest.raises(SystemExit):
        lib_module._confirm_uninstall_without_source(
            ["gone_mod"], manifest, True
        )


def test_dependent_uninstalled_alongside_does_not_block(db):
    db["dependents"]["gone_mod"] = ["has_source"]
    manifest = {"uninstall_without_source": ["gone_mod"]}
    assert lib_module._confirm_uninstall_without_source(
        ["gone_mod", "has_source"], manifest, True
    ) == ["gone_mod"]


def test_dry_run_neither_prompts_nor_aborts(db):
    assert (
        lib_module._confirm_uninstall_without_source(
            ["gone_mod"], {}, False, dry_run=True
        )
        == []
    )


def test_descendant_check_keeps_only_approved_sourceless(db):
    assert lib_module._check_uninstall_descendants(
        ["gone_mod"], set(), approved_without_source=["gone_mod"]
    ) == ["gone_mod"]
    assert lib_module._check_uninstall_descendants(["gone_mod"], set()) == []
