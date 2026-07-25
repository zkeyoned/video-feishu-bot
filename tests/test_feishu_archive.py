import json
from pathlib import Path

from video_feishu_bot.feishu import FeishuClient, answer_sections, build_document_blocks, select_key_frames
from video_feishu_bot.models import AnalysisArtifact, DownloadedVideo


def artifact(session_dir: Path) -> AnalysisArtifact:
    return AnalysisArtifact(
        session_dir=session_dir,
        report_path=session_dir / "report.md",
        analysis_path=session_dir / "analysis.json",
        summary="用自动化工具整理视频",
        answer="核心观点与操作步骤",
        transcript="完整语音转写",
        timeline=[{"timecode": "00:09", "event": "演示", "evidence": "画面"}],
        keywords=[{"term": "AI", "context": "工具", "timecode": "00:09"}],
        raw={},
    )


def test_select_key_frames_prefers_timeline_and_fills_slots(tmp_path: Path) -> None:
    frames = tmp_path / "frames"
    frames.mkdir()
    manifest_frames = []
    for timestamp in (0, 10, 20, 30):
        path = frames / f"frame-{timestamp}.jpg"
        path.write_bytes(b"jpeg")
        manifest_frames.append(
            {"timestamp": timestamp, "timecode": f"00:{timestamp:02d}", "path": str(path)}
        )
    (tmp_path / "manifest.json").write_text(
        json.dumps({"frames": manifest_frames}), encoding="utf-8"
    )

    selected = select_key_frames(artifact(tmp_path), limit=3)

    assert len(selected) == 3
    assert ("00:10", (frames / "frame-10.jpg").resolve()) in selected
    assert selected == sorted(selected, key=lambda item: item[0])


class RecordingFeishu(FeishuClient):
    def __init__(self) -> None:
        self.blocks: list[dict] = []
        self.fields: dict = {}

    def create_wiki_document(self, title: str) -> tuple[str, str, str]:
        return "doc1", "wik1", "https://feishu.cn/wiki/wik1"

    def append_document_blocks(self, document_token: str, blocks: list[dict]) -> None:
        self.blocks.extend(blocks)

    def append_document_image(self, document_token: str, timecode: str, image_path: Path) -> str:
        self.blocks.extend([{"block_type": 2}, {"block_type": 27}])
        return f"block-{image_path.stem}"

    def create_base_record(self, fields: dict) -> str:
        self.fields = fields
        return "rec1"


def test_archive_writes_key_frames_and_required_index_fields(tmp_path: Path) -> None:
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"jpeg")
    (tmp_path / "manifest.json").write_text(
        json.dumps({"frames": [{"timestamp": 9, "timecode": "00:09", "path": str(frame)}]}),
        encoding="utf-8",
    )
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"video")
    video = DownloadedVideo(
        content_id="123",
        source_url="https://www.douyin.com/video/123",
        title="测试视频",
        author="测试作者",
        description="",
        duration=42,
        source_created_at=0,
        video_path=video_path,
    )
    client = RecordingFeishu()

    result = client.archive(video, artifact(tmp_path))

    assert result.base_record_id == "rec1"
    assert any(block.get("block_type") == 27 for block in client.blocks)
    assert set(client.fields) == {
        "视频标题",
        "作者",
        "原链接",
        "摘要",
        "分类",
        "标签",
        "时长",
        "分析状态",
        "分析时间",
        "文档链接",
        "本地保存状态",
    }
    assert client.fields["标签"] == ["AI"]
    assert isinstance(client.fields["分析时间"], int)
    assert client.fields["原链接"]["link"].endswith("/video/123")
    assert client.fields["文档链接"]["text"] == "打开分析文档"


def test_document_has_separate_required_analysis_sections(tmp_path: Path) -> None:
    base = artifact(tmp_path)
    structured = AnalysisArtifact(
        **{
            **base.__dict__,
            "answer": "核心观点：观点 A\n操作步骤：1. 打开工具\n2. 导入视频\n可复用启发：先结构化再归档",
        }
    )
    core, steps, insights = answer_sections(structured)
    assert core == "观点 A"
    assert "导入视频" in steps
    assert insights == "先结构化再归档"
    blocks = build_document_blocks(
        DownloadedVideo("1", "https://v.douyin.com/a/", "标题", "作者", "", 1, 0, tmp_path / "v.mp4"),
        structured,
    )
    headings = [
        block["heading2"]["elements"][0]["text_run"]["content"]
        for block in blocks
        if block.get("block_type") == 4
    ]
    assert "核心观点" in headings
    assert "操作步骤" in headings
    assert "可复用启发" in headings


def test_document_batches_omit_fragile_optional_index() -> None:
    client = object.__new__(FeishuClient)
    requests: list[dict] = []
    client._request = lambda method, path, json_body=None: requests.append(json_body) or {}
    client.append_document_blocks("doc1", [{"block_type": 2}] * 51)
    assert all("index" not in request for request in requests)
    assert [len(request["children"]) for request in requests] == [50, 1]


def test_sections_never_triplicate_summary(tmp_path: Path) -> None:
    base = artifact(tmp_path)
    only_summary = AnalysisArtifact(
        **{**base.__dict__, "answer": "", "summary": "这是一段完整的整体分析。"}
    )
    core, steps, insights = answer_sections(only_summary)
    assert core == "这是一段完整的整体分析。"
    assert steps != core and insights != core
    assert "未单独提炼" in steps and "未单独提炼" in insights


def test_model_mislabels_steps_with_insights(tmp_path: Path) -> None:
    base = artifact(tmp_path)
    bad = AnalysisArtifact(
        **{
            **base.__dict__,
            "summary": "整段摘要。",
            "answer": (
                "操作步骤：可复用启发：可复用启发：① 多任务连续执行；② 体验设计。\n"
                "可复用启发：可复用启发：① 多任务连续执行；② 体验设计。"
            ),
        }
    )
    core, steps, insights = answer_sections(bad)
    assert core == "整段摘要。"
    assert insights.startswith("① 多任务") and "可复用启发" not in insights
    assert steps != insights and "未单独提炼" in steps
