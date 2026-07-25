from __future__ import annotations

from urllib.parse import urlparse

from .models import DownloadedVideo
from .pipeline import Downloader


class RoutingDownloader:
    """按站点挑下载器。

    不同站点适合的取流方式不一样。抖音的接口现在要 Cookie，而它的手机分享页
    （具体实现属于私有引擎，未随本仓库发行）——
    所以在抖音上比通用工具更省事。其余上千个站点交给 yt-dlp 更划算。

    专用下载器缺席时（比如公开发行版没带拾流），自动落到兜底下载器，
    不需要改配置。
    """

    def __init__(self, routes: list[tuple[tuple[str, ...], Downloader]], fallback: Downloader):
        self.routes = routes
        self.fallback = fallback

    def pick(self, source_url: str) -> Downloader:
        host = (urlparse(source_url).hostname or "").lower()
        for domains, downloader in self.routes:
            if any(host == d or host.endswith(f".{d}") for d in domains):
                return downloader
        return self.fallback

    def download(self, source_url: str) -> DownloadedVideo:
        return self.pick(source_url).download(source_url)


# 抖音的几个分享域名。v.douyin.com 是短链，iesdouyin.com 是分享页。
DOUYIN_DOMAINS = ("douyin.com", "iesdouyin.com")
