---
name: character-image-prompt
description: >
  生成并优化 Seedream 5.0 Pro 角色形象图片提示词。将角色描述转化为 7 段式
  英文提示词，并套用 Seedream 5.0 Pro 官方写作规范（自然语言、构图、画质、
  负向词）与输出参数（size / output_format / watermark 等）。作为可选润色工具，
  配合图片 agent（默认直接读 instances_prompt.yaml 的 appearance）生成定妆照。
---

# Character Image Prompt Skill（Seedream 5.0 Pro）

把角色描述转成**可直接喂给 Seedream 5.0 Pro** 的高质量英文提示词，并给出匹配的
生成参数。模型 `doubao-seedream-5-0-pro-260628`，官方教程见
`references/seedream_5_0_tutorial`（本 skill 的能力边界与参数表均以该文档为准）。

## 触发方式

```
/character-image-prompt 主角: 30岁白领，好奇心强，性格内向但关键时刻勇敢
```

或读 `instances_prompt.yaml` 里某实体的 `appearance`，用本 skill 优化成英文提示词后单张重生成。

## 一、7 段式提示词结构（角色定妆照模板）

每个角色提示词按顺序覆盖 7 段，段间用逗号连成**一段完整英文自然语言**：

| # | 段落 | 内容 | 示例片段 |
|---|------|------|---------|
| 1 | Age & Gender | 年龄、性别、物种/人种 | `4-year-old Border Collie` / `25-year-old Chinese male` |
| 2 | Face | 脸型、眼、鼻、肤质、标志特征 | `white face with a thin black eye line framing wise honest eyes` |
| 3 | Hair / Fur | 发型/毛色、长度、质感 | `black and white classic coat` |
| 4 | Build | 体型、身高、体态 | `sturdy body 22kg, standing upright` |
| 5 | Costume | 服装层次、颜色、配饰 | `red and black plaid neck band` |
| 6 | Expression & Pose | 默认表情、站姿、视线 | `grinning with tongue slightly out, front paws akimbo` |
| 7 | Style & Lighting | 画风、布光、画质 tag | `photorealistic, high detail` |

> 第 7 段固定收尾画质词，并按目标平台定画幅（见下方「画幅映射」）。

## 二、Seedream 5.0 Pro 写作规范

1. **写完整自然语言句子，别堆关键词**——Seedream 靠指令推理，不是标签匹配。
   ✅ `a woman in a navy blazer holding a coffee cup, standing in a modern lobby, natural lighting, editorial photography`
   ❌ `woman, blazer, coffee, lobby, natural light`
2. **聚焦 3–5 个关键元素**，宁短勿冗——400 字聚焦提示词 > 700 字流水账。
3. **具体 > 泛泛**：`almond-shaped eyes with warm brown irises` > `nice eyes`。
4. **避免自相矛盾**：`minimalist with lots of decorative elements` 会让模型无所适从。
5. **少用否定词**，描述「要什么」而非「不要什么」；确需排除的放**末尾**，并永久
   保留 `no logos, no watermarks`。
6. **别用 Midjourney 参数**：`--ar` / `--stylize` / `--chaos` 会被忽略。
7. **构图用自然语言**：`三分法构图` / `俯视鸟瞰` / `大留白，主体偏右` / `45度斜角`。
8. **文字渲染**：要生成的文字用引号包裹并指定字体，如
   `the poster reads "创意无界" in bold black sans-serif`。
9. **真实感反直觉技巧**：指定「缺陷」反而更真实——`自然传感器噪点、轻微手持晃动、
   柔和运动模糊`；避免塑料感可加 `no beauty filter, no AI-perfect sharpness`。

## 三、Seedream 5.0 Pro 输出参数

模型：`doubao-seedream-5-0-pro-260628`（已配在 `config/seedream.yaml` 的 `models.default`）。

| 参数 | 可选值 | 建议 |
|------|--------|------|
| `size` | `1K` / `1.5K` / `2K`（默认 2K），或 `宽x高` | 定妆照建议 `2K`；`1.5K` 与 `1K` 同价、效果更优 |
| `output_format` | `png` / `jpeg` | 需透明通道用 png |
| `response_format` | `url` / `b64_json` | 默认 url |
| `watermark` | `false` / `true` | 默认关；开则右下角加「AI生成」 |
| `optimize_prompt_options.mode` | `standard`（默认）/ `fast` | 对时延敏感选 fast，否则 standard 质量更优 |
| `background` | `opaque`（默认）/ `transparent` | transparent 仅图生图、且只输入 1 张带透明通道的图 |

### 画幅映射（size 档位 × 宽高比 → 实际像素）

短剧竖屏用 **9:16**，B 站横屏用 **16:9**。用 `size` 档位让模型按画幅出图，并在
prompt 里自然语言点一句画幅/用途（如 `vertical 9:16 portrait`）。

| size | 1:1 | 16:9 | 9:16 |
|------|-----|------|------|
| 1K   | 1024x1024 | 1424x800 | 800x1424 |
| 1.5K | 1536x1536 | 2048x1152 | 1152x2048 |
| 2K   | 2048x2048 | 2816x1584 | 1584x2816 |

> 自定义 `宽x高` 时须同时满足：总像素 ∈ [1280x720, 2048x2048×1.1025]，宽高比 ∈ [1/16, 16]。

## 四、Seedream 5.0 Pro 能力边界（别写进需求）

- 暂不支持：文生组图、单/多图生组图、流式输出、联网搜索。
- 输出上限 2K（总像素 ≤ 约 4624220），提示词里的「4K/8K」不会突破上限。
- 图片生成场景参考图**最多 10 张**（jpeg/png/webp/bmp/tiff/gif/heic/heif，≤30MB，
  宽高比 [1/16,16]，总像素 [196, 6000×6000]）。

## 五、Verification Checklist

生成/优化后逐项核对：

- [ ] 7 段齐全（年龄/脸/发/体型/服装/表情姿态/风格灯光）
- [ ] 全英文、完整自然语言句子（非关键词堆砌）
- [ ] 具体视觉细节，非泛泛形容词
- [ ] 第 7 段带画质 tag（photorealistic / high detail 等）+ 末尾 `no logos, no watermarks`
- [ ] 画幅匹配目标平台（竖屏 9:16 / 横屏 16:9）
- [ ] 无 Midjourney 参数、无自相矛盾、无纯否定
- [ ] 参数落在 Seedream 支持范围（size 档位、output_format、watermark）

## 六、与项目集成（可选手动润色）

- 图片 agent `agents/image/generator.py` 默认直接读 `script-writer` skill 产出的
  `instances_prompt.yaml`，用每个实体的 `appearance` 作为 Seedream 提示词，生成
  `character_images/<名>.jpg` + `character_images/urls.json`。
- 想得到更高质量的英文定妆照时，用本 skill 把某个实体的 `appearance` 优化成 7 段式英文
  提示词，再单张重生成：

```
.venv\Scripts\python.exe -m agents.image.generator --prompt "<7 段式英文提示词>" --name "<实体名>"
```

- 手工复核/重生成某角色：

```
/character-image-prompt 蜘蛛侠: 高中生，话痨，敏捷，红蓝紧身战衣，蛛网图案
```

## 角色类型速查（Costume / Lighting / Expression）

| 类型 | 服装 | 布光 | 表情 |
|------|------|------|------|
| 高冷主角 | Dark tailored suit | Low-key, shadow-heavy | Confident, slight smirk |
| 甜美女主 | Pastel tones, soft fabrics | Soft diffused natural | Warm smile, approachable |
| 反派 | Dark structured, sharp lines | Dramatic hard shadows | Cold gaze, thin lips |
| 搞笑配角 | Casual vibrant layers | Bright even | Playful, exaggerated |
| 长辈/导师 | Classic traditional | Warm ambient | Wise, calm, gentle |
