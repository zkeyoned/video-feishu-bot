from __future__ import annotations

import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

from .models import AnalysisArtifact, ArchiveResult, DownloadedVideo, IncomingMessage
from .parsing import extract_douyin_url
from .state import StateStore


class Downloader(Protocol):
    def download(self, source_url: str) -> DownloadedVideo: ...


class Analyzer(Protocol):
    def analyze(self, video: DownloadedVideo) -> AnalysisArtifact: ...


class FeishuPort(Protocol):
    def reply_text(self, message_id: str, text: str) -> None: ...

    def archive(self, video: DownloadedVideo, analysis: AnalysisArtifact) -> ArchiveResult: ...


class VideoBotPipeline:
    def __init__(
        self,
        *,
        state: StateStore,
        downloader: Downloader,
        analyzer: Analyzer,
        feishu: FeishuPort,
        allowed_open_ids: set[str] | None = None,
    ):
        self.state = state
        self.downloader = downloader
        self.analyzer = analyzer
        self.feishu = feishu
        self.allowed_open_ids = allowed_open_ids or set()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="video-bot-job")

    def accept(self, message: IncomingMessage) -> bool:
        if self.allowed_open_ids and message.sender_open_id not in self.allowed_open_ids:
            self._safe_reply(message.message_id, "这个视频分析助手目前只对创建者开放。")
            return False
        source_url = extract_douyin_url(message.text)
        if not self.state.claim_message(message, source_url):
            return False
        self.executor.submit(self._process, message, source_url)
        return True

    def recover(self) -> int:
        rows = self.state.recoverable_messages()
        for row in rows:
            message = IncomingMessage(
                message_id=str(row["message_id"]),
                chat_id=str(row["chat_id"]),
                sender_open_id=str(row["sender_open_id"]),
                text=str(row["text"]),
            )
            self.executor.submit(self._process, message, row["source_url"])
        return len(rows)

    def shutdown(self) -> None:
        self.executor.shutdown(wait=True, cancel_futures=False)

    def _safe_reply(self, message_id: str, text: str) -> None:
        try:
            self.feishu.reply_text(message_id, text)
        except Exception as exc:
            print(f"回复飞书消息失败：{exc}", flush=True)

    def _process(self, message: IncomingMessage, source_url: str | None) -> None:
        if not source_url:
            self.state.update_message(message.message_id, "ignored")
            self._safe_reply(
                message.message_id,
                "请发送一条公开的抖音视频链接。我会自动下载、转写、分析，并把完整报告归档到视频研究知识库。",
            )
            return

        try:
            self.state.update_message(message.message_id, "downloading")
            self._safe_reply(message.message_id, "已收到链接，正在解析并下载视频。")
            video = self.downloader.download(source_url)
            self.state.update_message(
                message.message_id,
                "downloaded",
                content_id=video.content_id,
            )

            existing = self.state.get_video(video.content_id)
            if existing is not None:
                url = str(existing["document_url"])
                self.state.update_message(
                    message.message_id,
                    "completed",
                    content_id=video.content_id,
                    document_url=url,
                )
                self._safe_reply(
                    message.message_id,
                    f"这个视频已经分析归档过了：\n{url}",
                )
                return

            self.state.update_message(message.message_id, "analyzing")
            self._safe_reply(message.message_id, "视频下载完成，正在转写声音并分析画面。")
            analysis = self.analyzer.analyze(video)

            self.state.update_message(message.message_id, "archiving")
            archive = self.feishu.archive(video, analysis)
            self.state.save_video(
                content_id=video.content_id,
                source_url=video.source_url,
                title=video.title,
                document_url=archive.document_url,
                document_token=archive.document_token,
                wiki_node_token=archive.wiki_node_token,
                base_record_id=archive.base_record_id,
            )
            self.state.update_message(
                message.message_id,
                "completed",
                content_id=video.content_id,
                document_url=archive.document_url,
            )
            summary = analysis.summary.strip() or "分析已完成"
            if len(summary) > 500:
                summary = summary[:497] + "…"
            self._safe_reply(
                message.message_id,
                f"分析完成。\n\n{summary}\n\n完整分析文档：\n{archive.document_url}",
            )
        except Exception as exc:
            error = str(exc).splitlines()[0] or exc.__class__.__name__
            self.state.update_message(message.message_id, "failed", error=error[:1000])
            self._safe_reply(
                message.message_id,
                f"这次处理没有完成：{error}\n\n任务已经记录，可以修复配置后重新发送链接。",
            )
            traceback.print_exc()
