import pytest

from zodoo import tools


@pytest.fixture
def plain_host(monkeypatch):
    """No /.dockerenv and a cgroup v2 root entry - what an EKS pod with
    containerd looks like, and also what a normal host looks like."""
    monkeypatch.setattr(tools.Path, "exists", lambda self: False)
    monkeypatch.setattr(tools.Path, "read_text", lambda self, *a, **kw: "0::/\n")
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)


def test_plain_host_is_not_a_container(plain_host):
    assert tools._is_in_container() is False


def test_kubernetes_pod_is_a_container(plain_host, monkeypatch):
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "172.20.0.1")
    assert tools._is_in_container() is True


def test_kubernetes_pod_reads_dbname_from_env(plain_host, monkeypatch):
    """The startup update asserts on config.dbname; without settings file
    the value has to come from the pod environment."""
    from zodoo.click_config import Config

    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "172.20.0.1")
    monkeypatch.setenv("DBNAME", "odoo")
    config = Config.__new__(Config)
    config.files = {}
    assert config.dbname == "odoo"
