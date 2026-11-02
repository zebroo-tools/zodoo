"""`odoo bakery bake` must keep its build-relevant settings beyond the
one-shot reload, otherwise a later `odoo reload` (e.g. the implicit one of
`odoo setting HUB_URL=...`) builds an image without the zodoo source."""

from types import SimpleNamespace

from ..lib_bakery import _persist_bake_settings
from ..myconfigparser import MyConfigParser


def test_bake_persists_zodoo_embed_and_src_extra(tmp_path):
    settings_file = tmp_path / "settings"
    settings_file.write_text("ZODOO_EMBED=0\nHUB_URL=registry.example\n")
    config = SimpleNamespace(files={"project_settings": settings_file})

    _persist_bake_settings(
        config, {"SRC_EXTRA": "0", "ZODOO_EMBED": "1", "DBNAME": "x"}
    )

    settings = MyConfigParser(settings_file)
    assert settings["ZODOO_EMBED"] == "1"
    assert settings["SRC_EXTRA"] == "0"
    assert settings["HUB_URL"] == "registry.example"
    assert "DBNAME" not in settings.keys()


def test_bake_keeps_explicit_override(tmp_path):
    settings_file = tmp_path / "settings"
    settings_file.write_text("")
    config = SimpleNamespace(files={"project_settings": settings_file})

    _persist_bake_settings(config, {"SRC_EXTRA": "0", "ZODOO_EMBED": "0"})

    assert MyConfigParser(settings_file)["ZODOO_EMBED"] == "0"
