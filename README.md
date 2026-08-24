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

## 成本参考

- 视频生成（Seedance 2.0 mini 模型）约 ¥1/秒视频。
