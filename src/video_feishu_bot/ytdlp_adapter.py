from __future__ import annotations

import json
import shutil
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from .models import DownloadedVideo

# 分析只看抽出来的帧，4K 源除了拖慢下载和占硬盘并没有额外信息，
# 所以默认封顶 1080p，取不到再退回最佳画质。可用 VIDEO_BOT_YTDLP_FORMAT 覆盖。
_DEFAULT_FORMAT = "bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/b"


class YtDlpDownloadError(RuntimeError):
    """yt-dlp 没能取到可下载的视频。"""


class YtDlpDownloader:
    """用 yt-dlp 实现 pipeline 的 Downloader 协议。

    这是开源版的默认下载器：它支持上千个站点（抖音、B 站、YouTube、小红书…），
    而且下载这件事的合规责任落在 yt-dlp 自己身上，不需要本项目维护解析逻辑。

    与拾流适配器可以互换 —— 两边返回同样的 DownloadedVideo。
    """

    def __init__(
        self,
        download_root: Path,
        binary: str = "yt-dlp",
        video_format: str = _DEFAULT_FORMAT,
        cookies_from_browser: str = "",
    ):
        self.download_root = download_root.expanduser().resolve()
        self.binary = binary
        self.video_format = video_format or _DEFAULT_FORMAT
        # 有些站点（抖音就是）要求带 cookie 才给下载。留空表示不碰浏览器数据。
        self.cookies_from_browser = cookies_from_browser.strip()
        self._lock = threading.Lock()

    def _cookie_args(self) -> list[str]:
        if not self.cookies_from_browser:
            return []
        return ["--cookies-from-browser", self.cookies_from_browser]

    def _resolve_binary(self) -> str:
        found = shutil.which(self.binary)
        if not found:
            raise YtDlpDownloadError(
                f"找不到 {self.binary}。安装后重试：brew install yt-dlp（或 pip install yt-dlp）"
            )
        return found

    def _run(self, args: list[str], *, timeout: int) -> str:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip().splitlines()
            reason = detail[-1] if detail else f"退出码 {result.returncode}"
            raise YtDlpDownloadError(f"yt-dlp 失败：{reason}")
        return result.stdout

    def download(self, source_url: str) -> DownloadedVideo:
        # 分析流程一次只处理一个视频，这里同样串行，避免并发写同一个目录。
        with self._lock:
            return self._download_locked(source_url)

    def _download_locked(self, source_url: str) -> DownloadedVideo:
        binary = self._resolve_binary()
        self.download_root.mkdir(parents=True, exist_ok=True)

        # 第一步：只取元信息，拿不到就不用浪费带宽去下。
        raw = self._run(
            [binary, "-J", "--no-playlist", "--no-warnings", *self._cookie_args(), source_url],
            timeout=120,
        )
        try:
            info = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise YtDlpDownloadError("yt-dlp 返回的元信息不是合法 JSON") from exc
        if info.get("_type") == "playlist":
            raise YtDlpDownloadError("这个链接是合集/播放列表，请改用单个作品的链接")

        # 第二步：真正下载，并让 yt-dlp 打印出最终落盘路径。
        printed = self._run(
            [
                binary,
                "--no-playlist",
                "--no-warnings",
                *self._cookie_args(),
                "-f",
                self.video_format,
                "--merge-output-format",
                "mp4",
                "--write-thumbnail",
                "--convert-thumbnails",
                "jpg",
                "-o",
                str(self.download_root / "%(id)s.%(ext)s"),
                "--print",
                "after_move:filepath",
                "--no-simulate",
                source_url,
            ],
            timeout=3600,
        )

        video_path = self._pick_video_path(printed, info)
        if not video_path.is_file():
            raise YtDlpDownloadError(f"yt-dlp 报告下载完成，但找不到文件：{video_path}")

        return DownloadedVideo(
            content_id=self._content_id(info),
            source_url=str(info.get("webpage_url") or source_url),
            title=self._clean(info.get("title")) or "未命名视频",
            author=self._clean(info.get("uploader") or info.get("channel") or info.get("uploader_id")),
            description=self._clean(info.get("description")),
            duration=int(info.get("duration") or 0),
            source_created_at=self._timestamp(info),
            video_path=video_path,
            cover_path=self._find_cover(video_path),
        )

    def _pick_video_path(self, printed: str, info: dict) -> Path:
        for line in reversed(printed.strip().splitlines()):
            candidate = line.strip()
            # --print 的输出里可能混进进度行，只认真实存在的文件。
            if candidate and Path(candidate).is_file():
                return Path(candidate).resolve()
        # 兜底：按 -o 模板自己拼一次。
        return (self.download_root / f"{info.get('id')}.mp4").resolve()

    def _find_cover(self, video_path: Path) -> Path | None:
        for suffix in (".jpg", ".jpeg", ".png", ".webp"):
            candidate = video_path.with_suffix(suffix)
            if candidate.is_file():
                return candidate
        return None

    @staticmethod
    def _clean(value: object) -> str:
        return str(value).strip() if value else ""

    @staticmethod
    def _content_id(info: dict) -> str:
        """抖音保持裸 id，跟拾流的历史记录对得上；其他站点加前缀防撞号。"""
        raw_id = str(info.get("id") or "").strip()
        if not raw_id:
            raise YtDlpDownloadError("yt-dlp 没有返回视频 id")
        extractor = str(info.get("extractor") or "").strip().lower()
        if not extractor or "douyin" in extractor:
            return raw_id
        return f"{extractor}-{raw_id}"

    @staticmethod
    def _timestamp(info: dict) -> int:
        raw = info.get("timestamp")
        if raw:
            try:
                return int(raw)
            except (TypeError, ValueError):
                pass
        upload_date = str(info.get("upload_date") or "").strip()
        if len(upload_date) == 8 and upload_date.isdigit():
            try:
                return int(datetime.strptime(upload_date, "%Y%m%d").timestamp())
            except ValueError:
                return 0
        return 0
