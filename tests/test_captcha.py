import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from tikbatch.model import NeedsCaptcha, Video
from tikbatch.sources import Source, browser_login
from tikbatch.engine import Engine
from test_engine import FakeSource


async def test_manual_navigation_allows_captcha_but_automatic_pauses(tmp_path):
    source = Source(tmp_path, lambda *_: None)
    source.check_access = AsyncMock()
    source.has_captcha = AsyncMock(return_value=True)
    page = SimpleNamespace(url='https://www.tiktok.com/@example',
                           goto=AsyncMock(return_value=SimpleNamespace(status=200)))
    await source.navigate(page, page.url, manual=True)
    assert source._browser_failure is None
    with pytest.raises(NeedsCaptcha):
        await source.navigate(page, page.url)


@pytest.mark.parametrize('during_scan', [True, False])
async def test_captcha_preserves_queue(tmp_path, during_scan):
    class CaptchaSource(FakeSource):
        async def scan(self, user, url, add):
            add(Video('123', 'https://www.tiktok.com/@example/video/123'))
            if during_scan:
                raise NeedsCaptcha('CAPTCHA')
            return 'source_end'
        async def resolve(self, *args, **kwargs):
            raise NeedsCaptcha('CAPTCHA')
    result = await Engine(tmp_path/'session', lambda *_:None, threading.Event(),
                          source_factory=CaptchaSource).run('@example', tmp_path/'out')
    assert result['pending'] == 1
    assert result['failed'] == result['active'] == 0
    assert result['error_code'] == 'needs_captcha'


async def test_manual_window_stays_open_and_saves_session(monkeypatch, tmp_path):
    import playwright.async_api
    import tikbatch.sources as module
    stop = threading.Event()
    page = SimpleNamespace()
    context = SimpleNamespace(pages=[page], close=AsyncMock())
    launch = AsyncMock(return_value=context)
    class Playwright:
        async def __aenter__(self):
            return SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=launch))
        async def __aexit__(self, *args): pass
    monkeypatch.setattr(playwright.async_api, 'async_playwright', Playwright)
    navigate, save = AsyncMock(), AsyncMock()
    monkeypatch.setattr(Source, 'navigate', navigate)
    monkeypatch.setattr(Source, 'check_access', AsyncMock())
    monkeypatch.setattr(Source, 'has_captcha', AsyncMock(side_effect=[True, False]))
    monkeypatch.setattr(Source, 'save_cookies', save)
    async def tick(_):
        assert not context.close.called
        if save.await_count == 2:
            stop.set()
    monkeypatch.setattr(module.asyncio, 'sleep', tick)
    events=[]
    await browser_login(tmp_path, 'https://www.tiktok.com/@example', lambda *x: events.append(x), stop)
    assert navigate.call_args.kwargs['manual'] is True
    assert save.await_count == 2
    context.close.assert_awaited_once()
    assert any('Đang chờ' in data for _,data in events)
    assert any('Không còn thấy CAPTCHA' in data for _,data in events)
    assert launch.call_args.kwargs['channel'] == 'chromium'
