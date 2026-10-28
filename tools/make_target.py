"""Generate examples/assets/target.png, the demo target card."""

from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont


def load_font(size: int):
    for name in ("seguisb.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10
        return ImageFont.load_default()


def build() -> Image.Image:
    width, height = 320, 220
    image = Image.new("RGB", (width, height), (10, 14, 22))
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle([4, 4, width - 5, height - 5], radius=16,
                           fill=(16, 22, 34), outline=(0, 224, 255), width=3)
    for radius, color in ((72, (0, 224, 255)), (52, (255, 82, 82)), (32, (255, 255, 255))):
        cx, cy = 92, 96
        draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius],
                     outline=color, width=4)
    draw.line([(20, 96), (164, 96)], fill=(0, 224, 255), width=2)
    draw.line([(92, 24), (92, 168)], fill=(0, 224, 255), width=2)

    title = load_font(30)
    small = load_font(16)
    draw.text((182, 62), "OSPREY", font=title, fill=(240, 248, 255))
    draw.text((184, 100), "TARGET", font=title, fill=(0, 224, 255))
    draw.text((184, 146), "move me on screen", font=small, fill=(150, 165, 190))
    return image


def main() -> None:
    target = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "examples", "assets")
    os.makedirs(target, exist_ok=True)
    path = os.path.abspath(os.path.join(target, "target.png"))
    build().save(path)
    print("wrote", path)


if __name__ == "__main__":
    main()
