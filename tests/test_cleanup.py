"""Cleaning up screenshots, logs, reports and bundles."""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sweeper import cleanup  # noqa: E402


def make(root: Path, name: str, size: int = 100, days_old: float = 0) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    when = time.time() - days_old * cleanup.DAY
    os.utime(path, (when, when))
    return path


def populate(root: Path):
    make(root, "logs/shots/a.png", 1000, days_old=40)
    make(root, "logs/shots/b.png", 2000, days_old=1)
    make(root, "logs/audit.log", 500, days_old=0)
    make(root, "logs/report-1.html", 300, days_old=60)
    make(root, "logs/changes-1.jsonl", 50, days_old=60)
    make(root, "logs/rules-1.json", 50, days_old=60)
    make(root, "diagnostics/20260101-000000/audit.log", 400, days_old=100)
    make(root, "settings.json", 10, days_old=100)
    make(root, "history.json", 10, days_old=100)


def test_scan_counts_each_category(tmp_path):
    populate(tmp_path)
    found = cleanup.scan(tmp_path)
    assert (found["screenshots"].files, found["screenshots"].bytes) == (2, 3000)
    assert found["changes"].files == 2
    assert found["diagnostics"].files == 1 and found["diagnostics"].bytes == 400
    assert found["runlog"].files == 0


def test_everything_removes_screenshots_and_empties_logs(tmp_path):
    populate(tmp_path)
    result = cleanup.clean(tmp_path, ["screenshots", "audit"], None)
    assert result.files == 3 and result.bytes == 3500 and not result.errors
    assert not list((tmp_path / "logs" / "shots").glob("*.png"))
    assert (tmp_path / "logs" / "audit.log").exists()  # emptied, not removed
    assert (tmp_path / "logs" / "audit.log").stat().st_size == 0


def test_an_age_keeps_recent_files(tmp_path):
    populate(tmp_path)
    result = cleanup.clean(tmp_path, ["screenshots", "audit"], 30)
    assert result.files == 1  # only the 40 day old screenshot
    assert (tmp_path / "logs" / "shots" / "b.png").exists()
    assert (tmp_path / "logs" / "audit.log").stat().st_size == 500  # written today, so not old


def test_a_dry_run_counts_and_removes_nothing(tmp_path):
    populate(tmp_path)
    result = cleanup.clean(tmp_path, ["screenshots", "audit"], None, dry_run=True)
    assert result.files == 3 and result.bytes == 3500
    assert len(list((tmp_path / "logs" / "shots").glob("*.png"))) == 2
    assert (tmp_path / "logs" / "audit.log").stat().st_size == 500


def test_bundles_are_removed_whole(tmp_path):
    populate(tmp_path)
    result = cleanup.clean(tmp_path, ["diagnostics"], 30)
    assert result.files == 1
    assert not (tmp_path / "diagnostics" / "20260101-000000").exists()


def test_settings_and_history_are_never_touched(tmp_path):
    populate(tmp_path)
    cleanup.clean(tmp_path, list(cleanup.CATEGORIES), None)
    assert (tmp_path / "settings.json").exists() and (tmp_path / "history.json").exists()


def test_a_file_that_cannot_go_is_reported_and_the_rest_carries_on(tmp_path, monkeypatch):
    populate(tmp_path)
    real = Path.unlink

    def refuse(self, *a, **k):
        if self.name == "a.png":
            raise PermissionError(13, "Permission denied")
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", refuse)
    result = cleanup.clean(tmp_path, ["screenshots"], None)
    assert result.files == 1 and result.errors == ["a.png: Permission denied"]


def test_sizes_and_summary_read_plainly():
    assert cleanup.human_size(512) == "512 B"
    assert cleanup.human_size(2048) == "2.0 KB"
    assert cleanup.summary_line(cleanup.Found(0, 0)) == "Empty"
    assert cleanup.summary_line(cleanup.Found(1, 2048)) == "1 item, 2.0 KB"
    assert cleanup.summary_line(cleanup.Found(3, 2048)) == "3 items, 2.0 KB"


def test_an_emptied_log_is_not_counted_and_change_records_have_their_own_button(tmp_path):
    make(tmp_path, "logs/audit.log", 0)
    make(tmp_path, "logs/changes-1.jsonl", 10)
    assert cleanup.scan(tmp_path)["audit"].files == 0
    assert "changes" not in cleanup.GROUP_KEYS and "screenshots" in cleanup.GROUP_KEYS
    assert "All time" in cleanup.AGES and "Everything" not in cleanup.AGES
