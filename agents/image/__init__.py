"""Agent — 实体参考图生成（Seedream 5.0 Pro，火山方舟 Ark）。

从 ``instances_prompt.yaml``（script-writer skill 产出的实体清单）读取每个实体的
``appearance``，生成 ``character_images/<名>.jpg`` 参考图与 ``urls.json``（名 → 公网 URL），
供视频生成步骤直接取用为 Seedance ``reference_image``。

Entry points:
  - ``python -m agents.image.generator --project-dir <dir>``（standalone CLI）
  - ``load_instances()`` / ``generate_character_images()`` in ``agents/image/generator.py``
  - ``SeedreamClient`` in ``agents/image/seedream_client.py``（可复用客户端）
"""
