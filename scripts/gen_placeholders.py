"""M1用プレースホルダ素材の生成（Pillowのみ・studio非依存）。

キャラ差分（表情・口パク）・背景・ロゴ・コーナーバッジ・B-roll仮画像・manifest を作る。
本番素材へは manifest.json 経由で無改修差し替え可能（SPEC 12章）。

    uv run python scripts/gen_placeholders.py
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
CHAR = ASSETS / "characters"
LAYOUT = ASSETS / "layout"

_FONT_CANDIDATES = [
    "C:/Windows/Fonts/meiryob.ttc",
    "C:/Windows/Fonts/meiryo.ttc",
    "C:/Windows/Fonts/msgothic.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
]


def font(size: int) -> ImageFont.FreeTypeFont:
    for c in _FONT_CANDIDATES:
        if Path(c).exists():
            return ImageFont.truetype(c, size)
    return ImageFont.load_default()


# --- キャラクター ------------------------------------------------------------

FOX = {"body": (255, 150, 60, 255), "belly": (255, 224, 196, 255), "ear": (60, 40, 30, 255)}
RABBIT = {"body": (245, 245, 250, 255), "belly": (255, 235, 240, 255), "ear": (255, 200, 210, 255)}

CW, CH = 560, 820


def _base(kind: str) -> tuple[Image.Image, ImageDraw.ImageDraw, dict]:
    pal = FOX if kind == "fox" else RABBIT
    img = Image.new("RGBA", (CW, CH), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # 体
    d.rounded_rectangle([120, 430, 440, 800], radius=120, fill=pal["body"])
    d.ellipse([190, 560, 370, 780], fill=pal["belly"])
    # 頭
    d.ellipse([130, 150, 430, 470], fill=pal["body"])
    # 耳
    if kind == "fox":
        d.polygon([(150, 210), (120, 40), (250, 170)], fill=pal["body"])
        d.polygon([(410, 210), (440, 40), (310, 170)], fill=pal["body"])
        d.polygon([(160, 190), (150, 90), (225, 165)], fill=pal["ear"])
        d.polygon([(400, 190), (410, 90), (335, 165)], fill=pal["ear"])
    else:
        d.ellipse([170, 20, 230, 230], fill=pal["body"])
        d.ellipse([330, 20, 390, 230], fill=pal["body"])
        d.ellipse([185, 60, 215, 210], fill=pal["ear"])
        d.ellipse([345, 60, 375, 210], fill=pal["ear"])
    return img, d, pal


def _eyes(d: ImageDraw.ImageDraw, variant: str) -> None:
    lx, rx, ey = 225, 335, 300
    if variant == "surprised":
        for cx in (lx, rx):
            d.ellipse([cx - 26, ey - 26, cx + 26, ey + 26], fill=(255, 255, 255, 255))
            d.ellipse([cx - 12, ey - 12, cx + 12, ey + 12], fill=(20, 20, 30, 255))
    elif variant == "smug":
        for cx in (lx, rx):
            d.arc([cx - 24, ey - 6, cx + 24, ey + 30], 200, 340, fill=(20, 20, 30, 255), width=8)
    elif variant == "worried":
        for cx, a, b in ((lx, 20, 160), (rx, 20, 160)):
            d.arc([cx - 22, ey - 10, cx + 22, ey + 26], a, b, fill=(20, 20, 30, 255), width=8)
    elif variant == "curious":
        d.ellipse([lx - 20, ey - 20, lx + 20, ey + 20], fill=(20, 20, 30, 255))
        d.ellipse([rx - 26, ey - 26, rx + 26, ey + 26], fill=(20, 20, 30, 255))
    else:  # normal
        for cx in (lx, rx):
            d.ellipse([cx - 20, ey - 22, cx + 20, ey + 22], fill=(20, 20, 30, 255))
            d.ellipse([cx - 6, ey - 14, cx + 8, ey], fill=(255, 255, 255, 255))


def _mouth(d: ImageDraw.ImageDraw, is_open: bool) -> None:
    mx, my = 280, 385
    if is_open:
        d.ellipse([mx - 34, my - 20, mx + 34, my + 40], fill=(120, 40, 50, 255))
        d.ellipse([mx - 18, my + 6, mx + 18, my + 34], fill=(220, 90, 110, 255))
    else:
        d.arc([mx - 34, my - 26, mx + 34, my + 22], 20, 160, fill=(60, 30, 30, 255), width=7)


def draw_char(kind: str, variant: str) -> Image.Image:
    img, d, _ = _base(kind)
    if variant == "mouth_open":
        _eyes(d, "normal")
        _mouth(d, True)
    elif variant == "mouth_closed":
        _eyes(d, "normal")
        _mouth(d, False)
    else:
        _eyes(d, variant)
        _mouth(d, False)
    return img


# --- レイアウト素材 ----------------------------------------------------------

W, H = 1080, 1920


def gradient(top: tuple, bottom: tuple) -> Image.Image:
    img = Image.new("RGB", (W, H))
    px = img.load()
    for y in range(H):
        u = y / H
        px_row = tuple(int(top[i] + (bottom[i] - top[i]) * u) for i in range(3))
        for x in range(W):
            px[x, y] = px_row
    return img


def make_bg() -> Image.Image:
    img = gradient((22, 26, 54), (58, 28, 74)).convert("RGBA")
    d = ImageDraw.Draw(img)
    for gy in range(0, H, 90):
        d.line([(0, gy), (W, gy)], fill=(255, 255, 255, 12), width=1)
    return img


def make_broll() -> Image.Image:
    img = gradient((20, 60, 80), (12, 30, 48)).convert("RGBA")
    d = ImageDraw.Draw(img)
    for r in range(120, 900, 160):
        d.ellipse([W // 2 - r, 700 - r, W // 2 + r, 700 + r], outline=(255, 255, 255, 20), width=3)
    d.text((W // 2, 1550), "B-ROLL", font=font(120), fill=(255, 255, 255, 40), anchor="mm")
    return img


def make_logo() -> Image.Image:
    f = font(56)
    txt = "AI産業革命報道局"
    d0 = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    tw = int(d0.textlength(txt, font=f))
    pad = 40
    img = Image.new("RGBA", (tw + pad * 2, 130), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, img.width - 1, img.height - 1], radius=40, fill=(230, 60, 70, 230))
    d.text((img.width // 2, img.height // 2), txt, font=f, fill=(255, 255, 255, 255), anchor="mm")
    return img


CORNERS = {
    "paper": "今日の論文",
    "news": "AI速報",
    "society": "AIと社会",
    "work": "AIと仕事",
}


def make_badge(label: str) -> Image.Image:
    f = font(44)
    d0 = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    tw = int(d0.textlength(label, font=f))
    pad = 32
    img = Image.new("RGBA", (tw + pad * 2, 96), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, img.width - 1, img.height - 1], radius=30, fill=(255, 190, 60, 235))
    d.text((img.width // 2, img.height // 2), label, font=f, fill=(40, 30, 20, 255), anchor="mm")
    return img


# --- 実行 --------------------------------------------------------------------


def main() -> None:
    (CHAR / "fox").mkdir(parents=True, exist_ok=True)
    (CHAR / "rabbit").mkdir(parents=True, exist_ok=True)
    LAYOUT.mkdir(parents=True, exist_ok=True)

    variants = {
        "fox": ["normal", "surprised", "smug", "worried", "mouth_open", "mouth_closed"],
        "rabbit": ["normal", "surprised", "curious", "mouth_open", "mouth_closed"],
    }
    manifest: dict[str, dict[str, str]] = {}
    for kind, vs in variants.items():
        manifest[kind] = {}
        for v in vs:
            draw_char(kind, v).save(CHAR / kind / f"{v}.png")
            manifest[kind][v] = f"{kind}/{v}.png"
    (CHAR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    make_bg().save(LAYOUT / "bg.png")
    make_broll().save(LAYOUT / "broll_placeholder.png")
    make_logo().save(LAYOUT / "logo.png")
    for corner, label in CORNERS.items():
        make_badge(label).save(LAYOUT / f"badge_{corner}.png")

    print("[ok] placeholders generated under assets/")


if __name__ == "__main__":
    main()
