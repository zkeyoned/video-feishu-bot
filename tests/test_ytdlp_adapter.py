from __future__ import annotations

import json
from pathlib import Path

import pytest

from video_feishu_bot.ytdlp_adapter import YtDlpDownloadError, YtDlpDownloader

INFO = {
    "id": "7664255108602924294",
    "extractor": "DouYin",
    "title": "  盘点一周 AI 大事  ",
    "uploader": "产品君",
    "description": "本周要闻",
    "duration": 178.3,
    "timestamp": 1784626391,
    "webpage_url": "https://www.douyin.com/video/7664255108602924294",
}


def _downloader(tmp_path: Path, monkeypatch, printed: str, info: dict = INFO):
    downloader = YtDlpDownloader(tmp_path)
    monkeypatch.setattr(downloader, "_resolve_binary", lambda: "/usr/bin/true")

    calls: list[list[str]] = []

    def fake_run(args, *, timeout):
        calls.append(args)
        return json.dumps(info) if "-J" in args else printed

    monkeypatch.setattr(downloader, "_run", fake_run)
    return downloader, calls


def test_maps_metadata_onto_downloaded_video(tmp_path, monkeypatch):
    video = tmp_path / "7664255108602924294.mp4"
    video.write_bytes(b"fake")
    (tmp_path / "7664255108602924294.jpg").write_bytes(b"cover")

    downloader, _ = _downloader(tmp_path, monkeypatch, f"{video}\n")
    result = downloader.download("https://v.douyin.com/abc/")

    assert result.content_id == "7664255108602924294"
    assert result.title == "盘点一周 AI 大事"
    assert result.author == "产品君"
    assert result.duration == 178
    assert result.source_created_at == 1784626391
    assert result.video_path == video.resolve()
    assert result.cover_path is not None and result.cover_path.name.endswith(".jpg")


def test_non_douyin_ids_get_extractor_prefix(tmp_path, monkeypatch):
    video = tmp_path / "dQw4w9WgXcQ.mp4"
    video.write_bytes(b"fake")
    info = {**INFO, "id": "dQw4w9WgXcQ", "extractor": "youtube"}

    downloader, _ = _downloader(tmp_path, monkeypatch, f"{video}\n", info)
    assert downloader.download("https://youtu.be/dQw4w9WgXcQ").content_id == "youtube-dQw4w9WgXcQ"


def test_upload_date_is_used_when_timestamp_missing(tmp_path, monkeypatch):
    video = tmp_path / "x.mp4"
    video.write_bytes(b"fake")
    info = {**INFO, "id": "x", "timestamp": None, "upload_date": "20260719"}

    downloader, _ = _downloader(tmp_path, monkeypatch, f"{video}\n", info)
    assert downloader.download("https://v.douyin.com/x/").source_created_at > 0


def test_playlist_is_rejected_before_downloading(tmp_path, monkeypatch):
    downloader, calls = _downloader(tmp_path, monkeypatch, "", {"_type": "playlist"})

    with pytest.raises(YtDlpDownloadError, match="合集"):
        downloader.download("https://www.douyin.com/collection/1")
    assert len(calls) == 1, "元信息判定是合集后就不应该再去下载"


def test_missing_file_raises(tmp_path, monkeypatch):
    downloader, _ = _downloader(tmp_path, monkeypatch, "/nowhere/missing.mp4\n")

    with pytest.raises(YtDlpDownloadError, match="找不到文件"):
        downloader.download("https://v.douyin.com/abc/")


def test_missing_binary_raises_with_install_hint(tmp_path):
    downloader = YtDlpDownloader(tmp_path, binary="yt-dlp-does-not-exist")

    with pytest.raises(YtDlpDownloadError, match="brew install yt-dlp"):
        downloader.download("https://v.douyin.com/abc/")
