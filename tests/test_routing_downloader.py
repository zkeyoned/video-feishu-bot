from __future__ import annotations

from pathlib import Path

from video_feishu_bot.models import DownloadedVideo
from video_feishu_bot.routing_downloader import DOUYIN_DOMAINS, RoutingDownloader


class FakeDownloader:
    def __init__(self, name: str):
        self.name = name
        self.calls: list[str] = []

    def download(self, source_url: str) -> DownloadedVideo:
        self.calls.append(source_url)
        return DownloadedVideo(
            content_id=self.name,
            source_url=source_url,
            title=self.name,
            author="",
            description="",
            duration=0,
            source_created_at=0,
            video_path=Path("/tmp/x.mp4"),
        )


def _router():
    shiliu, ytdlp = FakeDownloader("shiliu"), FakeDownloader("ytdlp")
    return RoutingDownloader([(DOUYIN_DOMAINS, shiliu)], fallback=ytdlp), shiliu, ytdlp


def test_douyin_short_link_goes_to_shiliu():
    router, shiliu, ytdlp = _router()
    assert router.download("https://v.douyin.com/x2nmVW6bMjU/").content_id == "shiliu"
    assert not ytdlp.calls


def test_douyin_share_page_goes_to_shiliu():
    router, shiliu, _ = _router()
    router.download("https://www.iesdouyin.com/share/video/7664255108602924294/?region=CN")
    assert len(shiliu.calls) == 1


def test_other_sites_fall_back_to_ytdlp():
    router, shiliu, ytdlp = _router()
    for url in (
        "https://www.bilibili.com/video/BV1xx411c7mD",
        "https://www.youtube.com/watch?v=jNQXAC9IVRw",
        "https://www.xiaohongshu.com/explore/abc",
    ):
        assert router.download(url).content_id == "ytdlp"
    assert len(ytdlp.calls) == 3
    assert not shiliu.calls


def test_lookalike_domain_does_not_match():
    """notdouyin.com 不该被当成抖音。"""
    router, shiliu, ytdlp = _router()
    assert router.download("https://notdouyin.com/video/1").content_id == "ytdlp"
    assert not shiliu.calls


def test_router_without_special_route_uses_fallback():
    ytdlp = FakeDownloader("ytdlp")
    router = RoutingDownloader([], fallback=ytdlp)
    assert router.download("https://v.douyin.com/abc/").content_id == "ytdlp"
