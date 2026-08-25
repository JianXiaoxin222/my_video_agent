# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# video_agent — 一句话 → 单镜头脚本 → 参考图 → 视频

将「一句话创意 / 单个镜头提示词」流水线化为短视频。两套入口并存：

1. **手动三步 CLI**（`script-writer` skill → `agents.image` → `agents.video`）：每步独立、可单跑、可复跑。
2. **Video Agent Studio**（`studio/` 后端 + `studio-ui/` 前端）：把脚本、图片、视频节点编排为可保存的 DAG 工作流，带安全预览与确认执行。

## 数据流（手动三步 CLI）

```
一句话 / 单个镜头提示词
   │  ① script-writer skill（Claude 写文件，不调 API）
   ▼
instances_prompt.yaml + script.yaml + script.md
   │  ② agents.image（火山方舟 Seedream 5.0 Pro）
   ▼
character_images/<名>.jpg + character_images/urls.json
   │  ③ agents.video.generate（火山方舟 Seedance 2.0，逐镜头手动）
   ▼
raw_videos/<shot>.mp4
```

## 目录结构

```
agents/
├── common/        # PROJECT_ROOT、config_loader（${VAR} 替换）、ark_auth（API key 解析）
├── image/         # 图片：generator.py（CLI）、seedream_client.py
├── video/         # 视频：generate.py（单视频 CLI + build_content_blocks）、seedance_client.py
├── editor/        # 计划：剪辑合成 → final/
└── publisher/     # 计划：多平台发布
studio/            # Studio 后端（FastAPI）：api/compiler/executor/validation/models/repository/storage/contracts/audit
studio-ui/         # Studio 前端（React + @xyflow/react + Vite + TS）
tests/             # test_studio.py（unittest，用假 client 不调 API）
run_studio.py      # uvicorn 启动 Studio 后端
_speedup_video.py  # 用 imageio-ffmpeg 给视频加速的小工具
.claude/skills/    # script-writer / character-image-prompt / sd2-pe / seedance-video（.agents/skills/ 为同内容副本）
config/            # secrets.yaml（git-ignored）、seedance.yaml、seedream.yaml
references/        # seedream_5_0_tutorial（供 character-image-prompt skill 参考）
output/            # projects/<标题>/ 产物 + .studio/studio.db（工作流/运行记录）
logs/              # seedance/seedream 请求与结果 JSONL + studio_runs.jsonl
```

## 环境与配置

- Python 3.12，统一 `.venv`。搭建：
  - Windows：`scripts\init_dev_env\setup_windows.bat`（uv 方式，会自动下载 uv）
  - 兜底：`python -m venv .venv && .venv\Scripts\python -m pip install -r requirements.txt`
- API key 放 `config/secrets.yaml`（git-ignored，**切勿提交或打印**）：
  - `ark.api_key` — 火山方舟（Seedance 视频）
  - `seedream.api_key` — 火山方舟（Seedream 图片，独立 key 便于分账统计）
  - 从 `config/secrets.yaml.example` 复制后填写。

**API key 解析优先级**（两处一致）：显式构造参数 → 环境变量 → `config/secrets.yaml`。

- Seedance：构造参数 → `ARK_API_KEY` → `secrets.yaml` 的 `ark.api_key`（或 `seedance.api_key`）。
- Seedream：构造参数 → `SEEDREAM_API_KEY` → `secrets.yaml` 的 `seedream.api_key`（不回退到视频 key）。

`agents/common/config_loader.py` 的 `load_config()` 会把 YAML 值里的 `${VAR}` / `${VAR:default}` 解析为环境变量（相对项目根定位路径）。

### 对象存储（Studio 上传本地素材）

Seedance 只接受公网 http(s) URL；Seedream 图片支持 `data:image/...;base64` 内联。Studio 通过 `studio/storage.py` 的 `StorageProvider` 解析本地素材：

- 未配置对象存储 → `UrlProvider`：公网 URL 直通，本地文件上传报错；图片内联为 data URL。
- 配置 S3 兼容存储（如 OSS）→ `S3CompatibleProvider`（惰性 import boto3）。通过环境变量开启：
  `VIDEO_AGENT_S3_ENDPOINT`、`VIDEO_AGENT_S3_BUCKET`、`VIDEO_AGENT_S3_PUBLIC_BASE_URL`（可选 `VIDEO_AGENT_S3_REGION`）。

## 常用命令

### 手动三步 CLI

```powershell
# ① 脚本：用 /script-writer skill（纯提示词，Claude 写文件，不调 API）
#    产物：output/projects/<标题>/instances_prompt.yaml + script.yaml + script.md

# ② 图片：读 instances_prompt.yaml，为每个实体生成参考图 + urls.json
.venv\Scripts\python.exe -m agents.image.generator --project-dir "output\projects\<标题>"

# ③ 视频：逐镜头手动生成（--image-urls 传实体参考图公网 URL，@图片N 按顺序对应）
.venv\Scripts\python.exe -m agents.video.generate --prompt "..." --image-urls "..." --ratio 16:9 --duration 5

# 无成本查看视频 payload（支持 text_to_video / image_to_video / video_to_video / first_last_frame_to_video）
.venv\Scripts\python.exe -m agents.video.generate --prompt "..." --mode text_to_video --dry-run
```

可选提示词优化 skill：`/character-image-prompt`（英文定妆照提示词）、`/sd2-pe`（Seedance 提示词优化）、`/seedance-video`（第 3 步手册）。

### Video Agent Studio（节点式界面）

```powershell
# 后端（FastAPI + SSE，127.0.0.1:8000）
.venv\Scripts\python.exe run_studio.py

# 前端（另开终端，127.0.0.1:5173）
cd studio-ui
npm install
npm run dev        # build: npm run build（tsc --noEmit && vite build）
```

工作流与运行记录持久化在 `output/.studio/studio.db`（SQLite）。预览（`/api/.../preview`）不调 API；执行（`/api/.../runs`）需先拿到 preview 返回的 `confirmation_token` 并回传 `confirmed: true`，否则 409 拒绝，确保不会误烧费用。

### 测试

```powershell
# 全部（unittest，用假 image/video client + FastAPI TestClient，不调真实 API）
.venv\Scripts\python.exe -m unittest tests.test_studio -v
```

## 架构要点

### 手动流水线契约

- **`instances_prompt.yaml`** 是图片 agent 的输入契约：`instances[]` 每项有 `id`/`name`/`appearance`（可含 `motion`），图片 agent 用 `appearance` 作提示词。
- **`script.yaml`** 顶层 `script:` 包裹 `title`/`overall_setting`/`instances[]`/`shots[]`；每个 `shot` 有 `description` 和引用实体 id 的 `entities`。
- **`character_images/urls.json`** 回传 `{实体名: 公网URL}`；`file://` 本地路径会被 Seedance 拒绝，图片请求若用 `b64_json` 不会产生可复用公网 URL。
- 视频提示词里的 `@图片1`、`@视频1` 索引对应 `build_content_blocks()` 生成的 content 数组中、文本块之后的非文本块顺序。

### `build_content_blocks()` 是 CLI 与 Studio 共享的提示词拼装函数

`agents/video/generate.py:build_content_blocks(prompt, image_urls, video_url, audio_url, first_frame_url, last_frame_url)` 把参数按「文本 → 首尾帧 → 普通图 → 视频 → 音频」顺序拼成 Seedance content 数组。CLI 与 Studio 的 compiler/executor 都复用它，改内容结构时须同步两处。

### Studio 工作流 = DAG

- 节点类型（`studio/models.py` 的 `NODE_TYPES`）：`text_input` / `image_input` / `video_input` / `image_generate` / `video_generate` / `script_project` / `output`；边组成有向图，`validation.py` 校验端口类型、唯一 id、无环（拓扑排序）。
- **生成模式由连线推导**：`models.py:infer_generation_mode()` 以「上游媒体节点类型 + handle」为准（`image_generate` 上游是 image→`image_to_image`；`video_generate` 看 first/last frame、video、image 等），节点 data 里的显式 mode 字段仅作无连线时的回退。
- **预览 vs 执行**：`compiler.py:preview_workflow()` 不调 API，产出各生成节点的 payload 与估算成本（按 duration 秒数累加）；`executor.py:WorkflowExecutor` 在后台线程真正跑，逐节点 emit 事件，经 SSE（`/api/runs/{run_id}/events`）推给前端，结果持久化到 runs 表。
- **单节点运行**（`/api/.../nodes/{id}/generate`）会自动把该节点的所有上游祖先加入执行集，保证连线的 prompt/素材可用。

### SeedanceClient / SeedreamClient 记录所有请求与结果

- **Seedance**：`create_task()` 追加完整请求 payload（model / ratio / duration / content）到 `logs/seedance_requests.jsonl`；`poll_task()` 成功后追加 `task_id` + 公网 `video_url` 到 `logs/seedance_results.jsonl`。传 `request_log_path=None` / `result_log_path=None` 可关闭。
- **Seedream**：请求记 `logs/seedream_requests.jsonl`，结果（公网 `image_url` + 本地路径）记 `logs/seedream_results.jsonl`；`generate_image_url()` 返回 `(本地路径, 公网URL)`，`generate()` 委托它并丢弃 URL。
- Studio 生命周期事件（`run_requested`/`run_rejected`/`run_status`/`client_error`）由 `studio/audit.py` 追加到 `logs/studio_runs.jsonl`。

## Agent 路线图

| Agent | 状态 | 说明 |
|-------|------|------|
| script | ✅ 可用 | `script-writer` skill：一句话 → 单镜头脚本（实体 + 分镜） |
| image | ✅ 可用 | Seedream 5.0 Pro 生实体参考图 → `character_images/` |
| video | ✅ 可用 | Seedance 2.0 逐镜头视频 → `raw_videos/` |
| studio | ✅ 可用 | 节点式 DAG 工作流（`studio/` + `studio-ui/`） |
| editor | 📋 计划 | 多段视频剪辑合成（FFmpeg/字幕/配乐）→ `final/` |
| publisher | 📋 计划 | 多平台自动发布 |

## 约定

- 用 `agents.common.PROJECT_ROOT` 定位项目根，不要各自 `Path(__file__).resolve().parent.parent...`（部分 CLI 模块会额外 `sys.path.insert` 项目根以支持 `python -m` 与直接 `python file.py` 两种运行方式，属正常）。
- 脚本产出到 `output/projects/<标题>/`，图片到 `output/projects/<标题>/character_images/`，视频到 `output/projects/<标题>/raw_videos/`。
- 真实 API key 绝不提交；`config/secrets.yaml` 已 git-ignored。
- 改动后建议先跑 `python -m unittest tests.test_studio -v`（不调 API）与相关 CLI 的 `--help`/`--dry-run` 验证；只有明确需要时才实际调用 Seedream/Seedance，避免烧 API 费用。

## 成本参考

- 视频生成（Seedance 2.0 mini 模型）约 ¥1/秒视频。
