import asyncio
import threading
from pathlib import Path

import pytest

from tikbatch.engine import Engine
from tikbatch.model import Media, SourceError, Video
from tikbatch.store import Store


class FakeSource:
    count = 1000
    broken_scan = False
    resolved = 0

    def __init__(self, root, emit):
        self.cookiefile = root / "absent.txt"

    async def scan(self, user, url, add):
        for i in range(self.count):
            add(Video(str(100000 + i), f"https://www.tiktok.com/@foo/video/{100000+i}"))
            if i % 20 == 0:
                await asyncio.sleep(0)
        if self.broken_scan:
            raise SourceError("Quét chưa hết.")
        return "source_end:test"

    async def resolve(self, row, fresh=False):
        type(self).resolved += 1
        return Media("https://cdn.example/video")

    async def close(self):
        pass


async def fake_download(self, row, media, folder, cookies):
    path = folder / (row["id"] + ".mp4")
    path.write_bytes(b"test")
    await asyncio.sleep(0)
    return {"filename": path.name, "bytes": 4, "sha256": "fixture", "width": 64, "height": 96, "provenance": "test"}


async def test_thousand_item_queue_resume_and_dedup(tmp_path, monkeypatch):
    monkeypatch.setattr("tikbatch.engine.Downloader.download", fake_download)
    FakeSource.resolved = 0
    events = []
    engine = Engine(tmp_path / "session", lambda k, d: events.append((k, d)), threading.Event(), source_factory=FakeSource)
    result = await engine.run("https://www.tiktok.com/@foo", tmp_path / "out")
    assert result["done"] == 1000 and result["failed"] == 0
    assert FakeSource.resolved == 1000
    result2 = await Engine(tmp_path / "session", lambda *_: None, threading.Event(), source_factory=FakeSource).run("@foo", tmp_path / "out")
    assert result2["done"] == 1000
    assert FakeSource.resolved == 1000  # no second download
    assert Path(result2["folder"], "ket-qua.csv").exists()


async def test_incomplete_scan_never_claims_completion(tmp_path, monkeypatch):
    class Partial(FakeSource):
        count = 2
        broken_scan = True
    monkeypatch.setattr("tikbatch.engine.Downloader.download", fake_download)
    result = await Engine(tmp_path / "session", lambda *_: None, threading.Event(), source_factory=Partial).run("@foo", tmp_path)
    assert result["done"] == 2
    assert result["scan"] == "incomplete" and result["error"]


async def test_stop_preserves_pending_jobs(tmp_path, monkeypatch):
    stop = threading.Event()
    class Many(FakeSource):
        count = 10
    async def slow(self, row, media, folder, cookies):
        stop.set()
        await asyncio.sleep(100)
    monkeypatch.setattr("tikbatch.engine.Downloader.download", slow)
    result = await Engine(tmp_path / "session", lambda *_: None, stop, source_factory=Many).run("@foo", tmp_path)
    assert result["stopped"] and result["active"] == 0
    assert result["pending"] == 10
