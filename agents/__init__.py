"""video_agent — 一句话 → 单镜头脚本 → 参考图 → 视频（手动三步流水线）。

三步手动流程（无自动化流水线，每步独立、可单跑、可复跑）：
  1. script-writer skill — 单镜头脚本（instances_prompt.yaml / script.yaml / script.md）
  2. agents.image        — 实体参考图（Seedream 5.0 Pro）
  3. agents.video        — 逐镜头视频（Seedance 2.0，generate.py）

Agents:
  - agents.image     : Seedream 5.0 Pro 实体参考图生成
  - agents.video     : Seedance 2.0 单视频生成（generate.py + seedance_client）
  - agents.editor    : [planned] 多段视频剪辑合成
  - agents.publisher : [planned] 多平台发布
"""
