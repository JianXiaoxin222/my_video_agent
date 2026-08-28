# video_agent

从「一句话创意 / 单个镜头提示词」到「短视频」的生成流水线，并提供 Video Agent Studio 节点式可视化界面。

1. `script-writer` skill —— 一句话 → 实体分析 + 镜头分镜（纯提示词，Claude 写文件）
2. 图片 agent —— 读 `instances_prompt.yaml`，为每个实体生成参考图（Seedream 5.0 Pro）
3. 视频 agent —— 逐镜头生成视频（Seedance 2.0）

CLI 仍可独立、可复跑；Studio 将提示词、图片、视频和脚本项目编排为可保存的 DAG 工作流。

## 新手部署指南（Windows）

下面按“第一次接触本项目”的顺序说明。先完成本地安装和无费用自检，再运行真实生成；真实生成会消耗火山方舟额度。

### 0. 准备软件和账号

需要准备：

- Windows 10/11、Git；
- Python 3.12（安装时勾选 **Add Python to PATH**）；
- Node.js 18 或更高版本（会同时安装 `npm`，Studio 前端需要）；
- 火山方舟（Ark）账号、可用的 API key，以及已开通的 Seedance 2.0 和 Seedream 5.0 Pro 模型。

如果项目已经在电脑上，打开 PowerShell 进入项目目录并切换分支：

```powershell
cd D:\codingbook\video_agent
git switch fetch/text
```

如果还没有项目，请先在代码托管平台复制仓库地址，再执行 `git clone <仓库地址>`，然后进入生成的目录并运行上面的 `git switch fetch/text`。不要把 `<仓库地址>` 原样输入。

检查软件是否可用：

```powershell
git --version
python --version
node --version
npm --version
```

Python 应显示 3.12.x；如果电脑上有多个 Python，可用 `py -3.12 --version` 检查指定版本。

### 1. 创建 Python 环境并安装依赖

推荐直接运行仓库提供的安装脚本（脚本会尝试安装 `uv`、创建根目录下的 `.venv` 并安装 `requirements.txt`）：

```powershell
scripts\init_dev_env\setup_windows.bat
```

脚本运行完后，后续所有 Python 命令都使用项目自己的解释器 `.venv\Scripts\python.exe`。如果不想使用 `uv`，可以手动安装：

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

看到 `Successfully installed` 或脚本提示 `Setup Complete` 即可。每次打开新的终端都要先 `cd D:\codingbook\video_agent`；不需要反复创建 `.venv`。

### 2. 创建并填写 API key

1. 登录火山方舟控制台，创建 API key，并在模型服务中开通（或申请）下列模型。模型 ID 以控制台实际显示为准：
   - 视频：`doubao-seedance-2-0-mini-260615`（默认、成本较低）或 `doubao-seedance-2-0-260128`（`--pro`）；
   - 图片：`doubao-seedream-5-0-pro-260628`。
2. 在项目根目录复制密钥模板：

   ```powershell
   Copy-Item config\secrets.yaml.example config\secrets.yaml
   notepad config\secrets.yaml
   ```

3. 把模板中的占位符替换为真实 key（不要改缩进）：

   ```yaml
   ark:
     api_key: "这里填写可调用 Seedance 的 Ark API key"

   seedream:
     api_key: "这里填写可调用 Seedream 的 Ark API key"
   ```

   视频和图片分别读取 `ark.api_key` 与 `seedream.api_key`，代码不会自动用视频 key 代替图片 key。若账号策略允许同一个 key 调用两个模型，可以在两处填写同一个值。

`config/secrets.yaml` 已加入 `.gitignore`，请勿把它提交或截图发给他人。也可以不写入文件，临时在当前 PowerShell 窗口设置环境变量（关闭窗口后失效）：

```powershell
$env:ARK_API_KEY = "你的 Seedance key"
$env:SEEDREAM_API_KEY = "你的 Seedream key"
```

密钥读取优先级是：命令行 `--api-key` → 对应环境变量 → `config/secrets.yaml`。因此遇到“API key not found”时，先确认当前目录正确、文件名不是 `secrets.yaml.txt`，且没有留下 `your-...` 占位符。

### 3. （可选）配置默认模型和生成参数

第一次运行不需要修改配置。需要调整时编辑：

| 文件 | 作用 | 常用字段 |
| --- | --- | --- |
| `config/seedance.yaml` | 视频请求 | `models.default`、`defaults.ratio`、`defaults.duration`、`defaults.resolution`、`defaults.generate_audio` |
| `config/seedream.yaml` | 图片请求 | `models.default`、`defaults.size`、`defaults.response_format`、`defaults.output_format` |

默认视频为 16:9、5 秒、480p、带音频、无水印；默认图片为 1920x1080、URL 返回、无水印。模型必须先在火山方舟控制台开通，不能只修改 YAML 就使用未开通的模型。

### 4. 启动 Studio（需要两个终端）

终端 A 启动后端：

```powershell
cd D:\codingbook\video_agent
.venv\Scripts\python.exe run_studio.py
```

看到 Uvicorn 在 `127.0.0.1:8000` 监听后不要关闭此窗口。可另开浏览器访问健康检查：<http://127.0.0.1:8000/api/health>。

终端 B 安装并启动前端（第一次需要 `npm install`，以后只需 `npm run dev`）：

```powershell
cd D:\codingbook\video_agent\studio-ui
npm install
npm run dev
```

浏览器打开 <http://127.0.0.1:5173>。前后端都运行时才能使用画布；结束时分别在两个终端按 `Ctrl+C`。工作流和运行记录保存在 `output/.studio/studio.db`。

### 5. 本地素材和对象存储（按需）

纯文本生视频不需要对象存储。直接使用公网图片、视频或音频 URL 也不需要额外配置。

如果要在 Studio 中选择本地文件，并把它作为 Seedance 的参考素材，必须让方舟能通过公网 `http(s)` 地址访问该文件。任选一种方式：

1. 先把素材放到已有的公网图床/CDN，再在节点中填写 URL；或
2. 配置任意 S3 兼容对象存储（阿里云 OSS、Cloudflare R2、AWS S3 等）。在**启动后端前**于同一 PowerShell 窗口设置：

   ```powershell
   $env:VIDEO_AGENT_S3_ENDPOINT = "https://对象存储服务的 S3 endpoint"
   $env:VIDEO_AGENT_S3_BUCKET = "你的 bucket 名称"
   $env:VIDEO_AGENT_S3_PUBLIC_BASE_URL = "https://能公开访问该 bucket 的域名"
   $env:VIDEO_AGENT_S3_REGION = "可选的 region"
   $env:AWS_ACCESS_KEY_ID = "对象存储 Access Key"
   $env:AWS_SECRET_ACCESS_KEY = "对象存储 Secret Key"
   # 使用临时凭证时还可设置：$env:AWS_SESSION_TOKEN = "..."
   .venv\Scripts\python.exe run_studio.py
   ```

   `VIDEO_AGENT_S3_PUBLIC_BASE_URL` 必须能公开读取 `video-agent/<文件名>`，不能填控制台地址或本地路径。对象存储凭证只用于上传，不要写进 `seedance.yaml` 或提交到 Git。

未配置对象存储时，Studio 仍可把本地图片作为图生图的内联素材；但图生视频、视频参考和音频参考仍必须使用公网 URL。Seedream 返回的图片 URL 会自动写入项目的 `character_images/urls.json`。

### 6. 不花钱的安装自检

以下命令只检查依赖和请求结构，不会调用 API：

```powershell
cd D:\codingbook\video_agent
.venv\Scripts\python.exe -m agents.video.generate --prompt "一只猫走过海边" --mode text_to_video --dry-run
.venv\Scripts\python.exe -m agents.image.generator --prompt "一只橘猫，正面肖像" --name "cat" --dry-run
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

三个命令都正常结束后，说明 Python 环境基本可用；`--dry-run` 不会产生费用。真实生成前仍要确认模型已开通、账户有余额或额度，并检查提示词中的 `@图片1` / `@视频1` 与参考素材顺序一致。

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

## 常见问题

| 现象 | 处理方式 |
| --- | --- |
| `.venv\Scripts\python.exe` 找不到 | 在项目根目录重新运行 `scripts\init_dev_env\setup_windows.bat`，或按上面的手动方式创建虚拟环境。 |
| `ARK_API_KEY not found` / `SEEDREAM_API_KEY not found` | 检查 `config\secrets.yaml` 是否存在、缩进是否正确、占位符是否已替换；若使用 `$env:...`，请在启动后端或执行 CLI 的同一个终端中设置。 |
| `model not found`、无权限或配额错误 | 在火山方舟控制台开通对应模型，核对 `config\seedance.yaml` / `config\seedream.yaml` 中的模型 ID 和账户额度。 |
| 页面提示无法连接后端 | 确认终端 A 仍在运行，并访问 <http://127.0.0.1:8000/api/health>；前端地址必须是 <http://127.0.0.1:5173>。 |
| 本地素材无法用于视频生成 | 填写可公开访问的 `http(s)` URL，或先配置 `VIDEO_AGENT_S3_*` 和 AWS 兼容凭证，再重启后端。 |
| `npm install` 或 `npm run dev` 失败 | 确认 `node --version` 为 18+，并在 `studio-ui` 目录执行；网络受限时需允许访问 npm registry。 |

报错详情和请求/结果记录位于 `logs/error/`、`logs/request/`、`logs/result/`。日志可能包含提示词和 URL，提交问题或公开仓库前请先脱敏。

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
