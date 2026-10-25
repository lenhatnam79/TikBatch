import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication
from tikbatch.ui import Window


@pytest.fixture
def window(tmp_path, monkeypatch):
    monkeypatch.setenv("TIKBATCH_DATA_DIR", str(tmp_path / "settings"))
    app = QApplication.instance() or QApplication([])
    win = Window()
    yield win
    win.close()
    app.processEvents()


def result(**kw):
    return {"pending": 0, "active": 0, "done": 2, "failed": 0, "unsupported": 0,
            "folder": "/tmp/tikbatch", "stopped": False, "scan": "incomplete", "error": "Quét gián đoạn", **kw}


def test_window_constructs_and_busy_controls(window):
    assert window.background.isChecked()
    assert window.maximum.maximum() == 32
    window.busy(True)
    assert not window.start.isEnabled() and window.pause.isEnabled()
    window.busy(False)
    assert window.start.isEnabled() and not window.pause.isEnabled()


def test_incomplete_scan_is_visible_in_final_status(window):
    window.handle_event("finished", result())
    assert "CHƯA xác nhận hết kênh" in window.status.text()
    assert window.values["done"].text() == "2"


def test_stopped_progress_does_not_claim_all_done(window):
    window.handle_event("finished", result(pending=8, stopped=True))
    assert window.progress.maximum() == 10
    assert window.progress.value() == 2
    assert "Đã dừng" in window.status.text()


def test_access_denied_status_explains_why_run_paused(window):
    window.handle_event("finished", result(pending=8, error_code="access_denied", error="Access Denied"))
    assert "Đã tạm dừng do Access Denied" in window.status.text()
    assert "hàng đợi được giữ lại" in window.status.text()


def test_login_denial_preserves_specific_error(window, monkeypatch):
    from tikbatch.model import AccessDenied
    from tikbatch.ui import Job
    job = Job(window.root, "login", "https://www.tiktok.com/@example")
    events = []
    async def execute():
        raise AccessDenied("TikTok từ chối truy cập (Access Denied).")
    monkeypatch.setattr(job, "execute", execute)
    job.event.connect(lambda kind, data: events.append((kind, data)))
    job.run()
    assert events == [("error", "TikTok từ chối truy cập (Access Denied).")]
