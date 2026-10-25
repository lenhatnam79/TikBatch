import hashlib
import threading

import httpx

from tikbatch.engine import Engine
from test_download import response
from test_engine import FakeSource


async def test_pipeline_with_real_mp4_validation(tmp_path, monkeypatch, video_bytes):
    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda r: response(200, video_bytes,
        {"content-length": str(len(video_bytes)), "etag": '"fixture"'}))
    monkeypatch.setattr("tikbatch.engine.httpx.AsyncClient", lambda **kw: original_client(transport=transport, **kw))
    class Source(FakeSource):
        count = 24
    result = await Engine(tmp_path / "session", lambda *_: None, threading.Event(),
                          source_factory=Source).run("@foo", tmp_path / "out")
    assert result["done"] == 24 and result["failed"] == 0
    files = list((tmp_path / "out" / "foo").glob("*.mp4"))
    assert len(files) == 24
    expected = hashlib.sha256(video_bytes).hexdigest()
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == expected for p in files)
