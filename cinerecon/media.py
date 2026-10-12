import math
import os
import re
import subprocess
from fractions import Fraction
from pathlib import Path
from PIL import Image, ImageDraw
import imageio_ffmpeg
from .common import require


def ffmpeg():
    return os.environ.get("FFMPEG_BIN") or imageio_ffmpeg.get_ffmpeg_exe()


def probe(path):
    p = subprocess.run([ffmpeg(), "-hide_banner", "-nostdin", "-i", str(path), "-map", "0:v:0", "-vf", "showinfo", "-frames:v", "1", "-f", "null", "-"], capture_output=True, text=True, check=True)
    rate = re.search(r"config in time_base:.*?frame_rate:\s*(\d+/\d+)", p.stderr)
    size = re.search(r"\bs:(\d+)x(\d+)", p.stderr)
    require(rate is not None and size is not None, "Cannot determine video frame rate/size")
    fps = float(Fraction(rate[1]))
    require(fps > 0, "Invalid video frame rate")
    counted = subprocess.run([ffmpeg(), "-v", "error", "-nostdin", "-i", str(path), "-map", "0:v:0", "-c", "copy", "-progress", "pipe:1", "-f", "null", "-"], capture_output=True, text=True, check=True)
    counts = re.findall(r"^frame=(\d+)", counted.stdout, re.M)
    require(bool(counts), "Cannot count video frames")
    return dict(fps=fps, fps_rational=rate[1], frames=int(counts[-1]), width=int(size[1]), height=int(size[2]))


def mapping(a, generated, frames):
    fps = generated["fps"]
    offset = a["source_frame_offset"] / a["fps"]
    start = math.ceil(offset * fps - 1e-6)
    end = math.ceil((offset + (a["end_frame"] + 1) / a["fps"]) * fps - 1e-6)
    require(0 <= start < end <= generated["frames"], "generated_time_range_unavailable")
    rows = []
    for f in frames:
        gf = min(end-start-1, max(0, round(f / a["fps"] * fps)))
        require(abs(f/a["fps"] - gf/fps) <= .51/fps, "Cannot align frame times")
        rows.append(dict(source_local_frame=f, source_absolute_frame=a["source_frame_offset"]+f,
                         generated_local_frame=gf, generated_absolute_frame=start+gf,
                         source_local_sec=f/a["fps"], generated_local_sec=gf/fps))
    return rows


def extract(path, indices, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    indices = sorted(set(indices))
    require(bool(indices), "No frames selected")
    expression = "select=" + "+".join(f"eq(n\\,{f})" for f in indices)
    subprocess.run([ffmpeg(), "-v", "error", "-xerror", "-nostdin", "-y", "-threads", "2", "-i", str(path), "-filter_threads", "1", "-vf", expression, "-vsync", "0", "-start_number", "0", "-compression_level", "2", str(destination/"frame_%06d.png")], capture_output=True, check=True, timeout=600)
    files = sorted(destination.glob("frame_*.png"))
    require(len(files) == len(indices), "Frame extraction incomplete")
    return dict(zip(indices, files))


def pair_image(source, generated, destination, clip_id, frame, seconds):
    canvas = Image.new("RGB", (960, 1136), "#101827")
    draw = ImageDraw.Draw(canvas)
    for path, label, y in [(source, "SOURCE reference", 0), (generated, "GENERATED evaluate", 568)]:
        draw.text((8, y+6), f"{label} | {clip_id} | LOCAL frame {frame} | t={seconds:.5f}s", fill="white")
        with Image.open(path) as original:
            im = original.convert("RGB")
            im.thumbnail((960, 540))
            canvas.paste(im, ((960-im.width)//2, y+28+(540-im.height)//2))
    canvas.save(destination, quality=94)
