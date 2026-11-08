import subprocess
import sys
import urllib.request

import pytest

from hydra import desktop
from test_wiki import dynasty


def test_desktop_serves_existing_wiki_and_closes_with_shell(tmp_path, monkeypatch):
    root = dynasty(tmp_path)
    shell = tmp_path / "hydra-desktop.exe"
    shell.touch()
    seen = []

    def run(args, **kwargs):
        assert args[0] == str(shell)
        seen.append(args[1])
        with urllib.request.urlopen(args[1], timeout=5) as response:
            html = response.read().decode()
        assert "Old King" in html
        assert "@view-transition{navigation:auto}" in html
        assert "hydra-windowbar" not in html
        with urllib.request.urlopen(args[1] + "wiki.css", timeout=5) as response:
            assert response.headers.get_content_type() == "text/css"
        return 0

    monkeypatch.setattr(desktop, "run_shell", run)
    assert desktop.launch(root, shell) == 0
    with pytest.raises(OSError):
        urllib.request.urlopen(seen[0], timeout=1)


def test_desktop_closes_server_when_shell_fails(tmp_path, monkeypatch):
    root = dynasty(tmp_path)
    shell = tmp_path / "hydra-desktop.exe"
    shell.touch()
    seen = []

    def run(args, **kwargs):
        seen.append(args[1])
        raise OSError("cannot start shell")

    monkeypatch.setattr(desktop, "run_shell", run)
    with pytest.raises(OSError, match="cannot start shell"):
        desktop.launch(root, shell)
    with pytest.raises(OSError):
        urllib.request.urlopen(seen[0], timeout=1)


def test_shell_exit_code_and_timeout():
    assert desktop.run_shell([sys.executable, "-c", "raise SystemExit(7)"]) == 7
    with pytest.raises(subprocess.TimeoutExpired):
        desktop.run_shell([sys.executable, "-c", "import time; time.sleep(60)"], timeout=0.1)


def test_missing_shell_fails_before_opening_archive(tmp_path):
    with pytest.raises(FileNotFoundError, match="Build the Saucer shell"):
        desktop.launch(tmp_path / "not-an-archive", tmp_path / "missing.exe")


def test_stale_archive_is_not_rebuilt_without_permission(tmp_path, monkeypatch):
    root = dynasty(tmp_path)
    shell = tmp_path / "hydra-desktop.exe"
    shell.touch()
    monkeypatch.setattr(desktop.ubuild, "pages_current", lambda root: False)
    monkeypatch.setattr(desktop.ubuild, "build", lambda root: pytest.fail("must not rebuild"))
    with pytest.raises(ValueError, match="--build"):
        desktop.launch(root, shell)


def test_cancel_archive_selection_does_not_launch(monkeypatch):
    monkeypatch.setattr(desktop, "pick_archive", lambda: "")
    monkeypatch.setattr(desktop, "launch", lambda *args, **kwargs: pytest.fail("must not launch"))
    assert desktop.main([]) == 0
