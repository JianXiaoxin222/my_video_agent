# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# video_agent — 一句话 → 单镜头脚本 → 参考图 → 视频

将「一句话创意 / 单个镜头提示词」手动三步流水线化为短视频。**无自动化编排**，
每一步独立、可单跑、可复跑。

三步流程：
1. **脚本**（`script-writer` skill，纯提示词，Claude 写文件，不调 API）：一句话 → 实体分析 + 镜头分镜。
2. **图片**（`agents/image`，Seedream 5.0 Pro）：读 `instances_prompt.yaml`，为每个实体生成参考图。
3. **视频**（`agents/video`，Seedance 2.0）：逐镜头用 `generate.py` 生成视频。

## 数据流

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
├── video/         # 视频：generate.py（单视频 CLI）、seedance_client.py
├── editor/        # 计划：剪辑合成 → final/
└── publisher/     # 计划：多平台发布
.claude/skills/    # script-writer / character-image-prompt / sd2-pe / seedance-video
config/            # secrets.yaml（git-ignored）、seedance.yaml、seedream.yaml
references/        # seedream_5_0_tutorial（供 character-image-prompt skill 参考）
output/projects/<标题>/  # 统一输出
logs/              # seedance_requests.jsonl / seedance_results.jsonl、seedream_requests.jsonl / seedream_results.jsonl
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

## 常用命令（三步手动流程）

```powershell
# ① 脚本：用 /script-writer skill（纯提示词，Claude 写文件，不调 API）
#    产物：output/projects/<标题>/instances_prompt.yaml + script.yaml + script.md

# ② 图片：读 instances_prompt.yaml，为每个实体生成参考图 + urls.json
.venv\Scripts\python.exe -m agents.image.generator --project-dir "output\projects\<标题>"

# ③ 视频：逐镜头手动生成（--image-urls 传实体参考图公网 URL，@图片N 按顺序对应）
.venv\Scripts\python.exe -m agents.video.generate --prompt "..." --image-urls "..." --ratio 16:9 --duration 5
```

可选提示词优化 skill：`/character-image-prompt`（英文定妆照提示词）、`/sd2-pe`（Seedance 提示词优化）。

## 架构要点

### `instances_prompt.yaml` 是图片 agent 的输入契约

`script-writer` skill 写出 `instances_prompt.yaml`（`instances[]`：每个实体的 `id`/`name`/`appearance`/`motion`）与 `script.yaml`（`script:` 包裹的 `title`/`overall_setting`/`instances[]`/`shots[]`）。图片 agent 读 `instances_prompt.yaml`，用每个实体的 `appearance` 作为 Seedream 提示词。

### `shots[]` 是视频生成的输入契约

`script.yaml` 的每个 `shot` 有 `description`（画面内容）和 `entities`（引用 `instances[].id`）。视频生成时手动取 `shot.description` 作提示词，把该镜头 `entities` 对应实体的参考图公网 URL（来自 `character_images/urls.json`）按顺序传给 `--image-urls`。

### 实体参考图按 `urls.json` 回传公网 URL

图片 agent 生成参考图后，把 `{实体名: 公网URL}` 写入 `character_images/urls.json`，视频生成步骤直接取用（`file://` 本地路径会被 Seedance 拒绝）。

### SeedanceClient / SeedreamClient 记录所有请求与结果

- **Seedance**：`SeedanceClient.create_task()` 追加完整请求 payload（model / ratio / duration / content）到 `logs/seedance_requests.jsonl`；`poll_task()` 成功后追加 `task_id` + 公网 `video_url` 到 `logs/seedance_results.jsonl`。传 `request_log_path=None` / `result_log_path=None` 可关闭。
- **Seedream**：请求记 `logs/seedream_requests.jsonl`，结果（公网 `image_url` + 本地路径）记 `logs/seedream_results.jsonl`；`generate_image_url()` 返回 `(本地路径, 公网URL)`，`generate()` 委托它并丢弃 URL。

## Agent 路线图

| Agent | 状态 | 说明 |
|-------|------|------|
| script | ✅ 可用 | `script-writer` skill：一句话 → 单镜头脚本（实体 + 分镜） |
| image | ✅ 可用 | Seedream 5.0 Pro 生实体参考图 → `character_images/` |
| video | ✅ 可用 | Seedance 2.0 逐镜头视频 → `raw_videos/` |
| editor | 📋 计划 | 多段视频剪辑合成（FFmpeg/字幕/配乐）→ `final/` |
| publisher | 📋 计划 | 多平台自动发布 |

## 约定

- 用 `agents.common.PROJECT_ROOT` 定位项目根，不要各自 `Path(__file__).resolve().parent.parent...`（部分 CLI 模块会额外 `sys.path.insert` 项目根以支持 `python -m` 与直接 `python file.py` 两种运行方式，属正常）。
- 脚本产出到 `output/projects/<标题>/`，图片到 `output/projects/<标题>/character_images/`，视频到 `output/projects/<标题>/raw_videos/`。
- 真实 API key 绝不提交；`config/secrets.yaml` 已 git-ignored。
- 无测试套件；改动后建议先跑 `--help` 或对已有样例项目 `--skip-existing` 验证，避免烧 API 费用。

## 成本参考

- 视频生成（Seedance 2.0 mini 模型）约 ¥1/秒视频。
