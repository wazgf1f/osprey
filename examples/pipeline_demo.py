"""Offline demo: build a fake UI, find its buttons, save an annotated image.

Runs headless (no screen capture, no input), so it doubles as a smoke test of
the vision stack:

    python examples/pipeline_demo.py
"""

from __future__ import annotations

import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from osprey.vision.io import save_image
from osprey.vision.match import match_template


def draw_button(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, label: str) -> None:
    draw.rounded_rectangle([x, y, x + w, y + h], radius=10, fill=(38, 108, 206), outline=(220, 235, 255), width=2)
    draw.text((x + 18, y + h // 2 - 8), label, fill=(255, 255, 255))


def build_scene() -> tuple:
    width, height = 960, 560
    scene = Image.new("RGB", (width, height), (18, 22, 30))
    draw = ImageDraw.Draw(scene)
    for y in range(height):
        shade = 18 + int(20 * y / height)
        draw.line([(0, y), (width, y)], fill=(shade, shade + 4, shade + 12))
    draw.rectangle([40, 40, 920, 140], fill=(28, 34, 46), outline=(60, 70, 90))
    draw.text((66, 74), "Osprey pipeline demo", fill=(240, 244, 252))
    draw_button(draw, 80, 200, 220, 64, "Continue")
    draw_button(draw, 80, 300, 220, 64, "Cancel")
    draw_button(draw, 600, 380, 180, 52, "Close")
    return np.asarray(scene), draw


def main() -> int:
    scene, _ = build_scene()
    template = scene[200:264, 80:300].copy()

    detections = match_template(scene, template, threshold=0.9, scales=(1.0, 0.9, 1.1))
    print("found %d match(es)" % len(detections))
    for det in detections:
        print("  x=%3d y=%3d w=%3d h=%3d score=%.4f scale=%.2f"
              % (det.x, det.y, det.w, det.h, det.score, det.scale))

    from osprey.vision.io import draw_detections

    annotated = draw_detections(scene, detections)
    output = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "demo_output.png")
    save_image(output, annotated)
    print("wrote", os.path.abspath(output))
    return 0 if detections else 1


if __name__ == "__main__":
    sys.exit(main())
