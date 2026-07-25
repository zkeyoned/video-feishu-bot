from __future__ import annotations

import re
from urllib.parse import urlparse


URL_PATTERN = re.compile(r"https?://[^\s<>\"'，。！？]+", re.IGNORECASE)
DOUYIN_HOSTS = {
    "douyin.com",
    "www.douyin.com",
    "m.douyin.com",
    "v.douyin.com",
    "iesdouyin.com",
    "www.iesdouyin.com",
    "v.iesdouyin.com",
}


def extract_douyin_url(text: str) -> str | None:
    for match in URL_PATTERN.finditer(text or ""):
        value = match.group(0).rstrip(")]}>，。！？")
        host = (urlparse(value).hostname or "").lower()
        if host in DOUYIN_HOSTS:
            return value
    return None

