from __future__ import annotations

import asyncio
import http.cookiejar
import json
import os
import re
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .model import Media, SourceError, Video, best_media, worker_command
from .worker import options

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"


def web_formats(item: dict) -> list[dict]:
    video = item.get("video") or {}
    formats = []
    def add(value, width=0, height=0, bitrate=0, codec="h264", size=0):
        if isinstance(value, str):
            urls = [value]
        elif isinstance(value, list):
            urls = [v.get("src", "") if isinstance(v, dict) else v for v in value]
        elif isinstance(value, dict):
            urls = value.get("UrlList") or value.get("urlList") or value.get("url_list") or []
            if isinstance(urls, str):
                urls = [urls]
            size = value.get("DataSize") or size
        else:
            urls = []
        for url in urls:
            if not isinstance(url, str):
                continue
            # TikTok has video-only HVC1 variants; require a muxed source.
            if urlsplit(url).path.endswith("/media-video-hvc1/"):
                continue
            formats.append({"url": url, "width": width, "height": height, "tbr": bitrate,
                            "filesize": size, "vcodec": codec, "acodec": "aac",
                            "format_id": "play", "_tikbatch_playback": True})
    w, h = int(video.get("width") or 0), int(video.get("height") or 0)
    add(video.get("playAddr"), w, h)
    for item in video.get("bitrateInfo") or []:
        addr = item.get("PlayAddr") or {}
        key = addr.get("UrlKey", "")
        res = re.search(r"_(\d+)p_", key)
        width, height = w, h
        if res and w and h:
            side = int(res[1])
            side = 576 if side == 540 else side
            width, height = (side, round(side * h / w)) if w < h else (round(side * w / h), side)
        codec = "bytevc2" if "bytevc2" in key else "h265" if "bytevc1" in key else "h264"
        add(addr, width, height, (item.get("Bitrate") or 0) / 1000, codec)
    # downloadAddr is deliberately excluded: it is commonly watermarked.
    return formats


def browser_video(item: dict, user: str) -> Video | None:
    author = item.get("author") or {}
    if isinstance(author, dict):
        author = author.get("uniqueId") or author.get("unique_id") or ""
    if author and str(author).lower() != user.lower():
        return None
    vid = str(item.get("id") or "")
    if not vid.isdigit():
        return None
    return Video(vid, f"https://www.tiktok.com/@{user}/video/{vid}", item.get("desc") or "",
                 int(item.get("createTime") or 0),
                 {"item": item, "fetched": time.time(), "photo": bool(item.get("imagePost"))})


class Source:
    def __init__(self, root: Path, emit):
        self.root, self.emit = root, emit
        self.cookiefile = root / "cookies.txt"
        self._local = threading.local()
        self.resolvers = asyncio.Semaphore(2)
        self.process = None
        self._playwright = None
        self._browser = None
        self._browser_lock = asyncio.Lock()
        self._detail_limit = asyncio.Semaphore(1)

    @asynccontextmanager
    async def browser_session(self):
        from playwright.async_api import async_playwright
        async with self._browser_lock:
            if self._browser is None:
                try:
                    self._playwright = await async_playwright().start()
                    self._browser = await self._playwright.chromium.launch_persistent_context(
                        str(self.root / "browser"), headless=os.environ.get("TIKBATCH_HEADLESS") == "1",
                        viewport={"width": 1440, "height": 960})
                except Exception as e:
                    if self._playwright:
                        await self._playwright.stop()
                        self._playwright = None
                    raise SourceError("Không mở được Chromium. Bấm ‘Cài trình duyệt’, hoặc đóng cửa sổ đăng nhập đang mở.") from e
        yield self._browser

    async def close(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def scan_direct(self, url: str, on_video):
        args = ["scan", url]
        if self.cookiefile.exists():
            args.append(str(self.cookiefile))
        proc = await asyncio.create_subprocess_exec(*worker_command(*args),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            limit=4 * 1024 * 1024)
        self.process = proc
        ended = False
        try:
            while line := await asyncio.wait_for(proc.stdout.readline(), timeout=60):
                event = json.loads(line)
                if event["type"] == "video":
                    on_video(Video(event["id"], event["url"], event["title"], event["timestamp"]))
                elif event["type"] == "end":
                    ended = True
                elif event["type"] == "error":
                    raise SourceError(event["message"])
            code = await proc.wait()
            if code or not ended:
                raise SourceError("Quét trực tiếp chưa hoàn tất.")
        finally:
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), 3)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
            self.process = None

    async def scan(self, user: str, url: str, on_video):
        try:
            self.emit("log", "Đang thử quét trực tiếp, không đăng nhập…")
            await self.scan_direct(url, on_video)
            return "source_end:yt-dlp"
        except (SourceError, asyncio.TimeoutError, ValueError):
            self.emit("log", "Quét trực tiếp chưa được. Đang mở cửa sổ TikTok; bạn có thể hoàn tất xác minh/đăng nhập nếu được yêu cầu…")
        return await self.scan_browser(user, url, on_video)

    async def scan_browser(self, user: str, url: str, on_video):
        from playwright.async_api import Error as BrowserError
        events = asyncio.Queue(maxsize=100)
        tasks = set()
        async with self.browser_session() as context:
            try:
                page = await context.new_page()
                async def capture(response):
                    path = urlsplit(response.url).path
                    if path not in ("/api/post/item_list/", "/api/creator/item_list/"):
                        return
                    try:
                        if response.status == 200:
                            data = await response.json()
                            await events.put((response.url, data))
                    except Exception:
                        pass
                def callback(response):
                    task = asyncio.create_task(capture(response))
                    tasks.add(task)
                    task.add_done_callback(tasks.discard)
                page.on("response", callback)
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                browser_ua = await page.evaluate("navigator.userAgent")
                def deliver(v):
                    v.seed["headers"] = {"User-Agent": browser_ua, "Referer": "https://www.tiktok.com/"}
                    on_video(v)
                last_new = time.monotonic()
                seen, cursors = set(), set()
                sec_uid = ""
                terminal = False
                while time.monotonic() - last_new < 50:
                    # Extract only page data, never credentials or form contents.
                    try:
                        data = await page.locator("script#__UNIVERSAL_DATA_FOR_REHYDRATION__").text_content(timeout=1500)
                        scope = json.loads(data or "{}").get("__DEFAULT_SCOPE__", {})
                        profile = scope.get("webapp.user-detail", {})
                        if profile.get("statusCode") in (10222, 10204):
                            raise SourceError("TikTok từ chối truy cập kênh; kiểm tra quyền truy cập và đăng nhập.")
                        detail = profile.get("userInfo", {})
                        sec_uid = detail.get("user", {}).get("secUid") or sec_uid
                        for item in detail.get("itemList") or []:
                            v = browser_video(item, user)
                            if v and v.id not in seen:
                                seen.add(v.id)
                                deliver(v)
                                last_new = time.monotonic()
                    except SourceError:
                        raise
                    except Exception:
                        pass
                    while not events.empty():
                        api_url, data = events.get_nowait()
                        query = parse_qs(urlsplit(api_url).query)
                        request_uid = (query.get("secUid") or [""])[0]
                        # Do not mistake another account's feed for this channel.
                        if not sec_uid or request_uid != sec_uid or data.get("statusCode", 0) != 0:
                            continue
                        items = data.get("itemList")
                        if not isinstance(items, list):
                            continue
                        for item in items:
                            v = browser_video(item, user)
                            if v and v.id not in seen:
                                seen.add(v.id)
                                deliver(v)
                                last_new = time.monotonic()
                        more = data.get("hasMore", data.get("hasMorePrevious"))
                        if more is False or more == 0:
                            terminal = True
                        cursor = data.get("cursor")
                        if cursor is not None:
                            cursors.add(str(cursor))
                    await self.save_cookies(context)
                    if terminal:
                        return "source_end:browser"
                    # DOM links provide IDs even when the API schema has changed;
                    # they do not establish that scanning reached the end.
                    links = await page.locator('a[href*="/video/"]').evaluate_all("els => els.map(e => e.href)")
                    for link in links:
                        match = re.search(r"/@([^/]+)/video/(\d+)", link)
                        if match and match[1].lower() == user.lower() and match[2] not in seen:
                            seen.add(match[2])
                            on_video(Video(match[2], f"https://www.tiktok.com/@{user}/video/{match[2]}"))
                            last_new = time.monotonic()
                    await page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
                    await asyncio.sleep(1.2)
                raise SourceError("Quét bị gián đoạn hoặc TikTok yêu cầu xác minh. Hãy mở TikTok/đăng nhập rồi thử lại; chưa xác nhận đã hết kênh.")
            except BrowserError as e:
                raise SourceError("Không đọc được trang TikTok trong trình duyệt; hãy mở TikTok để kiểm tra kết nối/đăng nhập.") from e
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*list(tasks), return_exceptions=True)
                await page.close()

    async def save_cookies(self, context):
        cookies = await context.cookies()
        jar = http.cookiejar.MozillaCookieJar(str(self.cookiefile))
        for c in cookies:
            if not (c["domain"].lstrip(".") == "tiktok.com" or c["domain"].endswith(".tiktok.com")):
                continue
            jar.set_cookie(http.cookiejar.Cookie(0, c["name"], c["value"], None, False,
                c["domain"], True, c["domain"].startswith("."), c["path"], True,
                c["secure"], int(c["expires"]) if c["expires"] > 0 else None,
                c["expires"] <= 0, None, None, {}, False))
        temp = self.cookiefile.with_suffix(".tmp")
        jar.save(str(temp), ignore_discard=True, ignore_expires=True)
        temp.chmod(0o600)
        temp.replace(self.cookiefile)

    async def resolve(self, row: dict, fresh: bool = False) -> Media:
        seed = json.loads(row.get("seed") or "{}")
        if not fresh and time.time() - seed.get("fetched", 0) < 600:
            try:
                return best_media(web_formats(seed.get("item", {})), seed.get("headers") or {"User-Agent": UA, "Referer": "https://www.tiktok.com/"})
            except SourceError:
                pass
        async with self.resolvers:
            try:
                return await asyncio.to_thread(self._resolve_sync, row["url"])
            except SourceError:
                return await self.resolve_browser(row["url"])

    async def resolve_browser(self, url):
        async with self._detail_limit, self.browser_session() as context:
            page = await context.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                data = await page.locator("script#__UNIVERSAL_DATA_FOR_REHYDRATION__").text_content(timeout=10000)
                scope = json.loads(data or "{}").get("__DEFAULT_SCOPE__", {})
                item = scope.get("webapp.video-detail", {}).get("itemInfo", {}).get("itemStruct", {})
                ua = await page.evaluate("navigator.userAgent")
                return best_media(web_formats(item), {"User-Agent": ua, "Referer": "https://www.tiktok.com/"})
            except SourceError:
                raise
            except Exception as e:
                raise SourceError("Không lấy được nguồn phát qua trình duyệt; hãy kiểm tra đăng nhập hoặc trạng thái video.") from e
            finally:
                await page.close()

    def _resolve_sync(self, url):
        import yt_dlp
        # Each resolution gets its own jar; yt-dlp must never write the shared session.
        opts = options()
        with yt_dlp.YoutubeDL(opts) as ydl:
            if self.cookiefile.exists():
                jar = http.cookiejar.MozillaCookieJar(str(self.cookiefile))
                jar.load(ignore_discard=True, ignore_expires=True)
                for cookie in jar:
                    ydl.cookiejar.set_cookie(cookie)
            try:
                info = ydl.extract_info(url, download=False)
                return best_media(info.get("formats") or [], info.get("http_headers"))
            except SourceError:
                raise
            except Exception as e:
                raise SourceError("Không lấy được nguồn video; nguồn có thể cần đăng nhập hoặc đã thay đổi.") from e


async def browser_login(root: Path, url: str, emit, stop=None):
    from playwright.async_api import async_playwright
    source = Source(root, emit)
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(str(root / "browser"),
            headless=False, viewport={"width": 1280, "height": 900})
        try:
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            emit("log", "Bạn có thể đăng nhập/xác minh trong cửa sổ TikTok. Đóng cửa sổ khi xong.")
            while context.pages and not (stop and stop.is_set()):
                try:
                    await source.save_cookies(context)
                    await asyncio.sleep(1)
                except Exception:
                    break
        finally:
            await context.close()
