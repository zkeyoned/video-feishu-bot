from pathlib import Path

from video_feishu_bot.models import IncomingMessage
from video_feishu_bot.state import StateStore


def test_message_id_is_claimed_once(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    message = IncomingMessage("om_1", "oc_1", "ou_1", "https://v.douyin.com/a/")
    assert store.claim_message(message, "https://v.douyin.com/a/") is True
    assert store.claim_message(message, "https://v.douyin.com/a/") is False


def test_completed_video_can_be_reused(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    store.save_video(
        content_id="123",
        source_url="https://www.douyin.com/video/123",
        title="测试",
        document_url="https://example.feishu.cn/wiki/wik1",
        document_token="doc1",
        wiki_node_token="wik1",
        base_record_id="rec1",
    )
    assert store.get_video("123")["document_url"].endswith("/wiki/wik1")

