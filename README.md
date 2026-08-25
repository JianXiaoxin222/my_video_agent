# video_agent

从「一句话创意 / 单个镜头提示词」到「短视频」的生成流水线，并提供 Video Agent Studio 节点式可视化界面。

1. `script-writer` skill —— 一句话 → 实体分析 + 镜头分镜（纯提示词，Claude 写文件）
2. 图片 agent —— 读 `instances_prompt.yaml`，为每个实体生成参考图（Seedream 5.0 Pro）
3. 视频 agent —— 逐镜头生成视频（Seedance 2.0）

CLI 仍可独立、可复跑；Studio 将提示词、图片、视频和脚本项目编排为可保存的 DAG 工作流。

## Video Agent Studio

安装新增依赖后，启动本地后端：

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe run_studio.py
```

另开终端启动节点画布：

```powershell
cd studio-ui
npm install
npm run dev
```

浏览器打开 `http://127.0.0.1:5173`。界面默认先生成安全预览，只有点击确认后才会调用 Seedream/Seedance。工作流和运行记录保存在 `output/.studio/studio.db`。

本地参考素材要参与真实 API 生成时，需要配置 `VIDEO_AGENT_S3_ENDPOINT`、`VIDEO_AGENT_S3_BUCKET`、`VIDEO_AGENT_S3_PUBLIC_BASE_URL`（以及对应的 S3 凭证）；也可以直接使用公网 URL。

### Studio 工作流

画布中的节点通过连线表达依赖，生成模式会根据上游素材自动推断：

| 节点 | 用途 |
| --- | --- |
| 文本输入 | 提供提示词或脚本文本 |
| 图片素材 / 视频素材 | 连接本地文件或公网 URL |
| 图片生成 | Seedream 文生图或图生图 |
| 视频生成 | Seedance 文生视频、图生视频或视频生视频 |
| 脚本项目 | 读写 `output/projects/<标题>/` 下的脚本契约 |
| 输出 | 连接并查看最终产物 |

建议的操作顺序是：添加输入和生成节点 → 连线 → 在右侧检查器确认提示词、模型、比例和时长 → 点击 **Preview** 检查 payload → 点击生成节点的 **Confirm generation**。也可以在画布上确认后执行整个工作流；每次真实 API 执行都会生成运行记录和事件流。

图片上传在未配置对象存储时可作为内联素材用于图生图；Seedance 的图片、视频参考必须是可访问的 `http(s)` 公网 URL，因此视频输入或图生视频场景需要配置 S3/OSS，或直接填写公网地址。Studio 后端会把运行事件写入 `logs/request/studio_YYYY-MM-DD.jsonl`、`logs/result/studio_YYYY-MM-DD.jsonl` 和 `logs/error/error_YYYY-MM-DD.jsonl`，前端连接失败或接口报错也会记录为客户端错误，便于排查。

后端提供健康检查 `GET http://127.0.0.1:8000/api/health`。若页面提示无法连接后端，请确认后端终端仍在运行，并检查 `logs/request/studio_YYYY-MM-DD.jsonl`、`logs/result/studio_YYYY-MM-DD.jsonl` 和 `logs/error/error_YYYY-MM-DD.jsonl`。

## 环境搭建

```powershell
# 方式一：一键（uv）
scripts\init_dev_env\setup_windows.bat

# 方式二：手动 venv
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

配置 API key：复制 `config/secrets.yaml.example` 为 `config/secrets.yaml` 并填写
`ark.api_key`（Seedance 视频）与 `seedream.api_key`（Seedream 图片）。该文件已
git-ignored，**切勿提交真实 key**。

## 使用（三步）

```powershell
# ① 脚本：用 /script-writer skill（纯提示词，Claude 写文件，不调 API）
#    产物：output/projects/<标题>/instances_prompt.yaml + script.yaml + script.md

# ② 图片：为每个实体生成参考图 + character_images/urls.json
.venv\Scripts\python.exe -m agents.image.generator --project-dir "output\projects\<标题>"

# ③ 视频：逐镜头手动生成（--image-urls 传实体参考图公网 URL，@图片N 按顺序对应）
.venv\Scripts\python.exe -m agents.video.generate --prompt "..." --image-urls "..." --ratio 16:9 --duration 5

# 无成本查看视频 payload（支持 text_to_video / image_to_video / video_to_video）
.venv\Scripts\python.exe -m agents.video.generate --prompt "..." --mode text_to_video --dry-run
```

`--dry-run` 只编译并打印请求 payload，不会产生 API 费用。真实生成前请确认模型已在火山方舟控制台开通，并检查实体顺序与 `@图片1`、`@视频1` 引用一致。

## 输出结构

```
output/projects/<标题>/
├── instances_prompt.yaml   # 实体清单（图片 agent 输入）
├── script.yaml             # title / overall_setting / instances[] / shots[]
├── script.md               # 人读版
├── character_images/       # 实体参考图 + urls.json（图片 agent 产出）
├── raw_videos/             # 逐镜头视频（视频 agent 产出）
└── final/                  # （占位）未来剪辑 agent 成品
```

## Skills

Claude Code 可用 skill（`.claude/skills/`）：

- `/script-writer` — 一句话 → 单镜头脚本（实体 + 分镜）
- `/character-image-prompt` — 英文定妆照提示词优化（可选）
- `/sd2-pe` — Seedance 2.0 提示词优化（可选）
- `/seedance-video` — Seedance 2.0 视频生成（第 3 步手册）

## 开发验证

不调用真实 API 的情况下，可运行仓库自带的 Studio 单元测试和前端类型/构建检查：

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
cd studio-ui
npm run build
```

测试会覆盖工作流 DAG 校验、预览 payload、素材上传回退和单节点执行。日志、`output/.studio/` 数据库以及生成的媒体文件均为本地运行产物，请勿把包含提示词或密钥的文件提交到公共仓库。

## 成本参考

- 视频生成（Seedance 2.0 mini 模型）约 ¥1/秒视频。
