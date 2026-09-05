"""
Generate synthetic photo-like test images for the cover renderer.

These are NOT stand-ins for real practice photos. They exist so the cover
pipeline (scrim, vignette, grain, contrast self-check, type legibility) can be
verified without spending anything on image generation. Replace them with real
photographs of the practice before using Part E for real.

    python fixtures/make_test_photos.py
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent.parent / "assets" / "photos"
W, H = 1600, 2000

# (id, base, accent, light_at) — light_at says where the frame is brightest,
# which is what the scrim has to fight.
SCENES = [
    ("operatory-window-light", (196, 206, 208), (120, 158, 162), "top"),
    ("reception-warm-evening", (74, 62, 54), (198, 150, 96), "bottom"),
    ("consult-room-neutral", (150, 152, 150), (96, 120, 126), "center"),
]


def gradient(base: tuple[int, int, int], accent: tuple[int, int, int],
             light_at: str) -> Image.Image:
    im = Image.new("RGB", (W, H))
    px = im.load()
    for y in range(H):
        t = y / H
        if light_at == "top":
            k = 1.0 - t * 0.72
        elif light_at == "bottom":
            k = 0.28 + t * 0.72
        else:
            k = 1.0 - abs(t - 0.5) * 1.35
        for x in range(0, W, 4):
            u = x / W
            r = int(base[0] * k + accent[0] * (1 - k) * 0.55 + u * 12)
            g = int(base[1] * k + accent[1] * (1 - k) * 0.55 + u * 8)
            b = int(base[2] * k + accent[2] * (1 - k) * 0.55)
            c = (max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))
            for dx in range(4):
                if x + dx < W:
                    px[x + dx, y] = c
    return im


def add_forms(im: Image.Image, accent: tuple[int, int, int], seed: int) -> Image.Image:
    """Soft out-of-focus shapes so the frame is not a flat ramp."""
    rnd = random.Random(seed)
    layer = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(layer)
    for _ in range(9):
        cx, cy = rnd.randint(0, W), rnd.randint(0, H)
        r = rnd.randint(140, 460)
        shade = rnd.randint(-40, 55)
        col = tuple(max(0, min(255, accent[i] + shade)) for i in range(3))
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
    layer = layer.filter(ImageFilter.GaussianBlur(120))
    return Image.blend(im, layer, 0.30)


def add_grain(im: Image.Image, seed: int, amount: int = 9) -> Image.Image:
    rnd = random.Random(seed)
    noise = Image.new("L", (W // 2, H // 2))
    noise.putdata([128 + rnd.randint(-amount, amount) for _ in range(
        (W // 2) * (H // 2))])
    noise = noise.resize((W, H), Image.BILINEAR)
    return Image.blend(im, Image.merge("RGB", (noise, noise, noise)), 0.10)


def vignette(im: Image.Image, strength: float = 0.35) -> Image.Image:
    mask = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(mask)
    for i in range(60):
        t = i / 60
        r = int(max(W, H) * (0.42 + 0.62 * t))
        v = int(255 * (1 - t) ** 1.6)
        d.ellipse([W // 2 - r, H // 2 - r, W // 2 + r, H // 2 + r], fill=v)
    mask = mask.filter(ImageFilter.GaussianBlur(90))
    dark = Image.new("RGB", (W, H), (0, 0, 0))
    return Image.composite(im, Image.blend(im, dark, strength), mask)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for i, (name, base, accent, light_at) in enumerate(SCENES):
        im = gradient(base, accent, light_at)
        im = add_forms(im, accent, seed=i * 17 + 3)
        im = vignette(im)
        im = add_grain(im, seed=i * 29 + 5)
        im = im.filter(ImageFilter.GaussianBlur(0.6))
        path = OUT / f"{name}.jpg"
        im.save(path, quality=88)
        print(f"wrote {path.name}  ({im.size[0]}x{im.size[1]}, bright at {light_at})")


if __name__ == "__main__":
    main()
