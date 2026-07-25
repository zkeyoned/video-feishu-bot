from __future__ import annotations

import signal
import sys
from pathlib import Path

from .config import BotSettings
from .feishu import FeishuClient, start_websocket
from .pipeline import Downloader, VideoBotPipeline
from .state import StateStore
from .video_adapter import VideoAnalyzer
from .routing_downloader import DOUYIN_DOMAINS, RoutingDownloader
from .ytdlp_adapter import _DEFAULT_FORMAT, YtDlpDownloader


def _build_ytdlp(settings: BotSettings) -> YtDlpDownloader:
    return YtDlpDownloader(
        settings.download_dir,
        video_format=settings.ytdlp_format or _DEFAULT_FORMAT,
        cookies_from_browser=settings.ytdlp_cookies_from_browser,
    )


def _load_shiliu(settings: BotSettings):
    """拾流是本机私有引擎，公开发行版里没有这个模块，所以按需导入。"""
    try:
        from .shiliu_adapter import ShiliuDownloader
    except ImportError:
        return None
    if not (settings.shiliu_root / "server.py").is_file():
        return None
    return ShiliuDownloader(settings.shiliu_root)


def build_downloader(settings: BotSettings) -> Downloader:
    """按配置选下载器。

    auto（默认）：抖音交给拾流（不需要 Cookie），其余站点交给 yt-dlp；
    拾流不在时整个落到 yt-dlp，配置不用改。
    """
    if settings.downloader == "shiliu":
        shiliu = _load_shiliu(settings)
        if shiliu is None:
            raise RuntimeError(f"配置要求用拾流，但找不到可用的拾流项目：{settings.shiliu_root}")
        return shiliu
    if settings.downloader == "ytdlp":
        return _build_ytdlp(settings)

    ytdlp = _build_ytdlp(settings)
    shiliu = _load_shiliu(settings)
    if shiliu is None:
        return ytdlp
    return RoutingDownloader([(DOUYIN_DOMAINS, shiliu)], fallback=ytdlp)


def build_pipeline(settings: BotSettings) -> tuple[VideoBotPipeline, FeishuClient]:
    settings.validate_local_projects()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    feishu = FeishuClient(
        app_id=settings.app_id,
        app_secret=settings.app_secret,
        tenant_url=settings.tenant_url,
        wiki_space_id=settings.wiki_space_id,
        wiki_parent_node_token=settings.wiki_parent_node_token,
        base_app_token=settings.base_app_token,
        base_table_id=settings.base_table_id,
    )
    pipeline = VideoBotPipeline(
        state=StateStore(settings.data_dir / "video-bot.db"),
        downloader=build_downloader(settings),
        analyzer=VideoAnalyzer(
            settings.video_agent_root,
            settings.env_path,
            mode=settings.analysis_mode,
            question=settings.analysis_question,
        ),
        feishu=feishu,
        allowed_open_ids=set(settings.allowed_open_ids),
    )
    return pipeline, feishu


def main() -> None:
    project_root = Path(__file__).resolve().parents[2]
    settings = BotSettings.from_env(project_root)
    pipeline, feishu = build_pipeline(settings)
    recovered = pipeline.recover()
    if recovered:
        print(f"已恢复 {recovered} 个未完成任务", flush=True)

    def stop(*_: object) -> None:
        pipeline.shutdown()
        feishu.close()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print("视频分析助手正在连接飞书长连接…", flush=True)
    try:
        start_websocket(settings.app_id, settings.app_secret, pipeline.accept)
    finally:
        pipeline.shutdown()
        feishu.close()


if __name__ == "__main__":
    main()
