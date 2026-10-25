import asyncio
import threading

import httpx

from tikbatch.engine import Adaptive, Engine
from tikbatch.model import ExpiredSource, Media, NeedsLogin, SourceError, Video
from tikbatch.store import Store
from test_engine import FakeSource, fake_download


def test_start_with_eight_tasks_and_respect_small_user_limit():
    assert Adaptive(32).limit == 8
    assert Adaptive(2).limit == 2


def immediate_retries(monkeypatch):
    original = Store.fail
    def fail(self, id, message, delay, **kw):
        return original(self, id, message, 0, **kw)
    monkeypatch.setattr(Store, "fail", fail)


async def test_content_errors_do_not_reduce_global_parallelism(tmp_path, monkeypatch):
    class One(FakeSource):
        count = 1
    calls = 0
    async def download(self, row, media, folder, cookies):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise SourceError("Missing metadata")
        return await fake_download(self, row, media, folder, cookies)
    monkeypatch.setattr("tikbatch.engine.Downloader.download", download)
    immediate_retries(monkeypatch)
    engine = Engine(tmp_path / "session", lambda *_: None, threading.Event(), source_factory=One)
    result = await engine.run("@foo", tmp_path / "out")
    assert result["done"] == 1
    assert engine.adaptive.error_count == 0 and engine.adaptive.limit == 8


async def test_transport_retry_reuses_source_without_browser_refresh(tmp_path, monkeypatch):
    fresh_flags = []
    class One(FakeSource):
        count = 1
        async def resolve(self, row, fresh=False):
            fresh_flags.append(fresh)
            return Media("https://cdn.example/a.mp4")
    calls = 0
    async def download(self, row, media, folder, cookies):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("network error")
        return await fake_download(self, row, media, folder, cookies)
    monkeypatch.setattr("tikbatch.engine.Downloader.download", download)
    immediate_retries(monkeypatch)
    engine = Engine(tmp_path / "session", lambda *_: None, threading.Event(), source_factory=One)
    result = await engine.run("@foo", tmp_path / "out")
    assert result["done"] == 1
    assert fresh_flags == [False, False]


async def test_expired_url_refreshes_immediately_within_same_attempt(tmp_path, monkeypatch):
    fresh_flags = []
    class One(FakeSource):
        count = 1
        async def resolve(self, row, fresh=False):
            fresh_flags.append(fresh)
            return Media("https://cdn.example/new" if fresh else "https://cdn.example/old")
    async def download(self, row, media, folder, cookies):
        if media.url.endswith("old"):
            raise ExpiredSource("Expired")
        return await fake_download(self, row, media, folder, cookies)
    monkeypatch.setattr("tikbatch.engine.Downloader.download", download)
    result = await Engine(tmp_path / "session", lambda *_: None, threading.Event(), source_factory=One).run("@foo", tmp_path / "out")
    assert result["done"] == 1 and fresh_flags == [False, True]
    store = Store(tmp_path / "out" / "foo")
    assert store.db.execute("SELECT attempts FROM videos").fetchone()[0] == 1
    store.close()


async def test_equivalent_cdn_url_is_used_before_browser_refresh(tmp_path, monkeypatch):
    fresh_flags = []
    urls = []
    class One(FakeSource):
        count = 1
        async def resolve(self, row, fresh=False):
            fresh_flags.append(fresh)
            return Media("https://cdn1.example/a", fallback_urls=["https://cdn2.example/a"])
    async def download(self, row, media, folder, cookies):
        urls.append(media.url)
        if "cdn1" in media.url:
            raise ExpiredSource("Expired")
        return await fake_download(self, row, media, folder, cookies)
    monkeypatch.setattr("tikbatch.engine.Downloader.download", download)
    result = await Engine(tmp_path / "session", lambda *_: None, threading.Event(), source_factory=One).run("@foo", tmp_path / "out")
    assert result["done"] == 1 and len(urls) == 2 and fresh_flags == [False]


async def test_login_requirement_pauses_without_failing_all_videos(tmp_path, monkeypatch):
    class Two(FakeSource):
        count = 2
        async def resolve(self, row, fresh=False):
            raise NeedsLogin("Login required")
    result = await Engine(tmp_path / "session", lambda *_: None, threading.Event(), source_factory=Two).run("@foo", tmp_path / "out")
    assert result["pending"] == 2 and result["failed"] == 0
    assert result["error"] == "Login required"
    assert (tmp_path / "out" / "foo" / "ket-qua.json").exists()


def test_sparse_listing_does_not_erase_rich_metadata(tmp_path):
    store = Store(tmp_path)
    seed = {"item": {"id": "123", "video": {"playAddr": "https://cdn.example/a"}}, "fetched": 123}
    store.add(Video("123", "url", "title", 100, seed))
    store.add(Video("123", "url"))
    row = store.claim()
    assert row["title"] == "title" and row["timestamp"] == 100
    assert "playAddr" in row["seed"]
    store.close()
