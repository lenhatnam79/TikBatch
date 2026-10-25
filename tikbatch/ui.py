from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices, QFont
from PySide6.QtWidgets import (QApplication, QCheckBox, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from .engine import Engine
from .locking import FileLock
from .model import SourceError, data_dir, profile_url, worker_command
from .sources import browser_login


STYLE = """
QWidget { background: #10191f; color: #e8eef0; font-size: 13px; }
QLabel#brand { color: #61e0bc; font-size: 14px; font-weight: 700; }
QLabel#title { font-size: 29px; font-weight: 700; }
QLabel#muted { color: #9baeb7; }
QLabel#value { font-size: 27px; font-weight: 700; color: #ecf8f3; }
QFrame#card { background: #19262e; border: 1px solid #2c3b44; border-radius: 12px; }
QFrame#card QLabel { background: transparent; }
QLineEdit, QSpinBox, QComboBox { background: #0d151a; border: 1px solid #344750;
    border-radius: 7px; padding: 10px; min-height: 18px; }
QLineEdit:focus { border: 1px solid #61e0bc; }
QPushButton { background: #253640; border: 1px solid #3a515d; border-radius: 7px; padding: 10px 14px; }
QPushButton:hover { background: #344c59; }
QPushButton#primary { color: #10251e; background: #61e0bc; border: 0; font-weight: 700; }
QPushButton:disabled { color: #657983; background: #1c2931; border-color: #283942; }
QPlainTextEdit { background: #0d151a; border: 1px solid #2c3b44; border-radius: 8px; padding: 10px; }
QProgressBar { background: #0d151a; border: 0; border-radius: 4px; height: 8px; }
QProgressBar::chunk { background: #61e0bc; border-radius: 4px; }
QToolTip { background: #253640; color: white; border: 0; }
"""


class Job(QThread):
    event = Signal(str, object)

    def __init__(self, root, mode, url, output=None, maximum=16, headless=True):
        super().__init__()
        self.root, self.mode, self.url, self.output = root, mode, url, output
        self.maximum = maximum
        self.headless = headless
        self.stop = threading.Event()

    def run(self):
        try:
            asyncio.run(self.execute())
        except Exception as e:
            # No raw network errors, URLs with query strings or browser diagnostics.
            message = (str(e) if isinstance(e, SourceError) or
                       (isinstance(e, (ValueError, RuntimeError)) and len(str(e)) < 200)
                       else "Tác vụ gặp lỗi. Hãy kiểm tra kết nối, thư mục và trạng thái trình duyệt.")
            self.event.emit("error", message)

    async def execute(self):
        emit = self.event.emit
        if self.mode == "download":
            await Engine(self.root, emit, self.stop, self.maximum, headless=self.headless).run(self.url, self.output)
        elif self.mode == "login":
            with FileLock(self.root / ".session.lock"):
                await browser_login(self.root, self.url, emit, self.stop)
            emit("log", "Đã đóng cửa sổ TikTok. Phiên truy cập được giữ trên máy.")
        elif self.mode == "install":
            emit("log", "Đang cài Chromium miễn phí. Lần đầu cần tải trình duyệt qua Internet…")
            proc = await asyncio.create_subprocess_exec(*worker_command("install-browser"),
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            try:
                while proc.returncode is None:
                    if self.stop.is_set():
                        proc.terminate()
                        await proc.wait()
                        return
                    try:
                        await asyncio.wait_for(proc.wait(), .5)
                    except asyncio.TimeoutError:
                        pass
                if proc.returncode:
                    raise RuntimeError("Cài Chromium chưa thành công. Kiểm tra Internet và phiên bản hệ điều hành rồi thử lại.")
                emit("log", "Đã cài Chromium. Bạn có thể bắt đầu tải hoặc mở TikTok để đăng nhập.")
            finally:
                if proc.returncode is None:
                    proc.terminate()
                    await proc.wait()


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.root = data_dir()
        self.settings = QSettings(str(self.root / "settings.ini"), QSettings.IniFormat)
        self.job = None
        self.closing = False
        self.folder = None
        self.setWindowTitle("TikBatch 0.2.2 · Tải video theo kênh")
        self.resize(1100, 820)
        self.setMinimumSize(920, 760)
        container = QWidget()
        self.setCentralWidget(container)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(30, 25, 30, 25)
        layout.setSpacing(15)
        brand = QLabel("TIKBATCH  /  LOCAL DOWNLOADER")
        brand.setObjectName("brand")
        layout.addWidget(brand)
        title = QLabel("Một kênh. Một thư mục.")
        title.setObjectName("title")
        layout.addWidget(title)
        subtitle = QLabel("Tải song song · Lưu tiến độ · Ưu tiên nguồn phát không logo · Không nén lại")
        subtitle.setObjectName("muted")
        layout.addWidget(subtitle)
        form = QFrame()
        form.setObjectName("card")
        grid = QGridLayout(form)
        grid.setContentsMargins(18, 17, 18, 17)
        grid.setSpacing(10)
        grid.addWidget(QLabel("LINK KÊNH TIKTOK"), 0, 0, 1, 3)
        self.url = QLineEdit(self.settings.value("url", "https://www.tiktok.com/@hong_le_"))
        self.url.setPlaceholderText("https://www.tiktok.com/@tenkenh")
        grid.addWidget(self.url, 1, 0, 1, 3)
        grid.addWidget(QLabel("THƯ MỤC LƯU"), 2, 0, 1, 3)
        default = QStandardPaths.writableLocation(QStandardPaths.DownloadLocation)
        self.output = QLineEdit(self.settings.value("output", str(Path(default) / "TikBatch")))
        grid.addWidget(self.output, 3, 0, 1, 2)
        self.browse = QPushButton("Chọn thư mục…")
        self.browse.clicked.connect(self.choose)
        grid.addWidget(self.browse, 3, 2)
        self.maximum = QSpinBox()
        self.maximum.setRange(1, 32)
        self.maximum.setValue(int(self.settings.value("maximum", 16)))
        self.maximum.setPrefix("Tối đa ")
        self.maximum.setSuffix(" video đồng thời")
        self.maximum.setToolTip("Bắt đầu tối đa 8, sau đó tự điều chỉnh theo tốc độ mạng. Tối đa 32 video; lấy nguồn có giới hạn riêng.")
        grid.addWidget(self.maximum, 4, 0)
        quality = QLabel("Nguồn phát tốt nhất truy cập được · MP4 + âm thanh")
        quality.setObjectName("muted")
        grid.addWidget(quality, 4, 1, 1, 2)
        self.background = QCheckBox("Chạy ngầm — không mở cửa sổ TikTok khi tải")
        self.background.setChecked(self.settings.value("headless", True, type=bool))
        grid.addWidget(self.background, 5, 0, 1, 3)
        grid.setColumnStretch(1, 1)
        layout.addWidget(form)
        buttons = QHBoxLayout()
        self.start = QPushButton("Bắt đầu / Tiếp tục")
        self.start.setObjectName("primary")
        self.start.clicked.connect(lambda: self.launch("download"))
        self.pause = QPushButton("Dừng và lưu tiến độ")
        self.pause.setEnabled(False)
        self.pause.clicked.connect(self.stop)
        self.open_folder = QPushButton("Mở thư mục")
        self.open_folder.clicked.connect(self.reveal)
        buttons.addWidget(self.start)
        buttons.addWidget(self.pause)
        buttons.addStretch()
        buttons.addWidget(self.open_folder)
        layout.addLayout(buttons)
        stats = QHBoxLayout()
        self.values = {}
        for key, text in [("total", "ĐÃ TÌM THẤY"), ("done", "ĐÃ LƯU"), ("speed", "TỐC ĐỘ"), ("limit", "SONG SONG"), ("failed", "THẤT BẠI")]:
            card = QFrame()
            card.setObjectName("card")
            box = QVBoxLayout(card)
            box.setContentsMargins(15, 12, 15, 12)
            label = QLabel(text)
            label.setObjectName("muted")
            value = QLabel("—")
            value.setObjectName("value")
            box.addWidget(label)
            box.addWidget(value)
            self.values[key] = value
            stats.addWidget(card)
        layout.addLayout(stats)
        self.status = QLabel("Sẵn sàng. Chọn thư mục và bắt đầu tải.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(1200)
        self.log.setMinimumHeight(100)
        self.log.setPlaceholderText("Tiến độ và các lỗi cần xử lý sẽ xuất hiện tại đây.")
        layout.addWidget(self.log, 1)
        bottom = QHBoxLayout()
        self.install = QPushButton("Cài trình duyệt (lần đầu)")
        self.install.clicked.connect(lambda: self.launch("install"))
        self.login = QPushButton("Mở TikTok / Xác minh")
        self.login.clicked.connect(lambda: self.launch("login"))
        bottom.addWidget(self.install)
        bottom.addWidget(self.login)
        bottom.addStretch()
        badge = QLabel("MIỄN PHÍ · LƯU TRÊN MÁY")
        badge.setObjectName("muted")
        bottom.addWidget(badge)
        layout.addLayout(bottom)
        note = QLabel("Phiên đăng nhập được lưu riêng trên máy. Nguồn phát không đồng nghĩa file gốc chủ kênh; logo có sẵn trong nội dung được giữ nguyên.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)

    def choose(self):
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu video", self.output.text())
        if folder:
            self.output.setText(folder)

    def reveal(self):
        folder = self.folder or Path(self.output.text()).expanduser()
        if folder.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def launch(self, mode):
        if self.job and self.job.isRunning():
            return
        try:
            _, url = profile_url(self.url.text())
            output = Path(self.output.text()).expanduser()
            if mode == "download":
                if not self.output.text().strip() or not output.is_absolute():
                    raise ValueError("Chọn đường dẫn thư mục đầy đủ để lưu video.")
                output.mkdir(parents=True, exist_ok=True)
                if not os.access(output, os.W_OK):
                    raise ValueError("Không có quyền ghi vào thư mục đã chọn.")
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, "Kiểm tra thông tin", str(e))
            return
        for key, value in {"url": url, "output": str(output), "maximum": self.maximum.value(),
                           "headless": self.background.isChecked()}.items():
            self.settings.setValue(key, value)
        self.job = Job(self.root, mode, url, output, self.maximum.value(), self.background.isChecked())
        self.job.event.connect(self.handle_event)
        self.job.finished.connect(self.idle)
        self.busy(True)
        self.status.setText({"download": "Đang quét kênh và chuẩn bị hàng đợi…", "login": "Đang mở TikTok…", "install": "Đang cài trình duyệt…"}[mode])
        self.progress.setRange(0, 0)
        self.job.start()

    def busy(self, yes):
        for widget in [self.start, self.install, self.login, self.url, self.output, self.browse, self.maximum, self.background]:
            widget.setEnabled(not yes)
        self.pause.setEnabled(yes)

    def stop(self):
        if self.job:
            self.job.stop.set()
            self.pause.setEnabled(False)
            self.status.setText("Đang dừng an toàn và lưu tiến độ…")

    def idle(self):
        self.busy(False)
        if self.job.mode != "download":
            self.progress.setRange(0, 100)
            self.status.setText("Tác vụ đã kết thúc. Xem nhật ký bên dưới.")
        if self.closing:
            self.close()

    def handle_event(self, kind, data):
        if kind == "log":
            self.log.appendPlainText(data)
        elif kind == "error":
            self.status.setText(data)
            self.log.appendPlainText(data)
            self.progress.setRange(0, 100)
        elif kind == "stats":
            total = sum(data[k] for k in ("pending", "active", "done", "failed", "unsupported"))
            for key, value in {"total": total, "done": data["done"], "failed": data["failed"],
                               "speed": f"{data['speed'] / 1048576:.1f} MB/s", "limit": data["limit"]}.items():
                self.values[key].setText(str(value))
            self.folder = Path(data["folder"])
            scan = "Đang quét kênh" if data["scan"] == "scanning" else "Đã tới cuối danh sách nguồn" if data["scan"].startswith("source_end") else "Quét chưa hoàn tất"
            text = f"{scan} · Chờ {data['pending']} · Đang xử lý {data['active']} · Bài ảnh {data['unsupported']}"
            if data["cooldown"]:
                text += f" · Chờ nguồn {data['cooldown']:.0f}s"
            self.status.setText(text)
            if data["scan"] != "scanning":
                self.progress.setRange(0, max(total, 1))
                self.progress.setValue(data["done"] + data["failed"] + data["unsupported"])
        elif kind == "finished":
            self.folder = Path(data["folder"])
            prefix = "Đã dừng, tiến độ được lưu" if data["stopped"] else "Đã kết thúc lượt chạy"
            if data.get("error_code") == "access_denied":
                prefix = "Đã tạm dừng do Access Denied, hàng đợi được giữ lại"
            if data.get("error_code") == "needs_captcha":
                prefix = "Đã tạm dừng chờ bạn xác minh CAPTCHA, hàng đợi được giữ lại"
            scan = "nguồn báo hết danh sách" if data["scan"].startswith("source_end") else "CHƯA xác nhận hết kênh"
            message = f"{prefix}: {data['done']} đã lưu, {data['failed']} lỗi, {data['unsupported']} bài ảnh; {scan}."
            if data["error"]:
                message += " " + data["error"]
            for key in ("done", "failed"):
                self.values[key].setText(str(data[key]))
            total = sum(data[k] for k in ("pending", "active", "done", "failed", "unsupported"))
            self.values["total"].setText(str(total))
            self.values["speed"].setText("0.0 MB/s")
            self.progress.setRange(0, max(total, 1))
            self.progress.setValue(data["done"] + data["failed"] + data["unsupported"])
            self.status.setText(message)
            self.log.appendPlainText(message + "\nKết quả: " + str(self.folder / "ket-qua.csv"))

    def closeEvent(self, event: QCloseEvent):
        if self.job and self.job.isRunning():
            self.closing = True
            self.stop()
            event.ignore()
        else:
            event.accept()


def launch(screenshot=None):
    app = QApplication.instance() or QApplication([])
    app.setFont(QFont("Arial", 12))
    app.setStyleSheet(STYLE)
    window = Window()
    window.show()
    if screenshot:
        def capture():
            window.grab().save(str(screenshot))
            app.quit()
        QTimer.singleShot(800, capture)
    return app.exec()
