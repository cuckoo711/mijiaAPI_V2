#!/usr/bin/env python3
"""
创建应用图标
支持使用用户提供的图片作为图标
"""

from PIL import Image, ImageDraw, ImageFont
import os
import sys


def create_icon_from_image(image_path: str):
    """从用户提供的图片创建图标"""
    # 打开用户提供的图片
    img = Image.open(image_path)
    
    # 转换为 RGBA 模式
    img = img.convert('RGBA')
    
    # 调整大小到 256x256
    img = img.resize((256, 256), Image.Resampling.LANCZOS)
    
    # 创建圆形蒙版
    mask = Image.new('L', (256, 256), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse([10, 10, 246, 246], fill=255)
    
    # 应用蒙版
    output = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
    output.paste(img, mask=mask)
    
    return output


def create_default_icon():
    """创建默认图标（绿色圆形 + M 字母）"""
    # 创建一个 256x256 的图像
    size = 256
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 绘制背景圆
    margin = 20
    draw.ellipse([margin, margin, size - margin, size - margin], fill=(0, 200, 83, 255))

    # 绘制 M 字母（简约风格）
    font_size = 140
    try:
        # 尝试使用系统字体
        font = ImageFont.truetype("arial.ttf", font_size)
    except:
        # 如果没有找到字体，使用默认字体
        font = ImageFont.load_default()

    # 计算文字位置使其居中
    text = "M"
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    x = (size - text_width) // 2
    y = (size - text_height) // 2 - 10

    # 绘制文字
    draw.text((x, y), text, fill=(255, 255, 255, 255), font=font)

    return img


def save_as_ico(img, output_path):
    """保存为 ICO 格式"""
    # ICO 格式支持多种尺寸
    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

    # 调整图像到不同尺寸
    images = []
    for size in sizes:
        resized = img.resize(size, Image.Resampling.LANCZOS)
        images.append(resized)

    # 保存为 ICO - 使用第一个图像保存，传入所有尺寸
    images[0].save(output_path, format='ICO', sizes=[(s.width, s.height) for s in images])
    print(f"Icon saved: {output_path}")


def main():
    """主函数"""
    assets_dir = os.path.join(os.path.dirname(__file__), 'assets')
    os.makedirs(assets_dir, exist_ok=True)

    # 检查是否有用户提供的图片
    user_image = os.path.join(assets_dir, 'icon_input.png')
    
    if os.path.exists(user_image):
        print(f"Using user provided image: {user_image}")
        img = create_icon_from_image(user_image)
    else:
        print("No user image found, using default icon")
        img = create_default_icon()

    # 保存为 PNG（预览用）
    png_path = os.path.join(assets_dir, 'icon.png')
    img.save(png_path, format='PNG')
    print(f"PNG icon saved: {png_path}")

    # 保存为 ICO
    ico_path = os.path.join(assets_dir, 'icon.ico')
    save_as_ico(img, ico_path)

    print("Icon creation completed!")


if __name__ == '__main__':
    main()
