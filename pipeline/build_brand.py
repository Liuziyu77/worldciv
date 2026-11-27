"""Render worldciv's README brand assets: a wordmark around the existing hex-globe mark, and rounded pill tags.

    python3 pipeline/build_brand.py        (needs Pillow)

The mark itself is docs/images/logo.png; the wordmark is set in Noto Serif SC (its Latin is a text serif), taken
from the chinaciv checkout's vendored font unless a local copy exists.
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "images")
MARK = os.path.join(OUT, "logo.png")

FONT_CANDIDATES_BOLD = [
    os.path.join(ROOT, "pipeline", "vendor", "NotoSerifSC-Bold.otf"),
    os.path.expanduser("~/My_Projects/chinaciv/pipeline/vendor/NotoSerifSC-Bold.otf"),
]
FONT_CANDIDATES_REG = [
    os.path.join(ROOT, "pipeline", "vendor", "NotoSerifSC-Regular.otf"),
    os.path.expanduser("~/My_Projects/chinaciv/pipeline/vendor/NotoSerifSC-Regular.otf"),
]
FONT_BOLD = next(p for p in FONT_CANDIDATES_BOLD if os.path.exists(p))
FONT_REG = next(p for p in FONT_CANDIDATES_REG if os.path.exists(p))

GOLD = (201, 164, 92)
GOLD_HI = (236, 208, 142)
INK_LIGHT = (24, 26, 30)
GREY_LIGHT = (104, 106, 112)
S = 2


def trim(img, pad=2):
    box = img.getchannel("A").getbbox()
    if not box:
        return img
    l, t, r, b = box
    return img.crop((max(0, l - pad), max(0, t - pad), min(img.width, r + pad), min(img.height, b + pad)))


def wordmark(path, main_fill, sub_fill):
    W, H = 1180 * S, 300 * S
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    icon = Image.open(MARK).convert("RGBA")
    icon = icon.resize((210 * S, 210 * S), Image.LANCZOS)
    img.alpha_composite(icon, (10 * S, (H - 210 * S) // 2))

    f_main = ImageFont.truetype(FONT_BOLD, 104 * S)
    f_dot = ImageFont.truetype(FONT_REG, 74 * S)
    f_sub = ImageFont.truetype(FONT_BOLD, 54 * S)
    d = ImageDraw.Draw(img)
    x = 10 * S + 210 * S + 46 * S
    mid = H // 2

    main = "worldciv"
    b = d.textbbox((0, 0), main, font=f_main)
    d.text((x, mid - (b[3] + b[1]) / 2 - 4 * S), main, font=f_main, fill=main_fill + (255,))
    x += b[2] - b[0] + 26 * S

    dot = "·"
    bd = d.textbbox((0, 0), dot, font=f_dot)
    d.text((x, mid - (bd[3] + bd[1]) / 2 - 2 * S), dot, font=f_dot, fill=sub_fill + (255,))
    x += bd[2] - bd[0] + 22 * S

    sub = "文明世界"
    bs = d.textbbox((0, 0), sub, font=f_sub)
    d.text((x, mid - (bs[3] + bs[1]) / 2 + 2 * S), sub, font=f_sub, fill=sub_fill + (255,))

    out = trim(img.resize((W // S, H // S), Image.LANCZOS), pad=2)
    out.save(path, optimize=True)
    print("wrote", path, out.size, os.path.getsize(path) // 1024, "KB")


def unify_frame(paths):
    imgs = [Image.open(p).convert("RGBA") for p in paths]
    w = max(i.width for i in imgs)
    h = max(i.height for i in imgs)
    for p, im in zip(paths, imgs):
        canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        canvas.alpha_composite(im, ((w - im.width) // 2, (h - im.height) // 2))
        canvas.save(p, optimize=True)
        print("unified", p, canvas.size)


def pill(path, label, value, tone):
    H, R = 30 * 3, 15 * 3
    f_lab = ImageFont.truetype(FONT_REG, 15 * 3)
    f_val = ImageFont.truetype(FONT_BOLD, 15 * 3)
    tmp = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    w_lab = tmp.textlength(label, font=f_lab)
    w_val = tmp.textlength(value, font=f_val) if value else 0
    gap = 10 * 3 if value else 0
    pad = 15 * 3
    W = max(H, int(pad * 2 + w_lab + gap + w_val))

    light, dark = tone
    body = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for yy in range(H):
        t = yy / (H - 1)
        c = tuple(int(light[k] + (dark[k] - light[k]) * t) for k in range(3))
        ImageDraw.Draw(body).line([(0, yy), (W, yy)], fill=c + (255,))

    gloss = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(gloss)
    top = int(H * 0.58)
    for yy in range(top):
        a = int(72 * (1 - yy / top) ** 1.4)
        if a:
            gd.line([(0, yy), (W, yy)], fill=(255, 255, 255, a))
    for yy in range(int(H * 0.62), H):
        a = int(55 * (yy - H * 0.62) / (H * 0.38))
        if a:
            gd.line([(0, yy), (W, yy)], fill=(0, 0, 0, a))
    body = Image.alpha_composite(body, gloss)
    rim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(rim).rounded_rectangle([1, 1, W - 2, H - 2], radius=R - 1, outline=(255, 255, 255, 66), width=2)
    body = Image.alpha_composite(body, rim)

    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, W - 1, H - 1], radius=R, fill=255)
    clipped = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    clipped.paste(body, (0, 0), mask)

    d = ImageDraw.Draw(clipped)
    d.text((pad, H / 2 + 1), label, font=f_lab, fill=(255, 255, 255, 224), anchor="lm")
    if value:
        d.text((pad + w_lab + gap, H / 2 + 1), value, font=f_val, fill=(255, 255, 255, 255), anchor="lm")

    out = Image.new("RGBA", (W + 10, H + 10), (0, 0, 0, 0))
    sh = Image.new("RGBA", (W + 10, H + 10), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([6, 8, W + 4, H + 8], radius=R, fill=(0, 0, 0, 80))
    out.alpha_composite(sh.filter(ImageFilter.GaussianBlur(4)))
    out.alpha_composite(clipped, (5, 3))
    out.resize(((W + 10) // 2, (H + 10) // 2), Image.LANCZOS).save(path, optimize=True)
    print("wrote", path, os.path.getsize(path) // 1024, "KB")


if __name__ == "__main__":
    light_p = os.path.join(OUT, "logo.png")          # overwritten below; keep the mark first
    navy = os.path.join(OUT, "logo-mark.png")
    if not os.path.exists(navy):
        Image.open(light_p).save(navy)
    word = os.path.join(OUT, "logo.png")
    dark = os.path.join(OUT, "logo-dark.png")
    wordmark(word, INK_LIGHT, GREY_LIGHT)
    wordmark(dark, GOLD_HI, GOLD)
    unify_frame([word, dark])

    tags = [
        ("15", "data layers", ((58, 110, 150), (24, 58, 86))),
        ("167", "countries", ((58, 110, 150), (24, 58, 86))),
        ("1,519", "cities", ((58, 110, 150), (24, 58, 86))),
        ("6,955", "power plants", ((150, 110, 50), (90, 62, 24))),
        ("Apache-2.0", "", ((52, 74, 96), (28, 42, 58))),
    ]
    for k, (a, b, tone) in enumerate(tags):
        pill(os.path.join(OUT, f"tag-{k}.png"), a, b, tone)
