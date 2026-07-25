from video_feishu_bot.parsing import extract_douyin_url


def test_extracts_douyin_url_from_share_text() -> None:
    text = "复制打开抖音，看看这个作品 https://v.douyin.com/AbC123/ 真的很好"
    assert extract_douyin_url(text) == "https://v.douyin.com/AbC123/"


def test_ignores_unrelated_url() -> None:
    assert extract_douyin_url("https://example.com/video/1") is None

