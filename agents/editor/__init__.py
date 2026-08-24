"""Agent (planned) — multi-clip video editing / assembly.

Takes the per-scene videos produced by the video agent plus the script
(subtitles / dialogue / BGM hints) and assembles a final cut (FFmpeg xfade,
MoviePy, Whisper subtitles, TTS voiceover, background music). Outputs to
<project_dir>/final/.
"""
