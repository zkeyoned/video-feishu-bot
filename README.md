# 飞书视频分析助手

> **仅供个人学习与自用。** 本项目不绕过登录、付费墙、DRM、验证码或任何访问控制，
> 也不移除画面中已有的水印。请只处理你本人创作、已获授权，或依法可以保存的内容，
> 并遵守来源站点的服务条款。使用者对自己的使用行为负责。


独立的飞书 Bot 接入层。它不会启动或操作拾流网页，而是直接复用：

- `../codex-zero/server.py`：抖音公开链接解析、H.264 视频下载和本地资料库。
- `../video-agent`：本地 Whisper 转写、智能抽帧、视觉分析和报告生成。

处理完成后，Bot 会在“视频研究知识库”创建飞书文档，在“视频索引”多维表格增加记录，并把摘要和文档链接回复到原消息。

## 数据流

```text
飞书消息 → 拾流下载引擎 → 本地视频 → video-agent → 飞书知识库文档 → 多维表格索引
```

原始视频默认只保留在拾流本地资料库，不上传飞书。

## 下载器（可替换 / 按站点自动选）

分析流程只依赖 `pipeline.Downloader` 协议——一个 `download(source_url) -> DownloadedVideo`
方法，因此下载这一层可以整体替换。

| 配置值 | 行为 |
| --- | --- |
| `auto`（默认） | 抖音链接交给拾流，其余站点交给 yt-dlp；拾流不存在时全部走 yt-dlp |
| `ytdlp` | 一律用 [yt-dlp](https://github.com/yt-dlp/yt-dlp)，支持上千个站点 |
| `shiliu` | 一律用拾流私有下载引擎（未随本仓库发行） |

之所以留出可替换的下载层：不同站点适合的获取方式不同。公开发行版默认统一走
yt-dlp（配合浏览器 Cookie，见下方说明）；私有引擎未随本仓库发行，缺席时自动
落到 yt-dlp，功能完整可用。

```bash
VIDEO_BOT_DOWNLOADER=auto
VIDEO_BOT_DOWNLOAD_DIR=            # 留空则用 <项目>/downloads
VIDEO_BOT_YTDLP_FORMAT=            # 留空则封顶 1080p（分析用不到 4K）
VIDEO_BOT_YTDLP_COOKIES_FROM_BROWSER=   # 见下方说明
```

使用 yt-dlp 前先安装：`brew install yt-dlp`（或 `pip install yt-dlp`）。

### 需要 Cookie 的站点

部分站点（抖音是其中之一）会要求请求带上浏览器 Cookie，否则 yt-dlp 会报
`Fresh cookies (not necessarily logged in) are needed`。此时可以指定从哪个浏览器读取：

```bash
VIDEO_BOT_YTDLP_COOKIES_FROM_BROWSER=chrome   # 或 safari / firefox / edge
```

留空表示完全不读取浏览器数据，这也是默认值。开启前请自行确认这台机器上的
Cookie 可以被本程序读取。

## 本地准备

```bash
cp .env.example .env
uv sync
uv run pytest -q
```

`.env` 中的飞书凭证和资源 ID 需要在创建“视频分析助手”应用、知识库和多维表格后填写。真实密钥不得提交到 Git。

### 给应用授予知识库权限（必做，否则归档会失败）

Bot 要往你的知识库写文档，光有 App ID/Secret 不够——**还必须把这个飞书应用加为目标知识库的「可编辑」成员**。漏了这步，下载/转写/分析都会正常跑，但最后一步会报：

```
permission denied: node permission denied, tenant needs edit permission
```

做法：打开目标知识库 → 设置/成员管理 → 添加成员 → 搜索你的应用名 → 权限选「可编辑」。多维表格同理，把应用加为可编辑协作者。

## 启动

```bash
uv run video-feishu-bot
```

Bot 使用飞书官方 Python SDK 建立 WebSocket 长连接，不要求公网回调域名。消息事件回调只做持久化和入队，视频处理在单独工作线程执行。

## macOS 开机自动运行

项目自带 `launchd/com.kongke.video-feishu-bot.plist`。安装到当前用户的
`~/Library/LaunchAgents` 后，Bot 会由已授权的 Python 直接启动，并在意外退出后自动重启。
部署运行日志分别保存在
`~/Library/Application Support/VideoFeishuBot/logs/bot.log` 和
`~/Library/Application Support/VideoFeishuBot/logs/bot-error.log`。

```bash
launchctl print gui/$(id -u)/com.kongke.video-feishu-bot
```

## 去重与恢复

- 同一个飞书 `message_id` 只入队一次，防止事件重推造成重复分析。
- 同一个抖音 `content_id` 已归档时，直接返回原有飞书文档。
- 队列状态保存在 `data/video-bot.db`；进程重新启动后会恢复未完成任务。

## 飞书多维表格字段

运行前需要存在以下字段，字段名必须完全一致：

- 视频标题（文本）
- 作者（文本）
- 原链接（文本或超链接）
- 摘要（文本）
- 分类（文本）
- 标签（文本）
- 时长（数字）
- 分析状态（文本）
- 分析时间（日期）
- 文档链接（文本或超链接）
- 本地保存状态（文本）

## 安全边界

- 只接受拾流支持的公开抖音链接。
- 不把 App Secret、模型 Key 或访问令牌写入日志和数据库。
- 默认依赖飞书应用的可用范围控制访问；如需应用内白名单，必须填写该应用事件返回的 OpenID，不能复用其他飞书应用的 OpenID。
- 不经过拾流主人密码、Web UI 或 Cloudflare Tunnel。
- 不删除原项目、历史报告或本地视频。

## 使用边界与免责声明

- 本项目是**个人自动化工具框架**，不是任何视频平台的官方客户端，也与飞书官方无关。
- 仅用于处理**你有权处理的内容**（自己的作品、获授权的素材、平台条款允许的个人学习用途）。
- 本项目**不提供**绕过付费、绕过版权保护或规避访问控制的能力；请遵守各平台的用户协议与当地法律。
- 使用本项目产生的一切后果由使用者自行承担。

## 隐私

- App Secret、模型 Key、Cookie 等敏感信息只存在于你本机的 `.env` 与系统钥匙串，不会提交进仓库，也不写入日志。
- 下载的视频与转写产物默认只保存在本机，由你自己的飞书应用归档到你自己的租户。

## License

GPL-3.0 —— 详见 [LICENSE](LICENSE)。衍生作品需以相同协议开源。
