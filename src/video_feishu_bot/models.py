from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class IncomingMessage:
    message_id: str
    chat_id: str
    sender_open_id: str
    text: str


@dataclass(frozen=True)
class DownloadedVideo:
    content_id: str
    source_url: str
    title: str
    author: str
    description: str
    duration: int
    source_created_at: int
    video_path: Path
    cover_path: Path | None = None


@dataclass(frozen=True)
class AnalysisArtifact:
    session_dir: Path
    report_path: Path
    analysis_path: Path
    summary: str
    answer: str
    transcript: str
    timeline: list[dict[str, Any]]
    keywords: list[dict[str, Any]]
    raw: dict[str, Any]


@dataclass(frozen=True)
class ArchiveResult:
    document_token: str
    wiki_node_token: str
    document_url: str
    base_record_id: str

