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
