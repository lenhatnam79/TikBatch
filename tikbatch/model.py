from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


class SourceError(Exception):
    pass


class ExpiredSource(SourceError):
    """Refresh the signed media URL, rather than repeating a failed URL."""


class NeedsLogin(SourceError):
    """Pause the run; never automatically open a visible browser."""


class Throttled(SourceError):
    def __init__(self, delay: float = 30):
        self.delay = min(max(delay, 1), 3600)
        super().__init__(f"Nguồn giới hạn truy cập; chờ {self.delay:.0f} giây.")


class DiskFull(SourceError):
    pass


def profile_url(value: str) -> tuple[str, str]:
    value = value.strip()
    if value.startswith("@"):
        value = "https://www.tiktok.com/" + value
    parsed = urlsplit(value)
    match = re.fullmatch(r"/@([A-Za-z0-9_.]{1,24})/?", parsed.path)
    if (parsed.scheme != "https" or parsed.hostname not in {"tiktok.com", "www.tiktok.com"}
            or parsed.username or parsed.password or parsed.port not in (None, 443) or not match):
        raise ValueError("Nhập link kênh dạng https://www.tiktok.com/@tenkenh")
    user = match[1]
    return user, f"https://www.tiktok.com/@{user}"


def data_dir() -> Path:
    if os.environ.get("TIKBATCH_DATA_DIR"):
        root = Path(os.environ["TIKBATCH_DATA_DIR"])
    elif sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "TikBatch"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / "TikBatch"
    else:
        root = Path.home() / ".local" / "share" / "TikBatch"
    root.mkdir(parents=True, exist_ok=True)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root


def worker_command(*args: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--worker", *args]
    return [sys.executable, "-m", "tikbatch.worker", *args]


@dataclass
class Video:
    id: str
    url: str
    title: str = ""
    timestamp: int = 0
    seed: dict = field(default_factory=dict)


@dataclass
class Media:
    url: str
    width: int = 0
    height: int = 0
    bitrate: float = 0
    size: int = 0
    headers: dict = field(default_factory=dict)
    # Source field, not a claim that pixels were automatically checked.
    provenance: str = "playback"
    fallback_urls: list[str] = field(default_factory=list)


def best_media(formats: list[dict], headers: dict | None = None) -> Media:
    safe = []
    for f in formats:
        note = str(f.get("format_note") or "").lower()
        fid = str(f.get("format_id") or "").lower()
        url = f.get("url", "")
        if ("watermark" in note or "unplayable" in note or "download" in fid
                or "bytevc2" in str(f.get("vcodec", ""))
                or f.get("vcodec") == "none" or f.get("acodec") == "none"
                or urlsplit(url).scheme != "https"
                or f.get("protocol", "https") not in ("http", "https")
                or f.get("ext", "mp4") != "mp4"):
            continue
        # Unknown origins are not accepted as evidence of an unwatermarked source.
        if not (fid.startswith("play") or note.startswith(("direct video", "playback video"))
                or f.get("_tikbatch_playback")):
            continue
        safe.append(f)
    if not safe:
        raise SourceError("Không tìm thấy nguồn phát MP4 có âm thanh và không bị đánh dấu logo.")
    def rank(f):
        w, h = f.get("width") or 0, f.get("height") or 0
        return (min(w, h), w * h, f.get("tbr") or 0, f.get("filesize") or 0)
    f = max(safe, key=rank)
    identity = lambda x: (x.get("width"), x.get("height"), x.get("tbr"), x.get("vcodec"))
    alternatives = list(dict.fromkeys(x["url"] for x in safe if identity(x) == identity(f) and x["url"] != f["url"]))
    return Media(f["url"], f.get("width") or 0, f.get("height") or 0,
                 f.get("tbr") or 0, f.get("filesize") or 0,
                 {**(headers or {}), **(f.get("http_headers") or {})},
                 "TikTok playback; chưa kiểm tra logo trong hình ảnh", alternatives)
