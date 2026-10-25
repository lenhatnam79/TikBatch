from __future__ import annotations

import asyncio
import http.cookiejar
import json
import random
import threading
import time
from pathlib import Path
from dataclasses import replace

import httpx

from .download import Downloader
from .model import DiskFull, ExpiredSource, NeedsLogin, SourceError, Throttled, Video, profile_url
from .sources import Source
from .store import Store
from .locking import FileLock


class Adaptive:
    """Conservative additive exploration; multiplicative reduction on errors."""
    def __init__(self, maximum=16, initial=8):
        self.maximum = maximum
        self.limit = min(initial, maximum)
        self.previous_speed = None
        self.last_direction = 0
        self.error_count = 0
        self.hold = 0

    def sample(self, speed: float, backlog: bool):
        if self.error_count:
            self.limit = max(1, self.limit // 2)
            self.last_direction = -1
            self.hold = 2
        elif backlog and speed > 0:
            if self.hold:
                self.hold -= 1
            elif self.previous_speed is not None and self.last_direction == 1 and speed < self.previous_speed * 1.03:
                self.limit = max(1, self.limit - 1)
                self.last_direction = 0
                self.hold = 6
            else:
                self.limit = min(self.maximum, self.limit + 1)
                self.last_direction = 1
        self.previous_speed = speed
        self.error_count = 0


class Engine:
    def __init__(self, root: Path, emit, stop: threading.Event, maximum=16, source_factory=Source, *, headless=True):
        self.root, self.emit, self.stop = root, emit, stop
        self.adaptive = Adaptive(maximum)
        self.source_factory = source_factory
        self.bytes = 0
        self.cooldown = 0
        self.headless = headless

    async def run(self, url: str, output: Path):
        user, _ = profile_url(url)
        with FileLock(self.root / ".session.lock"), FileLock(output / user / ".tikbatch.lock"):
            return await self._run(url, output)

    async def _run(self, url: str, output: Path):
        user, url = profile_url(url)
        folder = output / user
        store = Store(folder)
        source = (Source(self.root, self.emit, headless=self.headless,
                         max_resolvers=min(8, self.adaptive.maximum),
                         browser_workers=min(4, self.adaptive.maximum))
                  if self.source_factory is Source else self.source_factory(self.root, self.emit))
        store.set("profile", url)
        store.reconcile()
        store.set("scan", "scanning")
        scan_error = ""
        fatal = ""
        scan_done = False
        def add(v: Video):
            store.add(v)
            if v.seed.get("photo"):
                store.unsupported(v.id)
        async def scan():
            nonlocal scan_done, scan_error, fatal
            try:
                status = await source.scan(user, url, add)
                store.set("scan", status)
            except asyncio.CancelledError:
                store.set("scan", "interrupted")
                raise
            except Exception as e:
                scan_error = str(e) if isinstance(e, SourceError) else "Quét kênh gặp lỗi; chưa xác nhận hết danh sách."
                store.set("scan", "incomplete")
                self.emit("log", scan_error)
                if isinstance(e, NeedsLogin):
                    fatal = scan_error
            finally:
                scan_done = True
        def on_bytes(n):
            self.bytes += n
        tasks = set()
        scan_task = asyncio.create_task(scan())
        started = last_report = last_tune = time.monotonic()
        last_bytes = tune_bytes = 0
        initial_done = store.counts()["done"]
        limits = httpx.Limits(max_connections=self.adaptive.maximum + 8,
                             max_keepalive_connections=self.adaptive.maximum)
        try:
            async with httpx.AsyncClient(limits=limits, timeout=httpx.Timeout(30, connect=15)) as client:
                downloader = Downloader(client, on_bytes)
                async def download(row):
                    nonlocal fatal
                    try:
                        media = await source.resolve(row, fresh=row.get("error_code") == "expired")
                        cookies = None
                        if source.cookiefile.exists():
                            cookies = http.cookiejar.MozillaCookieJar(str(source.cookiefile))
                            cookies.load(ignore_discard=True, ignore_expires=True)
                        async def transfer(selected):
                            urls = list(dict.fromkeys([selected.url, *selected.fallback_urls]))[:3]
                            for i, url in enumerate(urls):
                                try:
                                    return await downloader.download(row, replace(selected, url=url), folder, cookies)
                                except ExpiredSource:
                                    if i == len(urls) - 1:
                                        raise
                        try:
                            result = await transfer(media)
                        except ExpiredSource:
                            self.emit("log", f"Video {row['id']}: đang làm mới nguồn hết hạn…")
                            media = await source.resolve(row, fresh=True)
                            result = await transfer(media)
                        store.done(row["id"], result)
                        self.emit("log", f"Đã lưu video {row['id']}")
                    except asyncio.CancelledError:
                        store.reset(row["id"])
                        raise
                    except DiskFull as e:
                        store.reset(row["id"])
                        fatal = str(e)
                    except NeedsLogin as e:
                        store.reset(row["id"])
                        fatal = str(e)
                    except Exception as e:
                        code = "source"
                        if isinstance(e, Throttled):
                            code = "throttled"
                            self.adaptive.error_count += 1
                            self.cooldown = max(self.cooldown, time.monotonic() + e.delay)
                            delay = e.delay
                        else:
                            delay = min(60, 2 ** (row["attempts"] + 1)) + random.random()
                        if isinstance(e, ExpiredSource):
                            code = "expired"
                        elif isinstance(e, httpx.TransportError):
                            code = "network"
                            self.adaptive.error_count += 1
                        elif isinstance(e, httpx.HTTPStatusError):
                            code = f"http_{e.response.status_code}"
                            if e.response.status_code >= 500:
                                self.adaptive.error_count += 1
                        message = (str(e) if isinstance(e, SourceError)
                                   else f"Lỗi {code}; sẽ thử lại có giới hạn.")
                        store.fail(row["id"], message, delay, code=code)
                        self.emit("log", f"Video {row['id']}: {message}")
                while not self.stop.is_set() and not fatal:
                    counts = store.counts()
                    if scan_done and not tasks and not counts["pending"]:
                        break
                    if time.monotonic() >= self.cooldown:
                        while len(tasks) < self.adaptive.limit:
                            row = store.claim()
                            if not row:
                                break
                            task = asyncio.create_task(download(row))
                            tasks.add(task)
                            task.add_done_callback(tasks.discard)
                    now = time.monotonic()
                    if now - last_report >= .5:
                        speed = (self.bytes - last_bytes) / (now - last_report)
                        self.emit("stats", {**store.counts(), "bytes": self.bytes, "speed": speed,
                            "limit": self.adaptive.limit, "scan": store.get("scan"),
                            "elapsed": now - started, "new_done": store.counts()["done"] - initial_done,
                            "cooldown": max(0, self.cooldown - now), "folder": str(folder)})
                        last_bytes, last_report = self.bytes, now
                    if now - last_tune >= 10:
                        self.adaptive.sample((self.bytes - tune_bytes) / (now - last_tune), counts["pending"] > 0)
                        last_tune, tune_bytes = now, self.bytes
                    if tasks:
                        await asyncio.wait(list(tasks), timeout=.15, return_when=asyncio.FIRST_COMPLETED)
                    else:
                        await asyncio.sleep(.15)
        finally:
            # Must settle all task mutations before closing the SQLite connection.
            scan_task.cancel()
            active = list(tasks)
            for task in active:
                task.cancel()
            await asyncio.gather(scan_task, *active, return_exceptions=True)
            try:
                await source.close()
            except Exception:
                self.emit("log", "Cửa sổ trình duyệt đã đóng.")
            result = {**store.counts(), "scan": store.get("scan"), "folder": str(folder),
                      "seconds": time.monotonic() - started, "bytes": self.bytes,
                      "stopped": self.stop.is_set(), "error": fatal or scan_error}
            store.export()
            (folder / "ket-qua.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            store.close()
        self.emit("finished", result)
        return result
