"""Unit tests for services.storage.LocalArtifactStore."""

from pathlib import Path

from multi_agent_research_lab.services.storage import LocalArtifactStore


def test_write_text_creates_root_dir_and_returns_the_written_path(tmp_path: Path) -> None:
    root = tmp_path / "reports"
    store = LocalArtifactStore(root=root)

    path = store.write_text("trace.json", '{"ok": true}')

    assert path == root / "trace.json"
    assert path.read_text(encoding="utf-8") == '{"ok": true}'
    assert root.is_dir()


def test_write_text_creates_nested_parent_directories(tmp_path: Path) -> None:
    store = LocalArtifactStore(root=tmp_path / "reports")

    path = store.write_text("runs/2026-08-20/trace.json", "data")

    assert path.exists()
    assert path.read_text(encoding="utf-8") == "data"


def test_write_text_overwrites_an_existing_file(tmp_path: Path) -> None:
    store = LocalArtifactStore(root=tmp_path / "reports")
    store.write_text("trace.json", "first")
    path = store.write_text("trace.json", "second")

    assert path.read_text(encoding="utf-8") == "second"
