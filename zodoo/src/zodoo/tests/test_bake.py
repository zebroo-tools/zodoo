"""End-to-end test for the `odoo bake` flow.

Walks through the full user journey:

    odoo src init <path> <version>
    odoo reload
    odoo -f db reset
    odoo bakery bake KEY=VALUE ...

and verifies the bake artefact (`{project}.env`) and the docker images.

Heavy: requires Docker, gimera, network access (clones Odoo + addons).
Self-skips via `requires_full_stack` when Docker / `odoo` CLI is missing,
so it is safe to run as part of a plain `pytest` invocation.

Versions tested are taken from the `ZODOO_BAKE_TEST_VERSIONS` env var
(comma-separated, e.g. `15.0,19.0`); defaults to `19.0`.
"""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

from .conftest import _run, requires_full_stack

DEFAULT_VERSIONS = os.environ.get("ZODOO_BAKE_TEST_VERSIONS", "19.0").split(",")


def _project_image(project_name, service):
    """The image the project built for ``service`` (``<project>-<service>:``)."""
    result = subprocess.run(
        ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
        capture_output=True,
        text=True,
        check=True,
    )
    images = [
        line
        for line in result.stdout.splitlines()
        if f"{project_name}-{service}:" in line
    ]
    assert images, (
        f"no {service} image for project '{project_name}' found.\n"
        f"available:\n{result.stdout}"
    )
    return images[0]


def _service_environment(project_name, service):
    """Environment the generated compose file hands to ``service`` - in a
    Kubernetes deployment exactly these values come in as pod env."""
    compose = Path.home() / ".odoo" / "run" / project_name / "docker-compose.yml"
    environment = (
        yaml.safe_load(compose.read_text())["services"][service].get("environment")
        or {}
    )
    if isinstance(environment, list):
        environment = dict(item.split("=", 1) for item in environment)
    # --env-file is line based; the container entrypoint flattens multi-line
    # values the same way (see odoo_config.get_settings).
    return {
        k: "" if v is None else str(v).replace("\n", " ")
        for k, v in environment.items()
    }


def _project_network(project_name):
    result = subprocess.run(
        [
            "docker",
            "network",
            "ls",
            "--filter",
            f"label=com.docker.compose.project={project_name}",
            "--format",
            "{{.Name}}",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    networks = result.stdout.split()
    assert networks, f"no docker network for project '{project_name}'"
    return networks[0]


@pytest.fixture
def isolated_home():
    """Uses the real HOME — test relies on a unique project_name
    (``baketest<version>``) instead of HOME isolation, which had too
    many edge cases (missing docker cli-plugins, no gimera cache,
    settings file paths, ...).
    """
    yield Path.home()


@pytest.mark.slow
@requires_full_stack
@pytest.mark.parametrize("version", DEFAULT_VERSIONS)
def test_bake_flow(version, isolated_home, tmp_path):
    project_name = f"baketest{version.replace('.', '')}"
    # The dir name must match project_name because `make_customs` runs an
    # internal `odoo reload` without `-p`, which derives the project name
    # from the current directory.
    project_dir = tmp_path / project_name
    project_dir.mkdir()

    # 60 minute cap per heavy step; covers Odoo clone + docker build on cold
    # cache, including the Python-from-source compile in the prebuilt-python
    # image when ODOO_PYTHON_VERSION hasn't been pushed to the registry yet.
    long_timeout = 60 * 60
    # Streamed with a stall guard: a hanging step fails after 20 quiet minutes
    # and shows its last output, instead of burning the full hour silently.
    # Docker builds print a line at least per layer, so 20 minutes without any
    # output means stuck, not slow.
    heavy = dict(timeout=long_timeout, stream=True, stall_timeout=20 * 60)

    try:
        # 1) Initialise a fresh project. `odoo src init` ends with sys.exit(0)
        #    after running an internal `odoo reload`, so there is no need to
        #    invoke reload separately — but we do it again below to be explicit.
        _run(
            [
                "odoo",
                "-f",
                "-p",
                project_name,
                "src",
                "init",
                str(project_dir),
                version,
            ],
            cwd=project_dir.parent,
            **heavy,
        )

        # 2) Reload + build — init's internal reload runs without `-p`
        #    (derives project_name from cwd), then we need to build
        #    images so `db reset` can start postgres.
        _run(
            ["odoo", "-p", project_name, "reload"],
            cwd=project_dir,
            **heavy,
        )
        _run(
            ["odoo", "-p", project_name, "build", "--no-zodoo-pull"],
            cwd=project_dir,
            **heavy,
        )

        # 3) Reset database.
        _run(
            ["odoo", "-f", "-p", project_name, "db", "reset"],
            cwd=project_dir,
            **heavy,
        )

        # 4) Bake — this is the actual assertion target.
        _run(
            [
                "odoo",
                "-p",
                project_name,
                "bakery",
                "bake",
                # Pass any user-defined env override; the bake test
                # only verifies the .env file round-trip and that
                # docker images get tagged.
                "ODOO_DEMO=1",
            ],
            cwd=project_dir,
            **heavy,
        )

        # 5) Bake should have produced <project_name>.env in the customs dir.
        env_file = project_dir / f"{project_name}.env"
        assert env_file.exists(), f"bake did not create the env file at {env_file}"
        env_content = env_file.read_text()
        assert "ODOO_DEMO=1" in env_content
        assert "SHA_IN_DOCKER=1" in env_content
        assert "SRC_EXTRA=0" in env_content

        # 6) Like a release pipeline: change a setting after bake, reload and
        #    build the image that gets pushed. The bake settings must survive
        #    this (zodoo <= 12.10.5 lost ZODOO_EMBED here and the image had no
        #    /opt/zodoo).
        _run(
            ["odoo", "-p", project_name, "setting", "DOCKER_IMAGE_TAG=baketest"],
            cwd=project_dir,
        )
        _run(["odoo", "-p", project_name, "reload"], cwd=project_dir, **heavy)
        _run(
            ["odoo", "-p", project_name, "build", "--no-zodoo-pull"],
            cwd=project_dir,
            **heavy,
        )
        odoo_image = _project_image(project_name, "odoo")

        # 7) Start the image the way a Kubernetes pod does (EKS, containerd):
        #    real entrypoint, configuration only from the environment, no
        #    mounts, no /.dockerenv, cgroup v2 namespace showing only "0::/".
        #    The startup update must finish with exit code 0 against the
        #    project database (zodoo 12.10.7 failed here with "assert dbname").
        _run(["odoo", "-p", project_name, "up", "-d", "postgres"], cwd=project_dir)
        env = _service_environment(project_name, "odoo")
        env["KUBERNETES_SERVICE_HOST"] = "10.0.0.1"
        env["UPDATE_ON_STARTUP"] = "1"
        env_file = tmp_path / "pod.env"
        env_file.write_text("".join(f"{k}={v}\n" for k, v in env.items()))
        result = _run(
            [
                "docker",
                "run",
                "--rm",
                "--cgroupns",
                "private",
                "--network",
                _project_network(project_name),
                "--env-file",
                env_file,
                "--entrypoint",
                "/bin/bash",
                odoo_image,
                "-c",
                "rm -f /.dockerenv && "
                "exec /odoolib/entrypoint.sh /odoolib/update_on_startup.py",
            ],
            cwd=project_dir,
            check=False,
            **heavy,
        )
        output = result.stdout + result.stderr
        assert result.returncode == 0, (
            f"startup update failed in pod-like container "
            f"(exit {result.returncode}):\n{output[-4000:]}"
        )
        # Regression guards for the root -> sudo -u odoo chain
        # (fix/chown-config-files-recursive,
        # fix/sudo-odoo-cmd-skip-when-already-odoo).
        assert "PermissionError" not in output, output[-2000:]
        assert "not in the sudoers file" not in output, output[-2000:]

    finally:
        # Best-effort teardown so a failed run does not leave containers behind.
        subprocess.run(
            ["odoo", "-p", project_name, "down", "-v"],
            cwd=str(project_dir),
            timeout=300,
        )
