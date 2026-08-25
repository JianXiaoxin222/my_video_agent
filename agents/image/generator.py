"""Entity reference image generation via Seedream 5.0 Pro (火山方舟 Ark).

Consumes ``<project_dir>/instances_prompt.yaml`` (the entity list written by the
``script-writer`` skill — one ``instances[]`` entry per entity with an
``appearance``) and produces one reference image per entity under
``<project_dir>/character_images/``, plus a ``urls.json`` mapping entity name →
public image URL for the video step.

Entry points:
  - ``generate_character_images()`` — library function (name → prompt map).
  - ``python -m agents.image.generator --project-dir "output/projects/<title>"``
    — standalone CLI (no video cost involved).
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import mimetypes
import sys
from pathlib import Path

import yaml

# Ensure project root is on sys.path (supports ``python -m`` and direct runs).
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from agents.image.seedream_client import SeedreamClient
from agents.common.log_writer import install_error_logging, record_error

logger = logging.getLogger(__name__)

_SUPPORTED_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")


def _reference_image_to_api_value(value: str) -> str:
    """Return a Seedream-compatible URL or data URL for image-to-image."""
    if value.startswith(("http://", "https://", "data:")):
        return value

    path = Path(value)
    if not path.is_file():
        raise FileNotFoundError(f"reference image not found: {path}")
    mime_type, _ = mimetypes.guess_type(path.name)
    if mime_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise ValueError("reference image must be a JPEG, PNG, or WebP file")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _sanitize_name(name: str) -> str:
    """Make an entity name filesystem-safe."""
    safe = "".join(c if c.isalnum() or c in "._- " else "_" for c in name).strip()
    return safe or "character"


def load_instances(project_dir: str | Path) -> dict[str, str]:
    """Load the entity list from ``<project_dir>/instances_prompt.yaml``.

    Returns a dict mapping entity ``name`` → ``appearance`` (the static look,
    used as the Seedream image prompt). Raises FileNotFoundError if the file is
    missing and ValueError if the ``instances`` list is empty or unusable.
    """
    project_dir = Path(project_dir)
    yaml_path = project_dir / "instances_prompt.yaml"
    if not yaml_path.is_file():
        raise FileNotFoundError(f"instances_prompt.yaml not found: {yaml_path}")

    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    instances = data.get("instances", [])
    if not instances:
        raise ValueError(f"no instances in {yaml_path}")

    prompts: dict[str, str] = {}
    for inst in instances:
        name = (inst.get("name") or "").strip()
        appearance = (inst.get("appearance") or "").strip()
        if not name or not appearance:
            logger.warning("Skipping instance with missing name/appearance: %s", inst)
            continue
        prompts[name] = appearance

    if not prompts:
        raise ValueError(f"no usable instances (name + appearance) in {yaml_path}")
    return prompts


def generate_character_images(
    project_dir: str | Path,
    character_prompts: dict[str, str],
    api_key: str | None = None,
    image_config_path: str = "config/seedream.yaml",
    model: str | None = None,
    size: str | None = None,
    watermark: bool | None = None,
    output_format: str | None = None,
    skip_existing: bool = False,
    reference_images: dict[str, str] | None = None,
) -> dict[str, str]:
    """Generate a reference image for each entity prompt.

    Images are saved to ``<project_dir>/character_images/<name>.jpg`` (or
    ``.png`` when ``output_format="png"``). The returned dict maps entity
    name → local image path.

    Additionally, the public image URLs returned by Seedream are written to
    ``<project_dir>/character_images/urls.json`` (name → URL), so the video
    step can reference them directly as Seedance ``reference_image`` blocks
    without re-uploading.

    Args:
        project_dir: Path to the drama project directory.
        character_prompts: Dict mapping entity name → image prompt (appearance).
        api_key: Optional Ark API key (resolved from env/config if None).
        image_config_path: Path to seedream.yaml.
        model: Model ID override.
        size: Size override ("1K"/"1.5K"/"2K" or "WxH").
        watermark: Watermark override.
        output_format: Optional "png"/"jpeg" (None = model default).
        skip_existing: Skip characters whose image already exists.

    Returns:
        Dict mapping character name → saved image path (successes only).
        Empty dict when image generation is unavailable (e.g. no API key).
    """
    if not character_prompts:
        return {}

    project_dir = Path(project_dir)
    out_dir = project_dir / "character_images"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Constructing the client resolves the API key and raises ValueError when
    # none is available. In that case, degrade gracefully so the pipeline can
    # continue to text-only video generation.
    try:
        client = SeedreamClient(api_key=api_key, config_path=image_config_path)
    except ValueError as e:
        record_error("Image generation unavailable", exc=e)
        logger.warning("Skipping image generation — %s", e)
        return {}

    ext = ".png" if (output_format or "").lower() == "png" else ".jpg"
    results: dict[str, str] = {}
    urls: dict[str, str] = {}

    for name, prompt in character_prompts.items():
        safe_name = _sanitize_name(name)
        out_path = out_dir / f"{safe_name}{ext}"

        if skip_existing and out_path.exists():
            logger.info("Skipping %s (already exists: %s)", name, out_path)
            results[name] = str(out_path)
            continue

        logger.info("Generating image for %s → %s", name, out_path)
        try:
            _path, url = client.generate_image_url(
                prompt=prompt,
                output_path=out_path,
                reference_image=(
                    _reference_image_to_api_value(reference_images[name])
                    if reference_images and reference_images.get(name) else None
                ),
                model=model,
                size=size,
                watermark=watermark,
                output_format=output_format,
            )
            results[name] = str(_path)
            if url:
                urls[name] = url
            logger.info("✅ %s → %s (url=%s)", name, out_path, url or "<none>")
        except Exception as e:
            record_error("Failed to generate image", exc=e, context={"name": name, "output_path": str(out_path)})
            logger.error("❌ Failed to generate image for %s: %s", name, e)

    # Persist the public URLs so the bridge can reference them directly as
    # Seedance ``reference_image`` blocks (public URLs only — ``file://`` paths
    # are rejected by the Seedance API).
    if urls:
        urls_path = out_dir / "urls.json"
        try:
            urls_path.write_text(
                json.dumps(urls, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            logger.info("Wrote %d image URLs → %s", len(urls), urls_path)
        except Exception as e:
            record_error("Failed to write image URLs", exc=e, context={"path": str(urls_path)})
            logger.error("Failed to write %s: %s", urls_path, e)

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Seedream 5.0 Pro character image generation CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # ---- Input ----
    parser.add_argument(
        "--project-dir", type=str, default=None,
        help="Path to project dir (reads instances_prompt.yaml).",
    )
    parser.add_argument(
        "--prompt", "-p", type=str, default=None,
        help="Single text prompt (alternative to --project-dir; use with --name).",
    )
    parser.add_argument(
        "--name", type=str, default=None,
        help="Entity name for --prompt mode (used as the output filename).",
    )
    parser.add_argument(
        "--reference-image", type=str, default=None,
        help="Image-to-image source: a public URL, data URL, or local JPEG/PNG/WebP path.",
    )

    # ---- Model / params ----
    parser.add_argument(
        "--model", "-m", type=str, default=None,
        help="Seedream model ID. Uses config default if not set.",
    )
    parser.add_argument(
        "--size", "-s", type=str, default=None,
        help="Image size: 1K/1.5K/2K or WxH (e.g. 1152x2048). Uses config default if not set.",
    )
    parser.add_argument(
        "--watermark", action="store_true", default=None,
        help="Add the 'AI generated' watermark.",
    )
    parser.add_argument(
        "--output-format", type=str, default=None, choices=["png", "jpeg"],
        help="Output image format (default: model default, JPEG via url).",
    )

    # ---- Output ----
    parser.add_argument(
        "--output-dir", "-o", type=str, default=None,
        help="Output dir for --prompt mode (default: ./download).",
    )
    parser.add_argument(
        "--skip-existing", action="store_true",
        help="Skip entities whose image already exists.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print image request payload(s) and exit without calling the API.",
    )

    # ---- Config ----
    parser.add_argument(
        "--config", "-c", type=str, default="config/seedream.yaml",
        help="Path to seedream config file.",
    )
    parser.add_argument(
        "--api-key", type=str, default=None,
        help="Ark API key. Overrides env var and config file.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose logging.",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    install_error_logging()

    # ---- Single-prompt mode ----
    if args.prompt:
        name = args.name or "image"
        out_dir = Path(args.output_dir or "download")
        out_dir.mkdir(parents=True, exist_ok=True)
        ext = ".png" if (args.output_format or "").lower() == "png" else ".jpg"
        out_path = out_dir / f"{_sanitize_name(name)}{ext}"

        print("=" * 60)
        print("  Seedream 5.0 Pro Image Generation")
        print("=" * 60)
        print(f"  Prompt  : {args.prompt[:80]}{'...' if len(args.prompt) > 80 else ''}")
        print(f"  Output  : {out_path}")
        print("-" * 60)

        if args.dry_run:
            print(json.dumps({
                "model": args.model,
                "prompt": args.prompt,
                "image": args.reference_image,
                "size": args.size,
                "watermark": args.watermark,
                "output_format": args.output_format,
            }, ensure_ascii=False, indent=2))
            sys.exit(0)

        try:
            client = SeedreamClient(api_key=args.api_key, config_path=args.config)
            reference_image = (
                _reference_image_to_api_value(args.reference_image)
                if args.reference_image else None
            )
            final_path = client.generate(
                prompt=args.prompt,
                output_path=out_path,
                reference_image=reference_image,
                model=args.model,
                size=args.size,
                watermark=args.watermark,
                output_format=args.output_format,
            )
            print("=" * 60)
            # Keep CLI output ASCII-safe on Windows consoles using GBK.
            print(f"  Done: {final_path}")
            print("=" * 60)
            sys.exit(0)
        except Exception as e:
            record_error("Image generation CLI failed", exc=e, context={"output_path": str(out_path)})
            print(f"\n  Error: {e}", file=sys.stderr)
            if args.verbose:
                import traceback
                traceback.print_exc()
            sys.exit(1)

    # ---- Project mode ----
    if not args.project_dir:
        parser.error("either --project-dir or --prompt is required")

    project_dir = Path(args.project_dir)
    try:
        character_prompts = load_instances(project_dir)
    except FileNotFoundError as e:
        record_error("Image project file not found", exc=e, context={"project_dir": str(project_dir)})
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        record_error("Invalid image project", exc=e, context={"project_dir": str(project_dir)})
        print(f"Warning: {e}", file=sys.stderr)
        sys.exit(0)

    print("=" * 60)
    print("  Seedream 5.0 Pro Entity Reference Image Generation")
    print("=" * 60)
    print(f"  Project   : {project_dir}")
    print(f"  Entities  : {len(character_prompts)}")
    for name, prompt in character_prompts.items():
        preview = prompt[:60] + ("..." if len(prompt) > 60 else "")
        print(f"    - {name}: {preview}")
    print("-" * 60)

    reference_images: dict[str, str] = {}
    yaml_path = project_dir / "instances_prompt.yaml"
    try:
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        for instance in data.get("instances", []):
            name = (instance.get("name") or "").strip()
            generation = instance.get("generation") or {}
            reference = generation.get("reference_image") or instance.get("reference_image")
            if name and reference:
                reference_images[name] = str(reference)
    except Exception as exc:
        logger.warning("Could not read optional generation references: %s", exc)

    if args.dry_run:
        print(json.dumps({
            "model": args.model,
            "entities": [
                {"name": name, "prompt": prompt, "reference_image": reference_images.get(name)}
                for name, prompt in character_prompts.items()
            ],
            "size": args.size,
            "watermark": args.watermark,
            "output_format": args.output_format,
        }, ensure_ascii=False, indent=2))
        sys.exit(0)

    try:
        results = generate_character_images(
            project_dir=project_dir,
            character_prompts=character_prompts,
            api_key=args.api_key,
            image_config_path=args.config,
            model=args.model,
            size=args.size,
            watermark=args.watermark,
            output_format=args.output_format,
            skip_existing=args.skip_existing,
            reference_images=reference_images,
        )
    except Exception as e:
        record_error("Image generation CLI failed", exc=e, context={"project_dir": str(project_dir)})
        print(f"\n  Error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)

    print("=" * 60)
    if results:
        print(f"  Generated {len(results)}/{len(character_prompts)} images -> "
             f"{project_dir / 'character_images'}")
    else:
        print("  No images generated (check API key / model availability).")
    print("=" * 60)
    sys.exit(0 if results else 1)


if __name__ == "__main__":
    main()
