"""Bakery images must not pack venv + /usr/share: unpacking at container
start needs a writable root filesystem, which k8s/AWS may not provide."""

from pathlib import Path

from ..lib_composer import _strip_pack_libs_block

COMMON_DOCKER = (
    Path(__file__).resolve().parents[4] / "odoo" / "config" / "common.docker"
)


def test_common_docker_tar_steps_sit_inside_the_marker_block():
    text = COMMON_DOCKER.read_text()
    assert text.count("# MARKER PACK_LIBS BEGIN") == 1
    assert text.count("# MARKER PACK_LIBS END") == 1
    stripped = _strip_pack_libs_block(text)
    assert "> venv.tar.zst" not in stripped
    assert "> share.tar.zst" not in stripped
    assert "#___SNIPPET_TAR___" not in stripped


def test_strip_keeps_everything_around_the_block():
    text = (
        "RUN before\n"
        "# MARKER PACK_LIBS BEGIN\n"
        "RUN tar venv\n"
        "# MARKER PACK_LIBS END\n"
        "RUN after\n"
    )
    assert _strip_pack_libs_block(text) == "RUN before\nRUN after\n"
