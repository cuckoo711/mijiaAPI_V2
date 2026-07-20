#!/usr/bin/env python3
"""Create application icons under deploy/assets/."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"


def create_icon_from_image(image_path: Path) -> Image.Image:
    img = Image.open(image_path).convert("RGBA")
    img = img.resize((256, 256), Image.Resampling.LANCZOS)

    mask = Image.new("L", (256, 256), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse([10, 10, 246, 246], fill=255)

    output = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    output.paste(img, mask=mask)
    return output


def create_default_icon() -> Image.Image:
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    margin = 20
    draw.ellipse(
        [margin, margin, size - margin, size - margin], fill=(0, 200, 83, 255)
    )

    font_size = 140
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except OSError:
        font = ImageFont.load_default()

    text = "M"
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    x = (size - text_width) // 2
    y = (size - text_height) // 2 - 10
    draw.text((x, y), text, fill=(255, 255, 255, 255), font=font)
    return img


def save_as_ico(img: Image.Image, output_path: Path) -> None:
    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    images = [img.resize(size, Image.Resampling.LANCZOS) for size in sizes]
    images[0].save(
        output_path,
        format="ICO",
        sizes=[(image.width, image.height) for image in images],
    )
    print(f"Icon saved: {output_path}")


def main() -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    user_image = ASSETS_DIR / "icon_input.png"

    if user_image.exists():
        print(f"Using user provided image: {user_image}")
        img = create_icon_from_image(user_image)
    else:
        print("No user image found, using default icon")
        img = create_default_icon()

    png_path = ASSETS_DIR / "icon.png"
    img.save(png_path, format="PNG")
    print(f"PNG icon saved: {png_path}")

    ico_path = ASSETS_DIR / "icon.ico"
    save_as_ico(img, ico_path)
    print("Icon creation completed!")


if __name__ == "__main__":
    main()
