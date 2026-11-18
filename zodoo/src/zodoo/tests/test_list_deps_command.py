"""`odoo list-deps` must stay a command.

A refactoring put the helper `_compute_module_hash` between the click
decorators and `list_deps`. The decorators then registered the helper as
command "-compute-module-hash" and `odoo list-deps` was gone; CICD
test-runs, which compute module hashes with it, failed with
"No such command 'list-deps'".
"""

import click

from zodoo import lib_module


def test_list_deps_is_a_command():
    assert isinstance(lib_module.list_deps, click.Command)
    assert lib_module.list_deps.name == "list-deps"
    params = {p.name for p in lib_module.list_deps.params}
    assert {"module", "no_cache", "customs"} <= params


def test_list_deps_registered_in_module_group():
    commands = lib_module.odoo_module.commands
    assert commands.get("list-deps") is lib_module.list_deps
    assert "-compute-module-hash" not in commands


def test_compute_module_hash_is_a_plain_helper():
    # list_deps calls it with (config, data); as a click command it would fail
    assert not isinstance(lib_module._compute_module_hash, click.Command)
    assert callable(lib_module._compute_module_hash)
