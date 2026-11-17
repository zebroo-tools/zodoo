"""The baked Odoo image must not rewrite the whole source tree in a second
layer: a separate `RUN chown -R /opt/src` copies every file once more and
made the bake test stall for more than 20 minutes on the CI runner."""

import stat
from types import SimpleNamespace

from .. import lib_composer


def _config(tmp_path, customs):
    return SimpleNamespace(
        project_name="proj",
        HOST_CUSTOMS_DIR=customs,
        dirs={"run.build.odoo": tmp_path / "build"},
    )


def test_source_is_copied_with_owner_and_without_recursive_chown(tmp_path):
    customs = tmp_path / "customs"
    (customs / "odoo").mkdir(parents=True)
    (customs / "odoo" / "file.py").write_text("x")
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM scratch\n")

    lib_composer.append_odoo_src(_config(tmp_path, customs), dockerfile)

    content = dockerfile.read_text()
    assert "COPY --chown=odoo:odoo ./src/proj /opt/src" in content
    assert "chown -R" not in content
    assert "chmod -R" not in content


def test_build_context_is_world_readable(tmp_path):
    customs = tmp_path / "customs"
    (customs / "addons" / "mod").mkdir(parents=True)
    private_file = customs / "addons" / "mod" / "secret.py"
    private_file.write_text("x")
    private_file.chmod(0o600)
    (customs / "addons" / "mod").chmod(0o700)
    (customs / "link.py").symlink_to("addons/mod/secret.py")
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("")

    lib_composer.append_odoo_src(_config(tmp_path, customs), dockerfile)

    copied = tmp_path / "build" / "src" / "proj"
    file_mode = stat.S_IMODE(
        (copied / "addons" / "mod" / "secret.py").stat().st_mode
    )
    dir_mode = stat.S_IMODE((copied / "addons" / "mod").stat().st_mode)
    assert file_mode & 0o444 == 0o444
    assert file_mode & 0o111 == 0
    assert dir_mode & 0o555 == 0o555
    assert (copied / "link.py").is_symlink()
