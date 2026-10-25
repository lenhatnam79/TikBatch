from __future__ import annotations

import asyncio
import errno
import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .model import DiskFull, ExpiredSource, Media, SourceError, Throttled


def retry_after(value: str | None) -> float:
    try:
        return max(1, float(value))
    except (ValueError, TypeError):
        try:
            return max(1, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return 30


def inspect_file(path: Path) -> dict:
    import av
    try:
        with av.open(str(path)) as container:
            if not container.streams.video or not container.streams.audio:
                raise SourceError("File thiếu hình ảnh hoặc âm thanh; không lưu thành công.")
            stream = container.streams.video[0]
            next(container.decode(stream))
            w, h = stream.codec_context.width, stream.codec_context.height
        digest = hashlib.sha256()
        with path.open("rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(block)
        return {"width": w, "height": h, "bytes": path.stat().st_size, "sha256": digest.hexdigest()}
    except SourceError:
        raise
    except Exception as e:
        raise SourceError("File tải về không đọc được như video có âm thanh.") from e


class Downloader:
    def __init__(self, client: httpx.AsyncClient, on_bytes, reserve: int = 256 * 1024 * 1024):
        self.client, self.on_bytes, self.reserve = client, on_bytes, reserve

    async def download(self, row: dict, media: Media, folder: Path, cookies=None):
        vid = row["id"]
        if not vid.isdigit():
            raise SourceError("ID video không hợp lệ.")
        date = datetime.fromtimestamp(row.get("timestamp") or 0, timezone.utc).strftime("%Y%m%d")
        target = folder / f"{date}_{vid}.mp4"
        part = target.with_suffix(".mp4.part")
        sidecar = target.with_suffix(".mp4.part.json")
        # Claim only files that this queue owns. A complete but uncommitted .part
        # remains recoverable after interruption between verification and DB commit.
        saved = {}
        try:
            saved = json.loads(sidecar.read_text())
        except (OSError, ValueError):
            pass
        offset = part.stat().st_size if part.exists() else 0
        signature = [media.width, media.height, urlsplit(media.url).netloc, urlsplit(media.url).path]
        validator = saved.get("validator") if saved.get("signature") == signature else None
        if not validator:
            offset = 0
        headers = {k: v for k, v in media.headers.items()
                   if k.lower() not in {"cookie", "host", "range", "if-range", "accept-encoding", "authorization"}}
        headers["Accept-Encoding"] = "identity"
        if offset:
            headers.update({"Range": f"bytes={offset}-", "If-Range": validator})
        if shutil.disk_usage(folder).free < self.reserve + max(0, media.size - offset):
            raise DiskFull("Không đủ dung lượng trống. Đã lưu tiến độ; chọn ổ còn đủ chỗ rồi tiếp tục.")
        try:
            async with self.client.stream("GET", media.url, headers=headers,
                                          cookies=cookies, follow_redirects=True) as response:
                if response.status_code in (429, 503):
                    raise Throttled(retry_after(response.headers.get("retry-after")))
                if response.status_code in (401, 403, 410):
                    raise ExpiredSource("Đường dẫn nguồn hết hạn hoặc bị từ chối; cần lấy nguồn mới.")
                if response.status_code == 416:
                    part.unlink(missing_ok=True)
                    sidecar.unlink(missing_ok=True)
                    raise SourceError("Phần tải dở không còn khớp; sẽ tải lại file.")
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                if "text/" in content_type or "json" in content_type:
                    raise SourceError("Nguồn trả trang lỗi thay vì video.")
                etag = response.headers.get("etag", "")
                new_validator = etag if etag and not etag.startswith("W/") else response.headers.get("last-modified")
                total = None
                if response.status_code == 206:
                    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("content-range", ""))
                    if not match or int(match[1]) != offset or int(match[2]) != int(match[3]) - 1:
                        raise SourceError("Máy chủ trả khoảng dữ liệu không đúng; giữ nguyên tiến độ.")
                    if offset and new_validator and new_validator != validator:
                        part.unlink(missing_ok=True)
                        sidecar.unlink(missing_ok=True)
                        raise SourceError("Nguồn đã đổi nội dung; sẽ tải lại file.")
                    total = int(match[3])
                elif response.status_code == 200:
                    offset = 0  # Server ignored Range or representation changed.
                    if response.headers.get("content-length"):
                        total = int(response.headers["content-length"])
                else:
                    raise SourceError("Máy chủ trả trạng thái tải không được hỗ trợ.")
                if total and shutil.disk_usage(folder).free < self.reserve + max(0, total - offset):
                    raise DiskFull("Ổ đĩa không đủ dung lượng cho video.")
                sidecar.write_text(json.dumps({"signature": signature, "validator": new_validator}), encoding="utf-8")
                since_space_check = 0
                with part.open("ab" if offset else "wb") as f:
                    async for chunk in response.aiter_raw(256 * 1024):
                        f.write(chunk)
                        self.on_bytes(len(chunk))
                        since_space_check += len(chunk)
                        if since_space_check > 8 * 1024 * 1024:
                            since_space_check = 0
                            if shutil.disk_usage(folder).free < self.reserve:
                                raise DiskFull("Ổ đĩa gần đầy; đã giữ phần tải dở.")
                    f.flush()
                    os.fsync(f.fileno())
                if total is not None and part.stat().st_size != total:
                    raise SourceError("Dung lượng tải về chưa đủ; sẽ tiếp tục tải.")
            try:
                result = await asyncio.to_thread(inspect_file, part)
            except SourceError:
                part.unlink(missing_ok=True)
                sidecar.unlink(missing_ok=True)
                raise
            # Never overwrite an unrelated user file.
            if target.exists():
                old = await asyncio.to_thread(inspect_file, target)
                if old["sha256"] != result["sha256"]:
                    raise SourceError("File đích đã tồn tại với nội dung khác; hãy đổi tên file cũ rồi chạy lại.")
                part.unlink(missing_ok=True)
            else:
                part.replace(target)
            sidecar.unlink(missing_ok=True)
            return {**result, "filename": target.name, "provenance": media.provenance}
        except OSError as e:
            if e.errno == errno.ENOSPC:
                raise DiskFull("Ổ đĩa đầy; đã giữ phần tải dở.") from e
            raise
