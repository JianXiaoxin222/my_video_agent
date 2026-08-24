---
name: seedance-video
description: >-
  手动三步流水线的第 3 步：用 agents.video.generate 单视频 CLI，为 script-writer
  skill 产出的每个镜头（shot）逐一生成 Seedance 2.0 视频。读 config/secrets.yaml
  的 ark.api_key，记录请求到 logs/seedance_requests.jsonl、结果到
  logs/seedance_results.jsonl。
---

# Seedance 2.0 Video Generation（第 3 步）

从「单镜头脚本」逐镜头生成 Seedance 2.0 视频。**手动执行**，无自动化流水线——
每个镜头显式调用一次 `agents.video.generate`，用 `--prompt` 传提示词、`--image-urls`
传实体参考图。

## 前置条件

- **Ark API key**：`config/secrets.yaml` 的 `ark.api_key`
- **统一 `.venv`**（Python 3.12）：`volcenginesdkarkruntime`、`httpx`、`yaml`

## 三步流程定位

1. `/script-writer` skill → `instances_prompt.yaml` + `script.yaml`（`shots[]`）+ `script.md`
2. `python -m agents.image.generator --project-dir "output\projects\<标题>"` → `character_images/` + `urls.json`
3. 本步骤：逐镜头 `python -m agents.video.generate` → `raw_videos/`

## 逐镜头生成

对 `script.yaml` 的每个 `shot`：

1. 取 `shot.description` 作为基础提示词（中文可直接用；可选 `/sd2-pe` 润色并加 `@图片N` 引用）。
2. 由 `shot.entities`（`主体N`）→ 经 `instances[]` 查 `name` → 经 `character_images/urls.json` 查公网 URL。
3. 按实体顺序把这些 URL 传给 `--image-urls`（`@图片1` = 第一个 `--image-urls`，以此类推）。

```powershell
.venv\Scripts\python.exe -m agents.video.generate `
    --prompt "<shot.description，可含 @图片1/@图片2 引用>" `
    --image-urls "<实体1 公网URL>" --image-urls "<实体2 公网URL>" `
    --ratio 16:9 --duration 5 `
    --output-dir "output\projects\<标题>\raw_videos" --output-name shot_01
```

## 参数

| 参数 | 说明 |
|------|------|
| `--prompt` / `-p` | 必填，文本提示词 |
| `--image-urls` | 参考图公网 URL，可重复（`@图片N` 按顺序对应） |
| `--video-url` | 参考视频公网 URL（视频延长/编辑） |
| `--audio-url` | 参考音频公网 URL |
| `--model` / `-m` | 模型 ID 覆盖 |
| `--pro` | 用 pro 模型（`doubao-seedance-2-0-260128`） |
| `--ratio` / `-r` | `16:9` / `9:16` / `1:1` |
| `--duration` / `-d` | 时长（秒，int） |
| `--watermark` | 加「AI 生成」水印 |
| `--no-audio` | 关闭音频 |
| `--poll-interval` / `--timeout` | 轮询间隔 / 超时 |
| `--output-dir` / `-o` | 输出目录（默认 `download`） |
| `--output-name` | 输出文件名（否则时间戳命名） |
| `--config` / `-c` | 默认 `config/seedance.yaml` |
| `--api-key` | Ark key 覆盖 |
| `--verbose` / `-v` | 详细日志 |

## 模型

| 模型 ID | 说明 | 最高分辨率 |
|---------|------|-----------|
| `doubao-seedance-2-0-mini-260615` | 默认（`seedance.models.default`），快、省 | 720p |
| `doubao-seedance-2-0-260128` | pro（`--pro`），更精细 | 1080p |

## 画幅

`--ratio` 直接指定（不再按平台自动映射）：

| ratio | 场景 |
|-------|------|
| `9:16` | 竖屏（抖音/快手/小红书） |
| `16:9` | 横屏（B 站） |
| `1:1` | 方形 |

## 请求 / 结果记录

- 每次生成请求的完整 payload 追加到 `logs/seedance_requests.jsonl`。
- 每次成功后的 `task_id` + 公网 `video_url` 追加到 `logs/seedance_results.jsonl`。

## 输出结构

```
output/projects/<标题>/
├── instances_prompt.yaml   ← 实体清单（script-writer skill 产出，图片 agent 输入）
├── script.yaml             ← title / overall_setting / instances[] / shots[]
├── script.md               ← 人读版
├── character_images/       ← 实体参考图 + urls.json（图片 agent 产出）
├── raw_videos/             ← 本步骤产出（shot_01.mp4 等）
└── final/                  ← （占位）未来剪辑 agent 成品
```

## 关键文件

| 文件 | 作用 |
|------|------|
| `agents/video/seedance_client.py` | `SeedanceClient`（create_task / poll / download；含请求记录） |
| `agents/video/generate.py` | 单视频 CLI（本步骤入口） |
| `agents/image/generator.py` | 实体参考图生成（读 instances_prompt.yaml） |
| `config/seedance.yaml` | 模型 ID / 默认参数 |

## 注意

- 参考图/视频/音频必须是**公网可访问 URL**（`file://` 本地路径会被 API 拒绝）；图片
  agent 写的 `urls.json` 即公网 URL。
- 视频约 ¥1/秒，逐镜头手动跑，先在第一个镜头验证链路再批量。
