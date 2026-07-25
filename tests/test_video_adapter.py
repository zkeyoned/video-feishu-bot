import os
from pathlib import Path
from unittest.mock import Mock, patch

from video_feishu_bot.video_adapter import VideoAnalyzer, normalize_answer


def test_keychain_api_key_is_loaded_without_overwriting_environment() -> None:
    with patch.dict(os.environ, {}, clear=True), patch(
        "video_feishu_bot.video_adapter.subprocess.run",
        return_value=Mock(returncode=0, stdout="secret-from-keychain\n"),
    ) as run:
        VideoAnalyzer._load_keychain_api_key()
        assert os.environ["VIDEO_AGENT_API_KEY"] == "secret-from-keychain"
        run.assert_called_once()


def test_existing_api_key_does_not_touch_keychain() -> None:
    with patch.dict(os.environ, {"VIDEO_AGENT_API_KEY": "already-set"}, clear=True), patch(
        "video_feishu_bot.video_adapter.subprocess.run"
    ) as run:
        VideoAnalyzer._load_keychain_api_key()
        run.assert_not_called()


def test_structured_answer_is_normalized_for_document_sections() -> None:
    value = normalize_answer(
        {
            "核心观点": "观点",
            "操作步骤": ["1. 第一步", "2. 第二步"],
            "可复用启发": "启发",
        }
    )
    assert value == "核心观点：观点\n操作步骤：1. 第一步\n2. 第二步\n可复用启发：启发"


def test_video_agent_answer_fields_are_preserved_without_duplicate_labels() -> None:
    value = normalize_answer(
        {
            "core_view": "核心观点：观点 A",
            "operation_steps": ["1. 第一步", "2. 第二步"],
            "reusable_insights": "可复用启发：启发 B",
        }
    )

    assert value == (
        "核心观点：观点 A\n"
        "操作步骤：1. 第一步\n2. 第二步\n"
        "可复用启发：启发 B"
    )


def test_video_agent_alternative_answer_fields_are_preserved() -> None:
    value = normalize_answer(
        {
            "core_viewpoint": "核心观点：观点 C",
            "operational_steps": "操作步骤：1. 执行操作",
            "reusable_insights": "可复用启发：启发 D",
        }
    )

    assert value == (
        "核心观点：观点 C\n"
        "操作步骤：1. 执行操作\n"
        "可复用启发：启发 D"
    )
