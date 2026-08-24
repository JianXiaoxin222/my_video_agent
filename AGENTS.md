# AGENTS.md

本文件是 Codex 在 `video_agent` 仓库中工作时的项目约定。

## 项目目标

本项目把「一句话创意 / 单个镜头提示词」拆成三个独立、可单跑、可复跑的步骤：

1. `script-writer` skill：只写提示词和脚本文件，不调用 API。
2. `agents.image`：用 Seedream 5.0 Pro 为脚本中的实体生成参考图。
3. `agents.video`：用 Seedance 2.0 按镜头逐个生成视频。

当前没有自动编排器；剪辑与发布 agent 仍是占位目录。

## 数据流与文件契约

```
一句话 / 单镜头提示词
   │ script-writer
   ▼
output/projects/<标题>/
├── instances_prompt.yaml
├── script.yaml
└── script.md
   │ agents.image
   ▼
character_images/<实体>.(jpg|png) + character_images/urls.json
   │ agents.video（逐镜头手动调用）
   ▼
raw_videos/<shot>.mp4
```

- `instances_prompt.yaml` 是图片步骤的输入契约，顶层为 `instances[]`；每项至少有 `id`、`name`、`appearance`，可包含 `motion`。图片 agent 使用 `appearance` 作为提示词。
- `script.yaml` 顶层为 `script:`，包含 `title`、`overall_setting`、`instances[]`、`shots[]`。每个 shot 至少有 `description` 和引用实体 id 的 `entities`。
- `character_images/urls.json` 的键是实体 `name`，值必须是 Seedance 可访问的公网 URL。Seedance 不接受 `file://` 本地路径；若图片请求使用 `b64_json`，不会产生可复用公网 URL。
- 视频提示词中的 `@图片1`、`@视频1` 等索引对应 `agents.video.generate` 生成的 content 数组中、文本块之后的非文本块顺序。传参时保持实体在 `shot.entities` 中的顺序。

## 目录结构

```
agents/
├── common/       # PROJECT_ROOT、配置加载、Ark API key 解析
├── image/        # generator.py、seedream_client.py
├── video/        # generate.py、seedance_client.py
├── editor/       # 计划中的 FFmpeg/字幕/配乐合成
└── publisher/    # 计划中的多平台发布
.agents/skills/   # 项目 skills：script-writer、character-image-prompt、sd2-pe、seedance-video
.claude/skills/   # Claude Code 兼容的 skill 副本（如存在）
config/           # seedance.yaml、seedream.yaml、secrets.yaml（git-ignored）
references/       # Seedream 教程等提示词参考资料
output/projects/  # 项目产物
logs/             # API 请求与结果 JSONL 审计日志
```

## 环境与密钥

- Python 3.12，统一使用仓库根目录的 `.venv`。
- Windows 推荐运行 `scripts\init_dev_env\setup_windows.bat`；兜底方式为：

  ```powershell
  python -m venv .venv
  .venv\Scripts\python -m pip install -r requirements.txt
  ```

- 从 `config/secrets.yaml.example` 复制出 `config/secrets.yaml` 并填写密钥。真实密钥绝不提交、绝不打印。
- Seedance（视频）密钥解析顺序：显式构造参数 → `ARK_API_KEY` → `secrets.yaml` 的 `ark.api_key`（兼容 `seedance.api_key`）。
- Seedream（图片）密钥解析顺序：显式构造参数 → `SEEDREAM_API_KEY` → `secrets.yaml` 的 `seedream.api_key`；不会回退到视频密钥。
- `agents.common.config_loader.load_config()` 支持递归解析 `${VAR}` 与 `${VAR:default}`，相对路径以项目根为基准。

## 常用命令

### Video Agent Studio（节点式界面）

```powershell
# 后端（FastAPI + SSE，默认 127.0.0.1:8000）
.venv\Scripts\python.exe run_studio.py

# 前端（另开终端，默认 127.0.0.1:5173）
cd studio-ui
npm install
npm run dev
```

界面保存的工作流与运行记录位于 `output/.studio/studio.db`。预览不会调用 API；点击确认运行后才会产生 Seedream/Seedance 费用。

脚本步骤由 `script-writer` skill 完成，产物应写入 `output/projects/<标题>/`。

```powershell
# 图片：从 instances_prompt.yaml 批量生成实体参考图
.venv\Scripts\python.exe -m agents.image.generator `
  --project-dir "output\projects\<标题>" --skip-existing

# 图片：单提示词模式（可选 --reference-image、--size、--output-format、--watermark）
.venv\Scripts\python.exe -m agents.image.generator `
  --prompt "..." --name "实体名" --output-dir "download"

# 视频：文本转视频
.venv\Scripts\python.exe -m agents.video.generate `
  --prompt "..." --ratio 16:9 --duration 5 --output-dir "download"

# 视频：图片参考（多张图重复 --image-urls；也支持 --video-url / --audio-url）
.venv\Scripts\python.exe -m agents.video.generate `
  --prompt "..." --image-urls "https://.../entity.jpg" `
  --ratio 16:9 --duration 5 --output-dir "output\projects\<标题>\raw_videos" `
  --output-name "shot_01.mp4"
```

视频 CLI 还支持 `--pro`、`--no-audio`、`--watermark`、`--poll-interval`、`--timeout`、`--config`、`--api-key` 和 `--verbose`。图片 CLI 支持 `--model`、`--size`、`--reference-image`、`--output-format`、`--skip-existing` 等参数；先用 `--help` 查看当前签名。

## 当前配置默认值

- Seedance 默认模型：`doubao-seedance-2-0-mini-260615`；`--pro` 使用 `doubao-seedance-2-0-260128`。
- Seedance 默认 `16:9`、5 秒、生成音频、无水印；轮询间隔 30 秒，超时 600 秒。
- Seedream 默认模型：`doubao-seedream-5-0-pro-260628`；默认尺寸 `1920x1080`、URL 响应、无水印。
- 模型必须先在火山方舟控制台开通；不要为了验证文档而实际消耗 API 配额。

## 日志与可复现性

`SeedanceClient` 默认追加：

- `logs/seedance_requests.jsonl`：完整模型、比例、时长、音频/水印开关和 content payload。
- `logs/seedance_results.jsonl`：成功任务的 `task_id`、模型和公网 `video_url`。

`SeedreamClient` 默认追加：

- `logs/seedream_requests.jsonl`：请求参数（data URL 会被省略）。
- `logs/seedream_results.jsonl`：公网 `image_url` 与本地输出路径。

构造 client 时将 `request_log_path=None` 或 `result_log_path=None` 可关闭对应日志。日志可能包含用户提示词，不要把含敏感内容的日志提交到公共仓库。

## 开发约定与验证

- 路径统一使用 `agents.common.PROJECT_ROOT`；不要在各模块重复计算项目根路径。CLI 为兼容直接运行而插入 `sys.path` 属正常行为。
- 输出路径遵循 `output/projects/<标题>/character_images`、`raw_videos`、`final` 约定；实体文件名需经过安全化处理。
- 仓库目前没有测试套件。代码改动后至少运行相关 CLI 的 `--help`；不调用真实 API 时，可用已有项目配合 `--skip-existing` 做无成本检查。
- 修改配置或请求结构时同步检查 `instances_prompt.yaml`、`script.yaml`、`urls.json` 三个契约，避免下游 agent 无法读取。

## 路线图与成本提示

| Agent | 状态 | 说明 |
|---|---|---|
| script | ✅ 可用 | skill 生成实体清单与分镜 |
| image | ✅ 可用 | Seedream 5.0 Pro 生成参考图 |
| video | ✅ 可用 | Seedance 2.0 逐镜头生成 |
| editor | 📋 计划 | FFmpeg/字幕/配乐合成到 `final/` |
| publisher | 📋 计划 | 多平台发布 |

视频生成按时长计费（当前项目文档估算 Seedance 2.0 mini 约 ¥1/秒）；任何会产生 API 费用的命令都应由用户明确发起。
