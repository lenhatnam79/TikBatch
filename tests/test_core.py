import json
import time

import pytest

from tikbatch.engine import Adaptive
from tikbatch.locking import FileLock
from tikbatch.model import SourceError, Video, best_media, profile_url
from tikbatch.sources import browser_video, web_formats
from tikbatch.store import Store


@pytest.mark.parametrize("url", ["https://www.tiktok.com/@hong_le_", "@hong_le_", "https://tiktok.com/@hong_le_/?lang=vi"])
def test_profile_normalization(url):
    assert profile_url(url) == ("hong_le_", "https://www.tiktok.com/@hong_le_")


@pytest.mark.parametrize("url", ["https://tiktok.com.evil.com/@foo", "http://tiktok.com/@foo", "https://www.tiktok.com/@foo/video/123", "https://user@tiktok.com/@foo", "https://tiktok.com:123/@foo", "../foo"])
def test_profile_rejects_other_targets(url):
    with pytest.raises(ValueError):
        profile_url(url)


def fmt(**kwargs):
    return {"url": "https://cdn.example/video.mp4", "format_id": "play", "width": 720,
            "height": 1280, "acodec": "aac", "vcodec": "h264", **kwargs}


def test_best_quality_rejects_watermark_and_silent_formats():
    formats = [fmt(), fmt(format_id="download", width=2160, height=3840),
               fmt(format_note="watermarked", width=2160, height=3840),
               fmt(acodec="none", width=2160, height=3840),
               fmt(width=1080, height=1920)]
    assert best_media(formats).width == 1080


@pytest.mark.parametrize("bad", [fmt(format_id="unknown"), fmt(vcodec="bytevc2"), fmt(protocol="m3u8_native"), fmt(url="http://cdn.example/a.mp4"), fmt(format_id="download_addr")])
def test_no_unproven_or_unplayable_source(bad):
    with pytest.raises(SourceError):
        best_media([bad])


def test_web_parser_excludes_download_address_and_video_only():
    item = {"video": {"width": 720, "height": 1280, "playAddr": "https://cdn.example/play.mp4",
                      "downloadAddr": "https://cdn.example/watermarked.mp4",
                      "bitrateInfo": [{"PlayAddr": {"UrlList": ["https://cdn.example/media-video-hvc1/"]}}]}}
    formats = web_formats(item)
    assert len(formats) == 1
    assert best_media(formats).url.endswith("play.mp4")


def test_wrong_author_is_not_imported():
    assert browser_video({"id": "123", "author": {"uniqueId": "other"}}, "hong_le_") is None


def test_queue_dedup_restart_and_repair(tmp_path):
    store = Store(tmp_path)
    v = Video("123", "https://www.tiktok.com/@foo/video/123", "hello")
    store.add(v)
    store.add(v)
    assert store.counts()["pending"] == 1
    assert store.claim()["id"] == "123"
    store.close()
    store = Store(tmp_path)
    assert store.counts()["pending"] == 1
    store.claim()
    store.done("123", {"filename": "a.mp4", "bytes": 5, "sha256": "x", "width": 1, "height": 1, "provenance": "playback"})
    (tmp_path / "a.mp4").write_bytes(b"12345")
    store.reconcile()
    assert store.counts()["done"] == 1
    (tmp_path / "a.mp4").write_bytes(b"bad")
    store.reconcile()
    assert store.counts()["pending"] == 1
    store.close()


def test_retry_is_bounded_and_backoff_is_persistent(tmp_path):
    store = Store(tmp_path)
    store.add(Video("123", "url"))
    store.claim()
    store.fail("123", "temporary", 60)
    assert store.claim() is None
    assert store.db.execute("SELECT ready FROM videos").fetchone()[0] > time.time()
    store.db.execute("UPDATE videos SET ready=0,attempts=3")
    store.db.commit()
    store.claim()
    store.fail("123", "permanent", 0)
    assert store.counts()["failed"] == 1
    store.close()


def test_lock_prevents_two_engines(tmp_path):
    with FileLock(tmp_path / "lock"):
        with pytest.raises(RuntimeError):
            with FileLock(tmp_path / "lock"):
                pass
    with FileLock(tmp_path / "lock"):
        pass


def test_adaptive_obeys_limit_and_reduces_after_errors():
    a = Adaptive(8)
    a.sample(100, True)
    assert a.limit == 5
    a.sample(100, True)
    assert a.limit == 4
    a.error_count = 1
    a.sample(100, True)
    assert a.limit == 2
    for i in range(30):
        a.sample(100 * (2 ** i), True)
    assert a.limit == 8
