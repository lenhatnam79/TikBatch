import asyncio
import json
import time
from types import SimpleNamespace

import pytest

from tikbatch.model import NeedsLogin, SourceError
from tikbatch.sources import Source, item_from_html, usable_cached_media, web_formats


class Page:
    def __init__(self):
        self.closed = False

    def is_closed(self):
        return self.closed

    async def evaluate(self, expression):
        return "TestBrowser/1.0"


class Context:
    def __init__(self):
        self.pages = [Page()]
        self.created = 0

    async def route(self, *args):
        pass

    async def new_page(self):
        self.created += 1
        page = Page()
        self.pages.append(page)
        return page

    async def close(self):
        for page in self.pages:
            page.closed = True


@pytest.fixture
def browser(monkeypatch):
    context = Context()
    calls = []
    fail = []
    async def launch(*args, **kwargs):
        calls.append(kwargs)
        if fail:
            raise RuntimeError("browser could not start")
        return context
    async def start():
        return SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=launch), stop=stop)
    async def stop():
        pass
    monkeypatch.setattr("playwright.async_api.async_playwright", lambda: SimpleNamespace(start=start))
    return context, calls, fail


async def test_default_is_new_headless_and_context_is_reused(tmp_path, browser, monkeypatch):
    monkeypatch.setenv("TIKBATCH_HEADLESS", "0")
    source = Source(tmp_path, lambda *_: None)
    for _ in range(3):
        async with source.browser_session():
            pass
    assert len(browser[1]) == 1
    assert browser[1][0]["headless"] is True
    assert browser[1][0]["channel"] == "chromium"
    await source.close()


async def test_detail_page_pool_reuses_four_pages_without_opening_per_video(tmp_path, browser):
    source = Source(tmp_path, lambda *_: None, browser_workers=4)
    active = peak = 0
    async def lookup():
        nonlocal active, peak
        async with source.detail_page():
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(.01)
            active -= 1
    await asyncio.gather(*(lookup() for _ in range(40)))
    assert peak == 4 and browser[0].created == 4
    assert len(browser[1]) == 1
    await source.close()


async def test_failed_browser_does_not_keep_relaunching_or_switch_to_headed(tmp_path, browser):
    browser[2].append(True)
    source = Source(tmp_path, lambda *_: None)
    async def lookup():
        with pytest.raises(NeedsLogin):
            async with source.browser_session():
                pass
    await asyncio.gather(*(lookup() for _ in range(8)))
    assert len(browser[1]) == 1
    assert browser[1][0]["headless"] is True


def test_parser_supports_sigi_and_rejects_wrong_video():
    item = {"id": "123", "video": {"playAddr": "https://cdn.example/a.mp4"}}
    html = '<script id="SIGI_STATE">' + json.dumps({"ItemModule": {"123": item}}) + '</script>'
    assert item_from_html(html, "123") == item
    assert item_from_html(html, "999") == {}


def test_parser_supports_universal_data():
    item = {"id": "123", "video": {}}
    data = {"__DEFAULT_SCOPE__": {"webapp.video-detail": {"itemInfo": {"itemStruct": item}}}}
    html = '<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">' + json.dumps(data) + '</script>'
    assert item_from_html(html, "123") == item


def test_play_address_struct_and_src_objects_are_supported():
    item = {"video": {"width": 720, "height": 1280, "playAddr": {"src": "//cdn.example/a.mp4"},
                      "PlayAddrStruct": {"UrlList": ["https://cdn2.example/a.mp4"]}}}
    assert {f["url"] for f in web_formats(item)} == {"https://cdn.example/a.mp4", "https://cdn2.example/a.mp4"}


def test_signed_url_lifetime_prevents_unnecessary_browser_refresh():
    seed = {"fetched": 0, "item": {"video": {"playAddr": "https://cdn.example/a.mp4?x-expires=9999999999"}}}
    assert usable_cached_media(seed, now=2000000000).url.startswith("https://cdn.example/")
    with pytest.raises(SourceError):
        usable_cached_media(seed, now=10000000000)


def test_unknown_url_expiry_uses_bounded_cache_age():
    seed = {"fetched": 1000, "item": {"video": {"playAddr": "https://cdn.example/a.mp4"}}}
    assert usable_cached_media(seed, now=2000)
    with pytest.raises(SourceError):
        usable_cached_media(seed, now=3000)
