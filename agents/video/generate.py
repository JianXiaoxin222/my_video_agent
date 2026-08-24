#!/usr/bin/env python3
"""Seedance 2.0 video generation CLI.

Non-interactive command-line interface for creating, polling, and downloading
videos from the Seedance 2.0 API.

Supports all generation modes:
  - Text-to-Video:        --prompt "..."  (no reference materials)
  - Image-to-Video:       --prompt "..." --image-urls URL1 --image-urls URL2
  - First/last frame:     --prompt "..." --first-frame URL --last-frame URL
  - Video-to-Video:       --prompt "..." --video-url URL --image-urls URL
  - Multi-modal:          --prompt "..." --image-urls URL --video-url URL --audio-url URL

Usage examples:
  # Text-to-video
  python -m agents.video.generate --prompt "A cat walking on a sunny beach" --duration 5

  # Image-to-video with character references
  python -m agents.video.generate --prompt "参考 @图片1 中的女孩，在咖啡馆吃蛋糕" \
      --image-urls "https://example.com/girl.jpg" --duration 10 --ratio 9:16

  # Video editing (replace object in existing video)
  python -m agents.video.generate --prompt "将视频1礼盒中的香水替换成图片1中的面霜" \
      --image-urls "https://example.com/cream.jpg" \
      --video-url "https://example.com/giftbox.mp4"

  # Custom output directory
  python -m agents.video.generate --prompt "..." --output-dir "download/my_project"
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Ensure project root is on sys.path
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from agents.video.seedance_client import SeedanceClient


def build_content_blocks(
    prompt: str,
    image_urls: list[str] | None = None,
    video_url: str | None = None,
    audio_url: str | None = None,
    first_frame_url: str | None = None,
    last_frame_url: str | None = None,
) -> list[dict]:
    """Build the content array for the Seedance API from CLI arguments.

    Content blocks are ordered: text first, then images, then video, then audio.
    This ordering ensures prompt references like @图片1, @视频1 work correctly
    (indexing matches array position of non-text blocks).

    Args:
        prompt: Text prompt (required).
        image_urls: Optional list of reference image URLs.
        video_url: Optional reference video URL.
        audio_url: Optional reference audio URL.
        first_frame_url: Optional strict first-frame image URL.
        last_frame_url: Optional strict last-frame image URL.

    Returns:
        List of content block dicts ready for SeedanceClient.create_task().
    """
    content: list[dict] = []

    # Text prompt always comes first
    if prompt:
        content.append({"type": "text", "text": prompt})

    # Strict first/last frame blocks must precede ordinary image references.
    # Seedance numbers all non-text image blocks in this order, so prompts can
    # refer to them consistently as 图片1, 图片2, ... when needed.
    if first_frame_url:
        content.append({
            "type": "image_url",
            "image_url": {"url": first_frame_url},
            "role": "first_frame",
        })
    if last_frame_url:
        content.append({
            "type": "image_url",
            "image_url": {"url": last_frame_url},
            "role": "last_frame",
        })

    # Ordinary reference images
    if image_urls:
        for url in image_urls:
            content.append({
                "type": "image_url",
                "image_url": {"url": url},
                "role": "reference_image",
            })

    # Reference video
    if video_url:
        content.append({
            "type": "video_url",
            "video_url": {"url": video_url},
            "role": "reference_video",
        })

    # Reference audio
    if audio_url:
        content.append({
            "type": "audio_url",
            "audio_url": {"url": audio_url},
            "role": "reference_audio",
        })

    return content


def main():
    parser = argparse.ArgumentParser(
        description="Seedance 2.0 video generation CLI — non-interactive",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # ---- Content ----
    parser.add_argument(
        "--prompt", "-p", required=True, type=str,
        help="Text prompt describing the video generation/editing task.",
    )
    parser.add_argument(
        "--image-urls", type=str, action="append", default=None,
        help="Reference image URL. Repeat for multiple images (e.g. --image-urls URL1 --image-urls URL2).",
    )
    parser.add_argument(
        "--first-frame", type=str, default=None,
        help="Strict first-frame image URL (role=first_frame).",
    )
    parser.add_argument(
        "--last-frame", type=str, default=None,
        help="Strict last-frame image URL (role=last_frame).",
    )
    parser.add_argument(
        "--video-url", type=str, default=None,
        help="Reference video URL (for video editing / style reference).",
    )
    parser.add_argument(
        "--audio-url", type=str, default=None,
        help="Reference audio URL (for voice / music style reference).",
    )
    parser.add_argument(
        "--mode", choices=["text_to_video", "image_to_video", "video_to_video", "first_last_frame_to_video"], default=None,
        help="Explicit generation mode; when omitted it is inferred from reference inputs.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the request payload and exit without calling the API.",
    )

    # ---- Model ----
    parser.add_argument(
        "--model", "-m", type=str, default=None,
        help="Model ID. Uses config default if not set.",
    )
    parser.add_argument(
        "--pro", action="store_true",
        help="Use the pro model (doubao-seedance-2-0-260128) instead of default.",
    )

    # ---- Parameters ----
    parser.add_argument(
        "--ratio", "-r", type=str, default=None,
        choices=["21:9", "16:9", "4:3", "1:1", "3:4", "9:16"],
        help="Aspect ratio. Uses config default if not set.",
    )
    parser.add_argument(
        "--duration", "-d", type=int, default=None,
        help="Video duration in seconds. Uses config default if not set.",
    )
    parser.add_argument(
        "--watermark", action="store_true", default=None,
        help="Add watermark to output video.",
    )
    parser.add_argument(
        "--no-audio", action="store_true",
        help="Disable audio generation.",
    )
    parser.add_argument(
        "--resolution", type=str, default=None,
        choices=["480p", "720p", "1080p", "4k"],
        help="Output resolution.",
    )
    parser.add_argument(
        "--return-last-frame", action="store_true",
        help="Also request the generated video's last-frame image.",
    )

    # ---- Polling ----
    parser.add_argument(
        "--poll-interval", type=int, default=None,
        help="Seconds between status checks (default: from config, usually 30).",
    )
    parser.add_argument(
        "--timeout", type=int, default=None,
        help="Max wait time in seconds (default: from config, usually 600).",
    )

    # ---- Output ----
    parser.add_argument(
        "--output-dir", "-o", type=str, default="download",
        help="Directory to save downloaded videos (default: download/).",
    )
    parser.add_argument(
        "--output-name", type=str, default=None,
        help="Output filename (default: auto-generated from timestamp).",
    )

    # ---- Config ----
    parser.add_argument(
        "--config", "-c", type=str, default="config/seedance.yaml",
        help="Path to seedance config file (default: config/seedance.yaml).",
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

    # Setup logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # ---- Resolve model ----
    client = SeedanceClient(
        api_key=args.api_key,
        config_path=args.config,
    )
    model = args.model
    if args.pro:
        model = client.pro_model
    elif model is None:
        model = client.default_model

    # ---- Build content ----
    content = build_content_blocks(
        prompt=args.prompt,
        image_urls=args.image_urls,
        video_url=args.video_url,
        audio_url=args.audio_url,
        first_frame_url=args.first_frame,
        last_frame_url=args.last_frame,
    )

    inferred_mode = "video_to_video" if args.video_url else ("first_last_frame_to_video" if (args.first_frame or args.last_frame) else ("image_to_video" if args.image_urls else "text_to_video"))
    if args.mode and args.mode != inferred_mode:
        parser.error(f"--mode {args.mode} does not match provided reference inputs (inferred {inferred_mode})")
    if args.dry_run:
        import json
        print(json.dumps({"mode": inferred_mode, "model": model, "content": content,
                          "ratio": args.ratio, "duration": args.duration,
                          "watermark": args.watermark, "generate_audio": not args.no_audio,
                          "resolution": args.resolution, "return_last_frame": args.return_last_frame},
                         ensure_ascii=False, indent=2))
        sys.exit(0)

    # ---- Determine output path ----
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.output_name:
        output_path = output_dir / args.output_name
    else:
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"seedance_{timestamp}.mp4"

    # ---- Run ----
    print("=" * 60)
    print("  Seedance 2.0 Video Generation")
    print("=" * 60)
    print(f"  Model    : {model}")
    print(f"  Ratio    : {args.ratio or client._defaults.get('ratio', '16:9')}")
    print(f"  Duration : {args.duration or client._defaults.get('duration', 5)}s")
    print(f"  Resolution: {args.resolution or client._defaults.get('resolution', '480p')}")
    print(f"  Audio    : {'off' if args.no_audio else 'on'}")
    print(f"  Watermark: {'on' if args.watermark else 'off'}")
    print(f"  Output   : {output_path}")
    content_types = [b["type"] for b in content]
    print(f"  Content  : {content_types}")
    print("-" * 60)

    try:
        # Create task
        task_id = client.create_task(
            content=content,
            model=model,
            ratio=args.ratio,
            duration=args.duration,
            watermark=args.watermark,
            generate_audio=not args.no_audio,
            resolution=args.resolution,
            return_last_frame=args.return_last_frame,
        )
        print(f"  Task ID  : {task_id}")
        print(f"  Status   : queued -> polling every "
              f"{args.poll_interval or client._defaults.get('poll_interval', 30)}s...")
        print("-" * 60)

        # Poll with progress dots
        dot_count = [0]  # mutable counter for closure

        def on_status(status: str):
            dot_count[0] += 1
            sys.stdout.write(f"\r  [{status:12s}] {'.' * min(dot_count[0], 60)}")
            sys.stdout.flush()

        # Poll until complete
        result = client.poll_task(
            task_id,
            poll_interval=args.poll_interval,
            timeout=args.timeout,
            on_status=on_status,
        )
        print()  # newline after dots

        # Download
        print("-" * 60)
        print(f"  Video URL: {result.content.video_url}")
        print(f"  Downloading -> {output_path} ...")

        final_path = client.download_video(result.content.video_url, output_path)

        print("=" * 60)
        print(f"  DONE: {final_path}")
        print("=" * 60)
        sys.exit(0)

    except TimeoutError as e:
        print(f"\n  TIMEOUT: {e}", file=sys.stderr)
        print(f"  You can check the task later with get_task('{task_id}').", file=sys.stderr)
        sys.exit(2)
    except RuntimeError as e:
        print(f"\n  FAILED: {e}", file=sys.stderr)
        sys.exit(3)
    except Exception as e:
        print(f"\n  ERROR: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
