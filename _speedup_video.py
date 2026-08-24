# -*- coding: utf-8 -*-
"""Speed up a video using imageio-ffmpeg's bundled ffmpeg binary.

Usage:
    .venv\\Scripts\\python.exe _speedup_video.py <input> <output> [factor]
    factor defaults to 1.8 (1.8x playback speed).
"""
import subprocess
import sys

import imageio_ffmpeg

inp = sys.argv[1]
outp = sys.argv[2]
factor = sys.argv[3] if len(sys.argv) > 3 else "1.8"

ff = imageio_ffmpeg.get_ffmpeg_exe()
cmd = [
    ff, "-y", "-i", inp,
    "-filter_complex", f"[0:v]setpts=PTS/{factor}[v];[0:a]atempo={factor}[a]",
    "-map", "[v]", "-map", "[a]",
    "-c:v", "libx264", "-preset", "medium", "-crf", "18",
    "-c:a", "aac",
    outp,
]
print("Running:", " ".join(cmd))
subprocess.run(cmd, check=True)
print("DONE:", outp)
