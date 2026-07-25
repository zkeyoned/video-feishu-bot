from __future__ import annotations

from pathlib import Path

from video_feishu_bot.models import (
    AnalysisArtifact,
    ArchiveResult,
    DownloadedVideo,
    IncomingMessage,
)
from video_feishu_bot.pipeline import VideoBotPipeline
from video_feishu_bot.state import StateStore


class FakeDownloader:
    calls = 0

    def download(self, source_url: str) -> DownloadedVideo:
        self.calls += 1
        return DownloadedVideo(
            content_id="123",
            source_url=source_url,
            title="测试视频",
            author="测试作者",
            description="",
            duration=12,
            source_created_at=0,
            video_path=Path("/tmp/test.mp4"),
        )


class FakeAnalyzer:
    calls = 0

    def analyze(self, video: DownloadedVideo) -> AnalysisArtifact:
        self.calls += 1
        return AnalysisArtifact(
            session_dir=Path("/tmp/report"),
            report_path=Path("/tmp/report/report.md"),
            analysis_path=Path("/tmp/report/analysis.json"),
            summary="这是摘要",
            answer="这是回答",
            transcript="这是转写",
            timeline=[],
            keywords=[],
            raw={},
        )


class FakeFeishu:
    def __init__(self):
        self.replies: list[str] = []
        self.archive_calls = 0

    def reply_text(self, message_id: str, text: str) -> None:
        self.replies.append(text)

    def archive(self, video: DownloadedVideo, analysis: AnalysisArtifact) -> ArchiveResult:
        self.archive_calls += 1
        return ArchiveResult("doc1", "wik1", "https://example.feishu.cn/wiki/wik1", "rec1")


def test_end_to_end_pipeline_and_content_dedup(tmp_path: Path) -> None:
    downloader = FakeDownloader()
    analyzer = FakeAnalyzer()
    feishu = FakeFeishu()
    pipeline = VideoBotPipeline(
        state=StateStore(tmp_path / "state.db"),
        downloader=downloader,
        analyzer=analyzer,
        feishu=feishu,
    )
    first = IncomingMessage("om_1", "oc_1", "ou_1", "https://v.douyin.com/a/")
    second = IncomingMessage("om_2", "oc_1", "ou_1", "https://v.douyin.com/a/")
    assert pipeline.accept(first)
    pipeline.shutdown()
    assert feishu.archive_calls == 1
    assert analyzer.calls == 1
    assert any("完整分析文档" in reply for reply in feishu.replies)

    # A new process would rebuild the executor but reuse the persistent state.
    second_pipeline = VideoBotPipeline(
        state=StateStore(tmp_path / "state.db"),
        downloader=downloader,
        analyzer=analyzer,
        feishu=feishu,
    )
    assert second_pipeline.accept(second)
    second_pipeline.shutdown()
    assert feishu.archive_calls == 1
    assert analyzer.calls == 1
    assert any("已经分析归档过" in reply for reply in feishu.replies)


def test_rejects_sender_outside_allowlist(tmp_path: Path) -> None:
    downloader = FakeDownloader()
    analyzer = FakeAnalyzer()
    feishu = FakeFeishu()
    pipeline = VideoBotPipeline(
        state=StateStore(tmp_path / "state.db"),
        downloader=downloader,
        analyzer=analyzer,
        feishu=feishu,
        allowed_open_ids={"ou_owner"},
    )
    message = IncomingMessage("om_other", "oc_1", "ou_other", "https://v.douyin.com/a/")
    assert pipeline.accept(message) is False
    pipeline.shutdown()
    assert downloader.calls == 0
    assert any("只对创建者开放" in reply for reply in feishu.replies)
