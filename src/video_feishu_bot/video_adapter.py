from __future__ import annotations

import sys
import os
import subprocess
import threading
from pathlib import Path

from .models import AnalysisArtifact, DownloadedVideo


def normalize_answer(value: object) -> str:
    if not isinstance(value, dict):
        return str(value or "")

    def section_text(raw: object, label: str) -> str:
        text = str(raw or "").strip()
        for separator in ("：", ":"):
            prefix = f"{label}{separator}"
            if text.startswith(prefix):
                return text[len(prefix) :].strip()
        return text

    core = section_text(
        value.get("核心观点")
        or value.get("core_points")
        or value.get("core_view")
        or value.get("core_viewpoint"),
        "核心观点",
    )
    raw_steps = (
        value.get("操作步骤")
        or value.get("steps")
        or value.get("operation_steps")
        or value.get("operational_steps")
        or []
    )
    if isinstance(raw_steps, list):
        steps = "\n".join(str(item).strip() for item in raw_steps if str(item).strip())
    else:
        steps = section_text(raw_steps, "操作步骤")
    insights = section_text(
        value.get("可复用启发") or value.get("reusable_insights"),
        "可复用启发",
    )
    sections = []
    if core:
        sections.append(f"核心观点：{core}")
    if steps:
        sections.append(f"操作步骤：{steps}")
    if insights:
        sections.append(f"可复用启发：{insights}")
    return "\n".join(sections)


class VideoAnalyzer:
    def __init__(self, project_root: Path, env_path: Path, *, mode: str, question: str):
        self.project_root = project_root.expanduser().resolve()
        self.env_path = env_path.expanduser().resolve()
        self.mode = mode
        self.question = question
        self._lock = threading.Lock()
        source_root = str(self.project_root / "src")
        if source_root not in sys.path:
            sys.path.insert(0, source_root)

    @staticmethod
    def _load_keychain_api_key() -> None:
        """Reuse the desktop app's key without copying it into dotenv or logs."""
        if os.environ.get("VIDEO_AGENT_API_KEY", "").strip():
            return
        result = subprocess.run(
            [
                "/usr/bin/security",
                "find-generic-password",
                "-s",
                "com.kongke.VideoAgentDesktop",
                "-a",
                "vision-api-key",
                "-w",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        api_key = result.stdout.strip() if result.returncode == 0 else ""
        if api_key:
            os.environ["VIDEO_AGENT_API_KEY"] = api_key

    def analyze(self, video: DownloadedVideo) -> AnalysisArtifact:
        # The configured vision provider and local Whisper are intentionally run
        # one video at a time to control memory, token cost, and output ordering.
        with self._lock:
            from video_agent.config import Settings
            from video_agent.workflow import analyze_video

            self._load_keychain_api_key()
            settings = Settings.from_env(self.env_path)
            settings.require_api_key()
            raw = analyze_video(
                video.video_path,
                settings,
                question=self.question,
                mode=self.mode,
            )
        session = Path(str(raw["session_dir"])).expanduser().resolve()
        result = raw.get("result") or {}
        report_path = session / "report.md"
        analysis_path = session / "analysis.json"
        if not report_path.is_file() or not analysis_path.is_file():
            raise RuntimeError("视频分析结束，但报告文件不完整")
        return AnalysisArtifact(
            session_dir=session,
            report_path=report_path,
            analysis_path=analysis_path,
            summary=str(result.get("summary") or ""),
            answer=normalize_answer(result.get("answer")),
            transcript=str(raw.get("transcript") or ""),
            timeline=list(result.get("timeline") or []),
            keywords=list(result.get("keywords") or []),
            raw=raw,
        )
