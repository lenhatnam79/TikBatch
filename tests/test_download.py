import asyncio
import hashlib
import json

import httpx
import pytest

from tikbatch.download import Downloader, inspect_file, retry_after
from tikbatch.model import DiskFull, Media, SourceError, Throttled


class Body(httpx.AsyncByteStream):
    def __init__(self, payload):
        self.payload = payload

    async def __aiter__(self):
        for start in range(0, len(self.payload), 1024):
            yield self.payload[start:start + 1024]
            await asyncio.sleep(0)


def response(status, payload=b"", headers=None):
    return httpx.Response(status, stream=Body(payload), headers=headers or {})


async def transfer(tmp_path, handler, media=None):
    received = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await Downloader(client, received.append, reserve=0).download(
            {"id": "123", "timestamp": 0}, media or Media("https://cdn.example/video.mp4", 64, 96), tmp_path)
    return result, sum(received)


async def test_actual_video_stream_is_verified_and_committed(tmp_path, video_bytes):
    result, transferred = await transfer(tmp_path, lambda r: response(200, video_bytes, {"content-length": str(len(video_bytes)), "etag": '"abc"'}))
    assert result["width"] == 64 and result["height"] == 96
    assert result["sha256"] == hashlib.sha256(video_bytes).hexdigest()
    assert (tmp_path / result["filename"]).read_bytes() == video_bytes
    assert transferred == len(video_bytes)
    assert not list(tmp_path.glob("*.part*"))


def seed_partial(tmp_path, payload):
    (tmp_path / "19700101_123.mp4.part").write_bytes(payload)
    (tmp_path / "19700101_123.mp4.part.json").write_text(json.dumps({"signature": [64, 96, "cdn.example", "/video.mp4"], "validator": '"abc"'}))


async def test_resume_requests_validated_range(tmp_path, video_bytes):
    seed_partial(tmp_path, video_bytes[:512])
    def handler(request):
        assert request.headers["range"] == "bytes=512-"
        assert request.headers["if-range"] == '"abc"'
        return response(206, video_bytes[512:], {"etag": '"abc"', "content-range": f"bytes 512-{len(video_bytes)-1}/{len(video_bytes)}"})
    result, transferred = await transfer(tmp_path, handler)
    assert transferred == len(video_bytes) - 512
    assert result["bytes"] == len(video_bytes)


async def test_server_ignores_range_restarts_without_appending(tmp_path, video_bytes):
    seed_partial(tmp_path, b"wrong data")
    result, transferred = await transfer(tmp_path, lambda r: response(200, video_bytes, {"content-length": str(len(video_bytes))}))
    assert (tmp_path / result["filename"]).read_bytes() == video_bytes


async def test_wrong_content_range_cannot_corrupt_partial(tmp_path, video_bytes):
    seed_partial(tmp_path, b"partial")
    with pytest.raises(SourceError, match="khoảng dữ liệu"):
        await transfer(tmp_path, lambda r: response(206, video_bytes, {"content-range": "bytes 1-5/6"}))
    assert (tmp_path / "19700101_123.mp4.part").read_bytes() == b"partial"


async def test_changed_validator_discards_stale_partial(tmp_path, video_bytes):
    seed_partial(tmp_path, video_bytes[:512])
    with pytest.raises(SourceError, match="đổi nội dung"):
        await transfer(tmp_path, lambda r: response(206, video_bytes[512:], {"etag": '"new"', "content-range": f"bytes 512-{len(video_bytes)-1}/{len(video_bytes)}"}))
    assert not (tmp_path / "19700101_123.mp4.part").exists()


@pytest.mark.parametrize("code", [429, 503])
async def test_throttling_honors_retry_after(tmp_path, code):
    with pytest.raises(Throttled) as error:
        await transfer(tmp_path, lambda r: response(code, headers={"retry-after": "45"}))
    assert error.value.delay == 45


async def test_html_and_corrupt_media_are_not_saved_as_mp4(tmp_path):
    with pytest.raises(SourceError):
        await transfer(tmp_path, lambda r: response(200, b"<html>blocked</html>", {"content-type": "text/html"}))
    with pytest.raises(SourceError):
        await transfer(tmp_path, lambda r: response(200, b"invalid binary", {"content-type": "video/mp4"}))
    assert not list(tmp_path.glob("*.mp4"))


async def test_truncated_transfer_is_not_committed(tmp_path, video_bytes):
    with pytest.raises(SourceError, match="chưa đủ"):
        await transfer(tmp_path, lambda r: response(200, video_bytes, {"content-length": str(len(video_bytes) + 1)}))
    assert not list(tmp_path.glob("*.mp4"))


async def test_existing_different_file_is_not_overwritten(tmp_path, video_bytes):
    target = tmp_path / "19700101_123.mp4"
    target.write_bytes(b"personal file")
    with pytest.raises(SourceError):
        await transfer(tmp_path, lambda r: response(200, video_bytes))
    assert target.read_bytes() == b"personal file"


async def test_low_disk_stops_before_request(tmp_path, monkeypatch):
    from collections import namedtuple
    usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr("tikbatch.download.shutil.disk_usage", lambda p: usage(100, 100, 0))
    with pytest.raises(DiskFull):
        await transfer(tmp_path, lambda r: pytest.fail("must not request"), Media("https://cdn.example/a", size=100))
