from __future__ import annotations

import json
import os
from pathlib import Path

import lark_oapi as lark


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
EXAMPLE_PATH = ROOT / ".env.example"


def update_env(values: dict[str, str]) -> None:
    source = ENV_PATH if ENV_PATH.is_file() else EXAMPLE_PATH
    lines = source.read_text(encoding="utf-8").splitlines()
    updated: set[str] = set()
    output: list[str] = []
    for line in lines:
        if "=" not in line or line.lstrip().startswith("#"):
            output.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in values:
            output.append(f"{key}={json.dumps(values[key], ensure_ascii=False)}")
            updated.add(key)
        else:
            output.append(line)
    for key, value in values.items():
        if key not in updated:
            output.append(f"{key}={json.dumps(value, ensure_ascii=False)}")
    ENV_PATH.write_text("\n".join(output) + "\n", encoding="utf-8")
    os.chmod(ENV_PATH, 0o600)


def on_qr_code(info: dict) -> None:
    print(f"VERIFICATION_URL={info['url']}", flush=True)
    print(f"EXPIRES_IN={info['expire_in']}", flush=True)


def main() -> None:
    result = lark.register_app(
        on_qr_code=on_qr_code,
        source="video-feishu-bot",
        create_only=True,
        app_preset={
            "name": "视频分析助手",
            "desc": "接收抖音视频链接，自动转写、分析并归档到视频研究知识库。",
        },
        addons={
            "preset": True,
            "scopes": {
                "tenant": [
                    "wiki:wiki",
                    "bitable:app",
                ]
            },
        },
    )
    update_env(
        {
            "FEISHU_APP_ID": str(result["client_id"]),
            "FEISHU_APP_SECRET": str(result["client_secret"]),
        }
    )
    print("APP_CREDENTIALS_SAVED=yes", flush=True)


if __name__ == "__main__":
    main()
