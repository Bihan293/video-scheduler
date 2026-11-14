#!/usr/bin/env python3
"""Generate a vertical sample video used in the demo recording."""

from __future__ import annotations

import math
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "demo"
OUT = OUT_DIR / "sample.mp4"
COVER = OUT_DIR / "cover.png"

W, H, SECONDS = 1080, 1920, 6
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def make_cover() -> None:
    top, bottom = (10, 10, 18), (30, 17, 62)
    image = Image.new("RGB", (W, H), top)
    draw = ImageDraw.Draw(image)
    for y in range(H):
        draw.line([(0, y), (W, y)], fill=lerp(top, bottom, y / H))

    glow = Image.new("RGB", (W, H), (0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    for cx, cy, radius, color in (
        (W * 0.18, H * 0.30, 460, (37, 244, 238)),
        (W * 0.82, H * 0.36, 420, (254, 44, 85)),
        (W * 0.50, H * 0.14, 360, (124, 92, 255)),
    ):
        gdraw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=color)
    glow = glow.filter(ImageFilter.GaussianBlur(150))
    image = Image.blend(image, glow, 0.6)
    draw = ImageDraw.Draw(image)

    for i in range(1, 7):
        y = int(H * i / 7)
        draw.line([(90, y), (W - 90, y)], fill=(255, 255, 255), width=1)

    font_big = ImageFont.truetype(FONT_BOLD, 92)
    font_mid = ImageFont.truetype(FONT_REG, 44)
    font_small = ImageFont.truetype(FONT_REG, 30)

    def centered(text, font, y, fill):
        bbox = draw.textbbox((0, 0), text, font=font)
        draw.text(((W - (bbox[2] - bbox[0])) / 2, y), text, font=font, fill=fill)

    # Rounded badge
    badge = "TIKTOK READY"
    fbadge = ImageFont.truetype(FONT_BOLD, 26)
    bbox = draw.textbbox((0, 0), badge, font=fbadge)
    bw = bbox[2] - bbox[0] + 44
    draw.rounded_rectangle(
        [(W - bw) / 2, H * 0.27, (W + bw) / 2, H * 0.27 + 52],
        radius=26,
        outline=(37, 244, 238),
        width=2,
    )
    draw.text(
        ((W - (bbox[2] - bbox[0])) / 2, H * 0.27 + 10),
        badge,
        font=fbadge,
        fill=(37, 244, 238),
    )

    centered("ВИДЕО", font_big, H * 0.40, (255, 255, 255))
    centered("ГОТОВО", font_big, H * 0.40 + 108, (255, 255, 255))
    centered("Публикация в TikTok", font_mid, H * 0.57, (190, 190, 214))
    centered("VIDEO SCHEDULER", font_small, H * 0.82, (37, 244, 238))
    centered("00:0" + str(SECONDS), font_small, H * 0.12, (255, 255, 255))

    # Progress bar
    draw.rounded_rectangle(
        [120, H * 0.88, W - 120, H * 0.88 + 8], radius=4, fill=(255, 255, 255, 40)
    )
    draw.rounded_rectangle(
        [120, H * 0.88, W * 0.72, H * 0.88 + 8], radius=4, fill=(37, 244, 238)
    )

    image.save(COVER)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    make_cover()
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-loop",
            "1",
            "-i",
            str(COVER),
            "-vf",
            "zoompan=z='1.0+0.05*on/180':x='iw/2-(iw/zoom/2)':"
            "y='ih/2-(ih/zoom/2)':d=180:s=1080x1920:fps=30,format=yuv420p",
            "-t",
            str(SECONDS),
            "-c:v",
            "libx264",
            "-crf",
            "23",
            "-movflags",
            "+faststart",
            str(OUT),
        ],
        check=True,
    )
    print(f"created {OUT} ({OUT.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    sys.exit(main())
