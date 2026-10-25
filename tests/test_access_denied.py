import json
import threading
from types import SimpleNamespace

import pytest
from playwright.async_api import Error as BrowserError

from tikbatch.engine import Engine
from tikbatch.model import AccessDenied, NeedsLogin, Video
from tikbatch.sources import Source, access_denial
from test_engine import FakeSource


BODY = """Access Denied
You don't have permission to access "http://www.tiktok.com/@example" on this server.
Reference #18.123456.1234567890.example
https://errors.edgesuite.net/18.123456.1234567890.example
"""


@pytest.mark.parametrize("status", [200, 403])
def test_gateway_error_is_not_a_login_error(status):
    error = access_denial(status, "Access Denied", BODY)
    assert isinstance(error, AccessDenied) and not isinstance(error, NeedsLogin)
    assert "Reference #18.123456.1234567890.example" in str(error)
    assert "http://" not in str(error) and "edgesuite.net" not in str(error)


def test_bare_403_is_detected_without_body():
    assert isinstance(access_denial(403), AccessDenied)


def test_video_title_alone_does_not_mean_blocked():
    assert access_denial(200, "Access Denied", "A normal video description") is None


class Page:
    url = "https://www.tiktok.com/@example"

    def __init__(self, raises=False):
        self.raises = raises
        self.navigations = 0

    async def goto(self, url, **kwargs):
        assert url.startswith("https://")
        self.navigations += 1
        if self.raises:
            raise BrowserError("net::ERR_HTTP_RESPONSE_CODE_FAILURE at https://example.invalid/?secret=do-not-log")
        return SimpleNamespace(status=403)

    async def title(self):
        return "Access Denied"

    async def evaluate(self, script):
        return BODY


@pytest.mark.parametrize("navigation_raises", [False, True])
async def test_navigation_detects_denial_even_after_browser_exception(tmp_path, navigation_raises):
    source = Source(tmp_path, lambda *_: None)
    page = Page(navigation_raises)
    with pytest.raises(AccessDenied):
        await source.navigate(page, page.url)
    with pytest.raises(AccessDenied):
        await source.navigate(page, page.url)
    assert page.navigations == 1  # no repeated navigation after a block


async def test_http_detail_denial_is_not_swallowed_or_followed_by_browser_retry(tmp_path):
    source = Source(tmp_path, lambda *_: None)
    disposed = []
    async def text(): return BODY
    async def dispose(): disposed.append(True)
    response = SimpleNamespace(status=403, text=text, dispose=dispose)
    async def get(*args, **kwargs): return response
    context = SimpleNamespace(request=SimpleNamespace(get=get))
    with pytest.raises(AccessDenied):
        await source._resolve_http(context, Page.url, "123")
    assert disposed == [True]
    assert isinstance(source._browser_failure, AccessDenied)


async def test_scan_denial_keeps_queue_and_writes_diagnostic_code(tmp_path):
    class Blocked(FakeSource):
        async def scan(self, user, url, add):
            add(Video("123", "https://www.tiktok.com/@example/video/123"))
            add(Video("124", "https://www.tiktok.com/@example/video/124"))
            raise access_denial(403, "Access Denied", BODY)
        async def resolve(self, *args, **kwargs):
            pytest.fail("no metadata requests after access denied")
    result = await Engine(tmp_path / "session", lambda *_: None, threading.Event(),
                          source_factory=Blocked).run("@example", tmp_path / "out")
    assert result["pending"] == 2 and result["failed"] == result["active"] == 0
    assert result["scan"] == "incomplete" and result["error_code"] == "access_denied"
    saved = json.loads((tmp_path / "out" / "example" / "ket-qua.json").read_text())
    assert saved["error_code"] == "access_denied"


async def test_video_lookup_denial_does_not_exhaust_video_retries(tmp_path):
    class Blocked(FakeSource):
        count = 3
        async def resolve(self, *args, **kwargs):
            raise access_denial(403)
    result = await Engine(tmp_path / "session", lambda *_: None, threading.Event(),
                          source_factory=Blocked).run("@example", tmp_path / "out")
    assert result["pending"] == 3 and result["failed"] == 0
    assert result["error_code"] == "access_denied"
