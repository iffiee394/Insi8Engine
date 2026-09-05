"""
Part D, step 6 — post-production with ffmpeg.

Does the four things that are pure mechanics and should never eat a human hour:

  normalise()  -> 1080x1920, cover-fit, no letterbox, audio levelled
  captions()   -> burned-in subtitles from the whisper segments
  cover()      -> a still frame for the Reel cover
  finish()     -> all of the above in one pass

Captions are burned in rather than left as a platform caption track because a
large share of the audience watches muted and platform auto-captions cannot be
styled or proofread. Burned-in text is also what survives cross-posting to
TikTok and Facebook. See DECISIONS.md D-17.

Windows note: the ffmpeg subtitles filter cannot take a Windows absolute path
with a drive letter, so every call runs with cwd set to the working directory
and refers to the subtitle file by bare filename.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # -> content-engine/

from shared import config  # noqa: E402

REEL_W, REEL_H = config.REEL_W, config.REEL_H


class FfmpegError(RuntimeError):
    pass


def ffmpeg_bin() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise FfmpegError(
            "ffmpeg not found on PATH. Install it (winget install Gyan.FFmpeg) "
            "or skip post-production and edit manually."
        )
    return exe


def run(args: list[str], cwd: Path | None = None) -> None:
    proc = subprocess.run(
        [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", *args],
        capture_output=True, text=True, cwd=str(cwd) if cwd else None, timeout=1800,
    )
    if proc.returncode != 0:
        raise FfmpegError(f"ffmpeg failed:\n{proc.stderr[-1500:]}")


def probe_duration(path: Path) -> float:
    exe = shutil.which("ffprobe")
    if not exe:
        return 0.0
    proc = subprocess.run(
        [exe, "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, timeout=120,
    )
    try:
        return float(json.loads(proc.stdout)["format"]["duration"])
    except Exception:  # noqa: BLE001
        return 0.0


# ---------------------------------------------------------------- subtitles

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{font},{size},&H00FFFFFF,&H00101820,&H80000000,-1,0,1,{outline},2,2,{ml},{mr},{mv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ass_time(seconds: float) -> str:
    cs = int(round(max(seconds, 0) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def _chunk_segment(text: str, max_chars: int = 34) -> list[str]:
    """Break a caption line so it never runs wider than the safe area."""
    words, out, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > max_chars and cur:
            out.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        out.append(cur)
    return out or [""]


def write_ass(
    segments: list[dict[str, Any]],
    out_path: Path,
    *,
    font: str = "Arial",
    size: int = 62,
    margin_v: int = 420,
) -> Path:
    """Build a styled .ass subtitle file from whisper segments.

    margin_v keeps captions above the platform UI (the caption/like rail eats
    roughly the bottom 300-400px of a 1920-tall Reel).
    """
    lines = [ASS_HEADER.format(
        w=REEL_W, h=REEL_H, font=font, size=size, outline=4,
        ml=80, mr=80, mv=margin_v,
    )]
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        start, end = float(seg.get("start", 0)), float(seg.get("end", 0))
        if end <= start:
            end = start + 1.2
        wrapped = r"\N".join(_chunk_segment(text))
        lines.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Caption,,0,0,0,,{wrapped}"
        )
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


# ---------------------------------------------------------------- operations


def normalise(src: Path, dst: Path) -> Path:
    """Cover-fit to 1080x1920 and level the audio. No letterboxing."""
    vf = (
        f"scale={REEL_W}:{REEL_H}:force_original_aspect_ratio=increase,"
        f"crop={REEL_W}:{REEL_H},fps=30,format=yuv420p"
    )
    run([
        "-i", str(src), "-vf", vf,
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
        str(dst),
    ])
    return dst


def burn_captions(src: Path, ass_file: Path, dst: Path) -> Path:
    """Burn the .ass captions in. Runs with cwd set so Windows paths behave."""
    work = ass_file.parent
    # ffmpeg runs with cwd=work, so a source already sitting in that directory
    # must be named bare — passing the original relative path would resolve to
    # work/out/_x/file.mp4 and fail.
    same_dir = src.parent.resolve() == work.resolve()
    rel_src = src.name if same_dir else str(src.resolve())
    run([
        "-i", rel_src,
        "-vf", f"subtitles={ass_file.name}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "copy", "-movflags", "+faststart",
        str(dst.resolve()),
    ], cwd=work)
    return dst


def cover_frame(src: Path, dst: Path, *, at: float = 0.8) -> Path:
    run(["-ss", str(at), "-i", str(src), "-frames:v", "1", "-q:v", "2", str(dst)])
    return dst


def trim(src: Path, dst: Path, *, start: float = 0.0, end: float | None = None) -> Path:
    args = ["-ss", str(start), "-i", str(src)]
    if end is not None:
        args += ["-to", str(max(end - start, 0.1))]
    args += ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", str(dst)]
    run(args)
    return dst


def finish(
    src: Path,
    out_dir: Path,
    *,
    slug: str,
    segments: list[dict[str, Any]] | None = None,
    make_cover: bool = True,
) -> dict[str, str]:
    """Full post pass: normalise -> captions -> cover."""
    out_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, str] = {}

    norm = out_dir / f"{slug}-1080x1920.mp4"
    print(f"  > normalising to {REEL_W}x{REEL_H}")
    normalise(src, norm)
    result["normalised"] = str(norm)
    final = norm

    if segments:
        print(f"  > burning {len(segments)} caption segments")
        ass = write_ass(segments, out_dir / f"{slug}.ass")
        captioned = out_dir / f"{slug}-captioned.mp4"
        burn_captions(norm, ass, captioned)
        result["captions_file"] = str(ass)
        result["captioned"] = str(captioned)
        final = captioned

    if make_cover:
        cov = out_dir / f"{slug}-cover.jpg"
        cover_frame(final, cov)
        result["cover"] = str(cov)

    result["final"] = str(final)
    result["duration"] = f"{probe_duration(final):.1f}"
    return result
