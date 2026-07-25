from __future__ import annotations

import json
import mimetypes
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable

import httpx

from .models import AnalysisArtifact, ArchiveResult, DownloadedVideo, IncomingMessage


class FeishuAPIError(RuntimeError):
    pass


class FeishuClient:
    API_ROOT = "https://open.feishu.cn/open-apis"

    def __init__(
        self,
        *,
        app_id: str,
        app_secret: str,
        tenant_url: str,
        wiki_space_id: str,
        wiki_parent_node_token: str,
        base_app_token: str,
        base_table_id: str,
    ):
        self.app_id = app_id
        self.app_secret = app_secret
        self.tenant_url = tenant_url.rstrip("/")
        self.wiki_space_id = wiki_space_id
        self.wiki_parent_node_token = wiki_parent_node_token
        self.base_app_token = base_app_token
        self.base_table_id = base_table_id
        self._http = httpx.Client(timeout=30)
        self._token = ""
        self._token_expires_at = 0.0
        self._token_lock = threading.Lock()

    def close(self) -> None:
        self._http.close()

    def _tenant_token(self) -> str:
        with self._token_lock:
            if self._token and time.time() < self._token_expires_at - 60:
                return self._token
            response = self._http.post(
                f"{self.API_ROOT}/auth/v3/tenant_access_token/internal",
                json={"app_id": self.app_id, "app_secret": self.app_secret},
            )
            payload = response.json()
            if response.is_error or payload.get("code") != 0:
                raise FeishuAPIError(f"获取飞书应用凭证失败：{payload.get('msg') or response.status_code}")
            self._token = str(payload["tenant_access_token"])
            self._token_expires_at = time.time() + int(payload.get("expire") or 7200)
            return self._token

    def _request(self, method: str, path: str, *, json_body: dict | None = None) -> dict:
        response = self._http.request(
            method,
            f"{self.API_ROOT}{path}",
            headers={
                "Authorization": f"Bearer {self._tenant_token()}",
                "Content-Type": "application/json; charset=utf-8",
            },
            json=json_body,
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise FeishuAPIError(f"飞书接口返回了非 JSON 响应（HTTP {response.status_code}）") from exc
        if response.is_error or payload.get("code") != 0:
            raise FeishuAPIError(
                f"飞书接口失败 {path}：{payload.get('msg') or response.status_code}"
            )
        return payload

    def reply_text(self, message_id: str, text: str) -> None:
        self._request(
            "POST",
            f"/im/v1/messages/{message_id}/reply",
            json_body={
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
        )

    def create_wiki_document(self, title: str) -> tuple[str, str, str]:
        body: dict[str, Any] = {
            "obj_type": "docx",
            "node_type": "origin",
            "title": title[:200],
        }
        if self.wiki_parent_node_token:
            body["parent_node_token"] = self.wiki_parent_node_token
        payload = self._request(
            "POST",
            f"/wiki/v2/spaces/{self.wiki_space_id}/nodes",
            json_body=body,
        )
        node = payload.get("data", {}).get("node", {})
        document_token = str(node.get("obj_token") or "")
        node_token = str(node.get("node_token") or "")
        if not document_token or not node_token:
            raise FeishuAPIError("飞书创建了知识库节点，但没有返回文档标识")
        document_url = str(node.get("url") or "").strip()
        if not document_url:
            document_url = f"{self.tenant_url or 'https://feishu.cn'}/wiki/{node_token}"
        return document_token, node_token, document_url

    def append_document_blocks(
        self,
        document_token: str,
        blocks: list[dict[str, Any]],
    ) -> None:
        # The API accepts at most 50 children per call. Preserve order by appending
        # batches sequentially to the document root block.
        for offset in range(0, len(blocks), 50):
            batch = blocks[offset : offset + 50]
            self._request(
                "POST",
                f"/docx/v1/documents/{document_token}/blocks/{document_token}/children?document_revision_id=-1",
                # Omit the optional index. Feishu then appends atomically.
                # Explicit tail indexes can mutate the document and still
                # return `invalid param` for long documents.
                json_body={"children": batch},
            )

    def upload_document_image(
        self,
        parent_node: str,
        image_path: Path,
        *,
        drive_route_token: str = "",
    ) -> str:
        path = image_path.expanduser().resolve()
        if not path.is_file():
            raise FeishuAPIError(f"关键画面文件不存在：{path}")
        size = path.stat().st_size
        if size <= 0 or size > 20 * 1024 * 1024:
            raise FeishuAPIError(f"关键画面大小不适合上传：{path.name}")
        data = {
            "file_name": path.name[:250],
            "parent_type": "docx_image",
            "parent_node": parent_node,
            "size": str(size),
        }
        if drive_route_token:
            data["extra"] = json.dumps(
                {"drive_route_token": drive_route_token}, ensure_ascii=False
            )
        with path.open("rb") as source:
            response = self._http.post(
                f"{self.API_ROOT}/drive/v1/medias/upload_all",
                headers={"Authorization": f"Bearer {self._tenant_token()}"},
                data=data,
                files={
                    "file": (
                        path.name,
                        source,
                        mimetypes.guess_type(path.name)[0] or "image/jpeg",
                    )
                },
            )
        payload = response.json()
        if response.is_error or payload.get("code") != 0:
            raise FeishuAPIError(
                f"上传关键画面失败：{payload.get('msg') or response.status_code}"
            )
        token = str(payload.get("data", {}).get("file_token") or "")
        if not token:
            raise FeishuAPIError("上传关键画面成功响应中缺少 file_token")
        return token

    def append_document_image(
        self,
        document_token: str,
        timecode: str,
        image_path: Path,
    ) -> str:
        # Image.token is read-only during block creation. Create an empty image
        # block, upload the media to that block, then bind it with replace_image.
        payload = self._request(
            "POST",
            f"/docx/v1/documents/{document_token}/blocks/{document_token}/children?document_revision_id=-1",
            json_body={
                "children": [
                    paragraph(f"画面时间：{timecode}"),
                    {"block_type": 27, "image": {}},
                ]
            },
        )
        children = payload.get("data", {}).get("children") or []
        image_block = next(
            (item for item in children if item.get("block_type") == 27), None
        )
        block_id = str((image_block or {}).get("block_id") or "")
        if not block_id:
            raise FeishuAPIError("飞书创建图片块成功响应中缺少 block_id")
        token = self.upload_document_image(
            block_id,
            image_path,
            drive_route_token=document_token,
        )
        self._request(
            "PATCH",
            f"/docx/v1/documents/{document_token}/blocks/{block_id}?document_revision_id=-1",
            json_body={"replace_image": {"token": token}},
        )
        return block_id

    def create_base_record(self, fields: dict[str, Any]) -> str:
        payload = self._request(
            "POST",
            f"/bitable/v1/apps/{self.base_app_token}/tables/{self.base_table_id}/records",
            json_body={"fields": fields},
        )
        record = payload.get("data", {}).get("record", {})
        record_id = str(record.get("record_id") or "")
        if not record_id:
            raise FeishuAPIError("多维表格写入成功响应中缺少 record_id")
        return record_id

    def archive(self, video: DownloadedVideo, analysis: AnalysisArtifact) -> ArchiveResult:
        title = f"{video.author}｜{video.title}"[:200]
        document_token, node_token, document_url = self.create_wiki_document(title)
        blocks = build_document_blocks(video, analysis)
        key_frames = select_key_frames(analysis)
        self.append_document_blocks(document_token, blocks)
        if key_frames:
            self.append_document_blocks(document_token, [heading("关键画面", 2)])
            for timecode, frame_path in key_frames:
                try:
                    self.append_document_image(document_token, timecode, frame_path)
                except Exception as exc:
                    self.append_document_blocks(
                        document_token,
                        [paragraph(f"{timecode} 关键画面上传失败：{exc}")],
                    )
                    continue
        record_id = self.create_base_record(
            {
                "视频标题": video.title,
                "作者": video.author,
                "原链接": base_url_cell(video.source_url, "打开抖音原视频"),
                "摘要": analysis.summary,
                "分类": infer_category(analysis),
                "标签": keyword_terms(analysis)[:12],
                "时长": video.duration,
                "分析状态": "分析完成",
                # Base OpenAPI expects a millisecond timestamp for datetime fields.
                "分析时间": int(time.time() * 1000),
                "文档链接": base_url_cell(document_url, "打开分析文档"),
                "本地保存状态": "已保存到拾流资料库",
            }
        )
        return ArchiveResult(document_token, node_token, document_url, record_id)


def _elements(content: str, *, bold: bool = False, link: str = "") -> list[dict[str, Any]]:
    style: dict[str, Any] = {}
    if bold:
        style["bold"] = True
    if link:
        style["link"] = {"url": link}
    text_run: dict[str, Any] = {"content": content}
    if style:
        text_run["text_element_style"] = style
    return [{"text_run": text_run}]


def heading(content: str, level: int = 2) -> dict[str, Any]:
    block_type = 3 if level == 1 else 4
    key = "heading1" if level == 1 else "heading2"
    return {"block_type": block_type, key: {"elements": _elements(content)}}


def paragraph(content: str) -> dict[str, Any]:
    return {"block_type": 2, "text": {"elements": _elements(content)}}


def base_url_cell(url: str, text: str) -> dict[str, str]:
    """Format a Base text field configured with style.type=url."""
    return {"link": url, "text": text}


def _chunks(value: str, size: int = 1400) -> list[str]:
    text = value.strip()
    if not text:
        return []
    return [text[index : index + size] for index in range(0, len(text), size)]


def keyword_terms(analysis: AnalysisArtifact) -> list[str]:
    values: list[str] = []
    for item in analysis.keywords:
        term = str(item.get("term") or "").strip()
        if term and term not in values:
            values.append(term)
    return values


def infer_category(analysis: AnalysisArtifact) -> str:
    haystack = " ".join(
        [analysis.summary, analysis.answer, *keyword_terms(analysis)]
    ).lower()
    candidates = [
        ("AI 与工具", ("ai", "agent", "codex", "claude", "模型", "工具", "自动化")),
        ("商业与营销", ("营销", "品牌", "商业", "销售", "增长", "投放")),
        ("内容创作", ("拍摄", "剪辑", "脚本", "内容", "创作", "账号")),
        ("个人成长", ("学习", "成长", "习惯", "认知", "效率")),
    ]
    for category, markers in candidates:
        if any(marker in haystack for marker in markers):
            return category
    return "待分类"


def answer_sections(analysis: AnalysisArtifact) -> tuple[str, str, str]:
    """Extract the three required report sections from the model answer."""
    labels = ("核心观点", "操作步骤", "可复用启发")
    pattern = re.compile(
        r"(?:^|\n)\s*(?:#{1,3}\s*)?(核心观点|操作步骤|可复用启发)\s*[:：]\s*"
    )
    matches = list(pattern.finditer(analysis.answer))
    values: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(analysis.answer)
        values[match.group(1)] = analysis.answer[match.end() : end].strip()
    # 三段必须是「不同」的内容。模型没有按标记切分时（常见于只填了 summary、
    # 三段字段留空），绝不能把同一段摘要塞进三栏——那会让文档出现一模一样的三段。
    # 此时只在「核心观点」放一次整体分析，其余两栏给诚实的指引占位。
    summary = analysis.summary.strip()
    whole = analysis.answer.strip() or summary or "暂无内容"
    pointer = "（本段模型未单独提炼，参见上方“核心观点”与“一句话摘要”）"

    core = values.get(labels[0]) or summary or whole
    steps = values.get(labels[1]) or pointer
    insights = values.get(labels[2]) or pointer
    # 若三段被回填成同一段，把重复项降级为指引占位
    if steps == core:
        steps = pointer
    if insights in (core, steps):
        insights = pointer
    return (core, steps, insights)


def _seconds(timecode: str) -> float | None:
    try:
        parts = [float(part) for part in timecode.split(":")]
    except ValueError:
        return None
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0] if len(parts) == 1 else None


def select_key_frames(analysis: AnalysisArtifact, limit: int = 6) -> list[tuple[str, Path]]:
    manifest_path = analysis.session_dir / "manifest.json"
    if not manifest_path.is_file():
        return []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    frames: list[tuple[float, str, Path]] = []
    for item in manifest.get("frames") or []:
        raw_path = Path(str(item.get("path") or "")).expanduser()
        path = raw_path if raw_path.is_file() else analysis.session_dir / "frames" / raw_path.name
        if path.is_file():
            frames.append(
                (
                    float(item.get("timestamp") or 0),
                    str(item.get("timecode") or ""),
                    path.resolve(),
                )
            )
    if not frames:
        return []

    selected: list[tuple[float, str, Path]] = []
    targets = [
        value
        for value in (_seconds(str(item.get("timecode") or "")) for item in analysis.timeline)
        if value is not None
    ]
    for target in targets:
        candidate = min(frames, key=lambda item: abs(item[0] - target))
        if candidate not in selected:
            selected.append(candidate)
        if len(selected) >= limit:
            break
    if len(selected) < min(limit, len(frames)):
        slots = min(limit, len(frames))
        for index in range(slots):
            position = round(index * (len(frames) - 1) / max(1, slots - 1))
            candidate = frames[position]
            if candidate not in selected:
                selected.append(candidate)
            if len(selected) >= limit:
                break
    selected.sort(key=lambda item: item[0])
    return [(timecode, path) for _, timecode, path in selected[:limit]]


def build_document_blocks(video: DownloadedVideo, analysis: AnalysisArtifact) -> list[dict[str, Any]]:
    core_points, steps, reusable_insights = answer_sections(analysis)
    blocks = [
        heading("视频信息", 2),
        paragraph(f"标题：{video.title}"),
        paragraph(f"作者：{video.author}"),
        paragraph(f"时长：{video.duration} 秒"),
        paragraph(f"原始抖音链接：{video.source_url}"),
        heading("一句话摘要", 2),
        paragraph(analysis.summary or "暂无摘要"),
        heading("核心观点", 2),
    ]
    blocks.extend(paragraph(chunk) for chunk in _chunks(core_points))
    blocks.append(heading("操作步骤", 2))
    blocks.extend(paragraph(chunk) for chunk in _chunks(steps))
    blocks.append(heading("可复用启发", 2))
    blocks.extend(paragraph(chunk) for chunk in _chunks(reusable_insights))
    blocks.append(heading("时间线", 2))
    for item in analysis.timeline:
        blocks.append(
            paragraph(
                f"• {item.get('timecode', '')} {item.get('event', '')}"
                f"（{item.get('evidence', '')}）"
            )
        )
    blocks.append(heading("关键词", 2))
    for item in analysis.keywords:
        blocks.append(
            paragraph(
                f"• {item.get('term', '')}：{item.get('context', '')}"
                f"（{item.get('timecode', '')}）"
            )
        )
    blocks.append(heading("完整语音转写", 2))
    transcript_chunks = _chunks(analysis.transcript)
    blocks.extend(paragraph(chunk) for chunk in (transcript_chunks or ["本次分析没有可用的语音转写。"]))
    blocks.extend(
        [
            heading("归档信息", 2),
            paragraph(f"本地视频：{video.video_path}"),
            paragraph(f"分析报告：{analysis.report_path}"),
        ]
    )
    return blocks


def start_websocket(app_id: str, app_secret: str, callback: Callable[[IncomingMessage], None]) -> None:
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

    def handle(event: P2ImMessageReceiveV1) -> None:
        try:
            message = event.event.message
            sender = event.event.sender
            if message.message_type != "text":
                return
            content = json.loads(message.content or "{}")
            callback(
                IncomingMessage(
                    message_id=str(message.message_id or ""),
                    chat_id=str(message.chat_id or ""),
                    sender_open_id=str(sender.sender_id.open_id or ""),
                    text=str(content.get("text") or ""),
                )
            )
        except Exception as exc:
            # Event handlers must return quickly and must not raise, otherwise
            # Feishu retries the event and may create duplicate work.
            print(f"处理飞书消息事件失败：{exc}", flush=True)

    handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(handle)
        .build()
    )
    client = lark.ws.Client(
        app_id,
        app_secret,
        event_handler=handler,
        # INFO includes the WebSocket URL and ephemeral connection parameters.
        # Keep persistent launchd logs free of those credentials.
        log_level=lark.LogLevel.ERROR,
    )
    client.start()
