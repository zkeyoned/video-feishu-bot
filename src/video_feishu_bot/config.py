from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"缺少配置：{name}")
    return value


@dataclass(frozen=True)
class BotSettings:
    project_root: Path
    env_path: Path
    data_dir: Path
    shiliu_root: Path
    video_agent_root: Path
    app_id: str
    app_secret: str
    tenant_url: str
    wiki_space_id: str
    wiki_parent_node_token: str
    base_app_token: str
    base_table_id: str
    allowed_open_ids: tuple[str, ...]
    analysis_mode: str
    analysis_question: str
    downloader: str
    download_dir: Path
    ytdlp_format: str
    ytdlp_cookies_from_browser: str

    @classmethod
    def from_env(cls, project_root: Path | None = None, *, require_feishu: bool = True) -> "BotSettings":
        root = (project_root or Path.cwd()).expanduser().resolve()
        env_path = root / ".env"
        load_dotenv(env_path)

        default_parent = root.parent
        shiliu = Path(os.environ.get("SHILIU_PROJECT_ROOT", default_parent / "codex-zero"))
        video_agent = Path(os.environ.get("VIDEO_AGENT_PROJECT_ROOT", default_parent / "video-agent"))
        data = Path(os.environ.get("VIDEO_BOT_DATA_DIR", root / "data"))
        if not data.is_absolute():
            data = root / data

        get = _required if require_feishu else lambda name: os.environ.get(name, "").strip()
        mode = os.environ.get("VIDEO_BOT_ANALYSIS_MODE", "narration").strip() or "narration"
        if mode not in {"balanced", "narration"}:
            raise RuntimeError("VIDEO_BOT_ANALYSIS_MODE 只能是 balanced 或 narration")

        # auto：抖音走拾流（不要 Cookie），其余走 yt-dlp；没有拾流就全走 yt-dlp。
        downloader = os.environ.get("VIDEO_BOT_DOWNLOADER", "auto").strip().lower() or "auto"
        if downloader not in {"auto", "ytdlp", "shiliu"}:
            raise RuntimeError("VIDEO_BOT_DOWNLOADER 只能是 auto、ytdlp 或 shiliu")
        download_dir = Path(os.environ.get("VIDEO_BOT_DOWNLOAD_DIR", root / "downloads"))
        if not download_dir.is_absolute():
            download_dir = root / download_dir
        return cls(
            project_root=root,
            env_path=env_path,
            data_dir=data.expanduser().resolve(),
            shiliu_root=shiliu.expanduser().resolve(),
            video_agent_root=video_agent.expanduser().resolve(),
            app_id=get("FEISHU_APP_ID"),
            app_secret=get("FEISHU_APP_SECRET"),
            tenant_url=os.environ.get("FEISHU_TENANT_URL", "https://feishu.cn").strip().rstrip("/")
            or "https://feishu.cn",
            wiki_space_id=get("FEISHU_WIKI_SPACE_ID"),
            wiki_parent_node_token=os.environ.get("FEISHU_WIKI_PARENT_NODE_TOKEN", "").strip(),
            base_app_token=get("FEISHU_BASE_APP_TOKEN"),
            base_table_id=get("FEISHU_BASE_TABLE_ID"),
            allowed_open_ids=tuple(
                value.strip()
                for value in os.environ.get("FEISHU_ALLOWED_OPEN_IDS", "").split(",")
                if value.strip()
            ),
            analysis_mode=mode,
            analysis_question=os.environ.get(
                "VIDEO_BOT_QUESTION",
                "完整理解这个视频，并提炼核心观点、操作步骤、时间线和可复用启发。",
            ).strip(),
            downloader=downloader,
            download_dir=download_dir.expanduser().resolve(),
            ytdlp_format=os.environ.get("VIDEO_BOT_YTDLP_FORMAT", "").strip(),
            ytdlp_cookies_from_browser=os.environ.get(
                "VIDEO_BOT_YTDLP_COOKIES_FROM_BROWSER", ""
            ).strip(),
        )

    def validate_local_projects(self) -> None:
        # 只有选了拾流才要求它存在，用 yt-dlp 的人不需要这个目录。
        if self.downloader == "shiliu" and not (self.shiliu_root / "server.py").is_file():
            raise RuntimeError(f"找不到拾流项目：{self.shiliu_root}")
        if not (self.video_agent_root / "pyproject.toml").is_file():
            raise RuntimeError(f"找不到 video-agent 项目：{self.video_agent_root}")
