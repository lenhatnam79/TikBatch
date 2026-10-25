from __future__ import annotations

import asyncio
import http.cookiejar
import json
import re
import time
from contextlib import asynccontextmanager
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .model import AccessDenied, Media, NeedsCaptcha, NeedsLogin, SourceError, Video, best_media, worker_command
from .worker import options

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"


def access_denial(status=None, title="", body=""):
    """Return a safe diagnostic, without saving page contents or signed URLs."""
    text = body.lower()
    blocked = (status == 403 or
               ("access denied" in (title + " " + body).lower() and
                ("you don't have permission to access" in text or "errors.edgesuite.net" in text)))
    if not blocked:
        return None
    match = re.search(r"\bReference\s*#\s*([A-Za-z0-9._-]{1,120})", body, re.IGNORECASE)
    reference = f" Reference #{match[1]}." if match else ""
    return AccessDenied("TikTok từ chối truy cập (Access Denied)." + reference +
        " Đã tạm dừng và giữ hàng đợi. Kiểm tra cùng link bằng Chrome/Safari thông thường;"
        " chỉ tiếp tục khi trang mở lại được. Đăng nhập lại chưa chắc khắc phục lỗi này.")


def web_formats(item: dict) -> list[dict]:
    video = item.get("video") or {}
    formats = []
    def add(value, width=0, height=0, bitrate=0, codec="h264", size=0):
        if isinstance(value, str):
            urls = [value]
        elif isinstance(value, list):
            urls = [v.get("src", "") if isinstance(v, dict) else v for v in value]
        elif isinstance(value, dict):
            urls = value.get("UrlList") or value.get("urlList") or value.get("url_list") or value.get("src") or value.get("url") or []
            if isinstance(urls, str):
                urls = [urls]
            size = value.get("DataSize") or size
        else:
            urls = []
        for url in urls:
            if not isinstance(url, str):
                continue
            if url.startswith("//"):
                url = "https:" + url
            # TikTok has video-only HVC1 variants; require a muxed source.
            if urlsplit(url).path.endswith("/media-video-hvc1/"):
                continue
            formats.append({"url": url, "width": width, "height": height, "tbr": bitrate,
                            "filesize": size, "vcodec": codec, "acodec": "aac",
                            "format_id": "play", "_tikbatch_playback": True})
    w, h = int(video.get("width") or 0), int(video.get("height") or 0)
    add(video.get("playAddr"), w, h)
    add(video.get("PlayAddrStruct"), w, h, (video.get("bitrate") or 0) / 1000)
    add(video.get("play_addr"), w, h)
    add(video.get("play_addr_h264"), w, h)
    add(video.get("play_addr_bytevc1"), w, h, codec="h265")
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


def item_from_json(data: dict, vid: str) -> dict:
    scope = data.get("__DEFAULT_SCOPE__", {})
    candidates = [scope.get("webapp.video-detail", {}).get("itemInfo", {}).get("itemStruct"),
                  data.get("ItemModule", {}).get(vid), data.get("itemInfo", {}).get("itemStruct"),
                  data.get("itemStruct"), data.get("data", {}).get("itemInfo", {}).get("itemStruct")]
    return next((v for v in candidates if isinstance(v, dict) and str(v.get("id")) == vid), {})


class _PageData(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inside = False
        self.parts = []
        self.current = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("id") in {"__UNIVERSAL_DATA_FOR_REHYDRATION__", "SIGI_STATE"}:
            self.inside = True
            self.current = []

    def handle_data(self, data):
        if self.inside:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.inside:
            self.parts.append("".join(self.current))
            self.inside = False


def item_from_html(html: str, vid: str) -> dict:
    parser = _PageData()
    parser.feed(html)
    for text in parser.parts:
        try:
            if item := item_from_json(json.loads(text), vid):
                return item
        except (ValueError, AttributeError, TypeError):
            continue
    return {}


def usable_cached_media(seed: dict, now=None):
    now = time.time() if now is None else now
    media = best_media(web_formats(seed.get("item", {})), seed.get("headers") or {"User-Agent": UA, "Referer": "https://www.tiktok.com/"})
    query = parse_qs(urlsplit(media.url).query)
    expiries = []
    for name in ("x-expires", "expires", "expire"):
        try:
            value = float(query[name][0])
            if value > 1e12:
                value /= 1000
            expiries.append(value)
        except (KeyError, ValueError, TypeError):
            pass
    if expiries:
        if min(expiries) <= now + 30:
            raise SourceError("Nguồn trong bộ nhớ đã hết hạn.")
    elif now - seed.get("fetched", 0) > 1800:
        raise SourceError("Cần làm mới nguồn trong bộ nhớ.")
    return media


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
    def __init__(self, root: Path, emit, *, headless=True, max_resolvers=8, browser_workers=4):
        self.root, self.emit = root, emit
        self.cookiefile = root / "cookies.txt"
        self.headless = headless
        self.resolvers = asyncio.Semaphore(max_resolvers)
        self.process = None
        self._playwright = None
        self._browser = None
        self._browser_lock = asyncio.Lock()
        self._detail_limit = asyncio.Semaphore(browser_workers)
        self._pages = asyncio.Queue()
        self._browser_failure = None
        self._prefer_browser = False
        self._http_details_usable = None
        self._http_probe_lock = asyncio.Lock()
        self._ua = UA

    @asynccontextmanager
    async def browser_session(self):
        from playwright.async_api import async_playwright
        async with self._browser_lock:
            if self._browser_failure:
                raise self._browser_failure
            if self._browser is None:
                try:
                    self._playwright = await async_playwright().start()
                    self._browser = await self._playwright.chromium.launch_persistent_context(
                        str(self.root / "browser"), headless=self.headless, channel="chromium",
                        viewport={"width": 1440, "height": 960})
                    # Metadata is required, rendered media is not. This does not
                    # block the JS/fetch requests used to populate the channel.
                    async def filter_assets(route):
                        if route.request.resource_type in {"image", "media", "font"}:
                            await route.abort()
                        else:
                            await route.continue_()
                    await self._browser.route("**/*", filter_assets)
                    if self._browser.pages:
                        self._ua = await self._browser.pages[0].evaluate("navigator.userAgent")
                except Exception as e:
                    if self._playwright:
                        await self._playwright.stop()
                        self._playwright = None
                    self._browser_failure = NeedsLogin("Không mở được Chromium chạy ngầm. Kiểm tra cài trình duyệt và đóng phiên đăng nhập đang mở; hàng đợi được giữ lại.")
                    raise self._browser_failure from e
        yield self._browser

    @asynccontextmanager
    async def detail_page(self):
        async with self._detail_limit, self.browser_session() as context:
            try:
                page = self._pages.get_nowait()
            except asyncio.QueueEmpty:
                page = await context.new_page()
            try:
                if page.is_closed():
                    page = await context.new_page()
                yield page
            finally:
                if not page.is_closed():
                    self._pages.put_nowait(page)

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
            self._prefer_browser = True
            self.emit("log", "Quét trực tiếp chưa được. Chuyển sang trình duyệt chạy ngầm; chỉ mở cửa sổ đăng nhập khi bạn bấm nút.")
        return await self.scan_browser(user, url, on_video)

    async def scan_browser(self, user: str, url: str, on_video):
        from playwright.async_api import Error as BrowserError
        events = asyncio.Queue(maxsize=100)
        tasks = set()
        async with self.browser_session() as context:
            page = None
            try:
                page = await context.new_page()
                await self.check_auth(page, before_navigation=True)
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
                await self.navigate(page, url, timeout=45000)
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
                    await self.check_auth(page)
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
                raise SourceError("Quét bị gián đoạn; chưa xác nhận hết kênh. Có thể cần dùng nút Mở TikTok / Đăng nhập rồi tiếp tục.")
            except BrowserError as e:
                raise SourceError("Không đọc được trang TikTok trong trình duyệt; hãy mở TikTok để kiểm tra kết nối/đăng nhập.") from e
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*list(tasks), return_exceptions=True)
                if page and not page.is_closed():
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
        if not fresh:
            try:
                return usable_cached_media(seed)
            except SourceError:
                pass
        async with self.resolvers:
            if self._prefer_browser or seed.get("item"):
                return await self.resolve_browser(row["url"])
            try:
                return await asyncio.to_thread(self._resolve_sync, row["url"])
            except SourceError:
                return await self.resolve_browser(row["url"])

    async def check_auth(self, page, before_navigation=False):
        if self._browser_failure:
            raise self._browser_failure
        if before_navigation:
            return
        await self.check_access(page)
        needs_login = urlsplit(page.url).path.startswith("/login")
        if await self.has_captcha(page):
            self._browser_failure = NeedsCaptcha("TikTok yêu cầu CAPTCHA. Đã tạm dừng và giữ hàng đợi. Bấm Mở TikTok / Xác minh, xử lý thủ công rồi đóng cửa sổ và bấm Bắt đầu / Tiếp tục.")
            raise self._browser_failure
        if needs_login:
            self._browser_failure = NeedsLogin("TikTok yêu cầu đăng nhập/xác minh. Đã tạm dừng; bấm Mở TikTok / Đăng nhập rồi tiếp tục.")
            raise self._browser_failure

    async def has_captcha(self, page):
        captcha = page.locator('[id="captcha-verify-container"], iframe[src*="captcha"], [id="verify-center"], [class*="captcha-verify-container"]')
        for index in range(await captcha.count()):
            if await captcha.nth(index).is_visible():
                return True
        return False

    async def check_access(self, page, status=None):
        if self._browser_failure:
            raise self._browser_failure
        try:
            title = await page.title()
            body = ""
            if status is not None or title.strip().lower() in {"access denied", "forbidden", "request rejected"}:
                body = await page.evaluate("(document.body?.innerText || '').slice(0, 12000)")
        except Exception:
            title, body = "", ""
        if denial := access_denial(status, title, body):
            self._browser_failure = denial
            raise denial

    async def navigate(self, page, url, timeout=20000, *, manual=False):
        from playwright.async_api import Error as BrowserError
        if self._browser_failure:
            raise self._browser_failure
        try:
            response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        except BrowserError as e:
            # Chromium can throw on a 403 navigation before returning a response.
            await self.check_access(page)
            code = re.search(r"net::ERR_[A-Z_]+", str(e))
            label = code[0] if code else type(e).__name__
            raise SourceError(f"Không tải được trang TikTok ({label}); kiểm tra truy cập bằng trình duyệt thông thường.") from e
        await self.check_access(page, response.status if response else None)
        if not manual:
            await self.check_auth(page)
        return response

    async def resolve_browser(self, url):
        vid = urlsplit(url).path.rstrip("/").split("/")[-1]
        # Cheap HTML lookup shares this browser session's cookies. Probe once;
        # stop trying this route when TikTok requires page JavaScript instead.
        async with self.browser_session() as context:
            if self._http_details_usable is None:
                async with self._http_probe_lock:
                    if self._http_details_usable is None:
                        self._http_details_usable = False
                        if media := await self._resolve_http(context, url, vid):
                            self._http_details_usable = True
                            return media
            elif self._http_details_usable:
                if media := await self._resolve_http(context, url, vid):
                    return media
        async with self.detail_page() as page:
            captured = []
            tasks = set()
            async def capture(response):
                if "/api/item/detail" not in urlsplit(response.url).path:
                    return
                try:
                    item = item_from_json(await response.json(), vid)
                    if item:
                        captured.append(item)
                except Exception:
                    pass
            def callback(response):
                task = asyncio.create_task(capture(response))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
            page.on("response", callback)
            try:
                await self.navigate(page, url)
                ua = await page.evaluate("navigator.userAgent")
                for _ in range(8):
                    await self.check_auth(page)
                    scripts = await page.locator("script#__UNIVERSAL_DATA_FOR_REHYDRATION__, script#SIGI_STATE").all_text_contents()
                    items = list(captured)
                    for script in scripts:
                        try:
                            items.append(item_from_json(json.loads(script), vid))
                        except (ValueError, AttributeError, TypeError):
                            pass
                    for item in items:
                        try:
                            return best_media(web_formats(item), {"User-Agent": ua, "Referer": "https://www.tiktok.com/"})
                        except SourceError:
                            continue
                    await asyncio.sleep(.4)
                raise SourceError("Trang video chưa cung cấp nguồn phát phù hợp; có thể là video hạn chế hoặc dữ liệu nguồn đã thay đổi.")
            except SourceError:
                raise
            except Exception as e:
                raise SourceError("Không đọc được nguồn phát trong thời gian chờ; sẽ thử lại có giới hạn.") from e
            finally:
                page.remove_listener("response", callback)
                active = list(tasks)
                for task in active:
                    task.cancel()
                await asyncio.gather(*active, return_exceptions=True)

    async def _resolve_http(self, context, url, vid):
        response = None
        try:
            response = await context.request.get(url, timeout=8000)
            if response.status == 403:
                self._browser_failure = access_denial(403, body=await response.text())
                raise self._browser_failure
            if response.status != 200:
                return None
            html = await response.text()
            # The request endpoint sometimes returns an error document with 200.
            if not item_from_html(html, vid):
                # Only visible text is used; do not scan JSON/video descriptions
                # for block markers and confuse a post caption with an error.
                plain = re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.I | re.S)
                visible = re.sub(r"<[^>]+>", " ", plain)
                if denial := access_denial(200, body=visible):
                    self._browser_failure = denial
                    raise denial
            item = item_from_html(html, vid)
            return best_media(web_formats(item), {"User-Agent": self._ua, "Referer": "https://www.tiktok.com/"})
        except AccessDenied:
            raise
        except Exception:
            return None
        finally:
            if response:
                await response.dispose()

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
            headless=False, channel="chromium", viewport={"width": 1440, "height": 960})
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await source.navigate(page, url, timeout=45000, manual=True)
            emit("log", "Bạn có thể đăng nhập/xác minh trong cửa sổ TikTok. Đóng cửa sổ khi xong.")
            awaiting_captcha = False
            while context.pages and not (stop and stop.is_set()):
                try:
                    page = context.pages[0]
                    await source.check_access(page)
                    captcha = await source.has_captcha(page)
                    if captcha and not awaiting_captcha:
                        emit("log", "Đang chờ bạn xử lý CAPTCHA thủ công trong trình duyệt. Tool không tự giải hoặc tải lại trang.")
                    elif awaiting_captcha and not captcha:
                        emit("log", "Không còn thấy CAPTCHA. Nếu trang đã dùng được, đóng cửa sổ TikTok rồi bấm Bắt đầu / Tiếp tục.")
                    awaiting_captcha = captcha
                    await source.save_cookies(context)
                    await asyncio.sleep(1)
                except AccessDenied:
                    raise
                except Exception:
                    if context.pages and not (stop and stop.is_set()):
                        raise SourceError("Không đọc được cửa sổ xác minh. Đóng cửa sổ rồi mở lại; hàng đợi vẫn được giữ.")
                    break
        finally:
            await context.close()
