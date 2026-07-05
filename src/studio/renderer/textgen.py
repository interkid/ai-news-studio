"""日本語字幕・テロップの PNG 生成（Pillow）。

SPEC 2章: 日本語字幕は TextClip ではなく Pillow で PNG 生成 → ImageClip 化する。
フォントは assets/fonts → 環境変数 → システムCJK の順にフォールバック。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ..shared.config import ASSETS, settings

# システムCJKフォントのフォールバック候補（本番は assets/fonts の Noto を推奨）
_SYSTEM_FALLBACKS = [
    "C:/Windows/Fonts/meiryo.ttc",
    "C:/Windows/Fonts/YuGothM.ttc",
    "C:/Windows/Fonts/msgothic.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
]


@lru_cache(maxsize=1)
def _font_file() -> str:
    # 1) assets/fonts に置かれた Noto を最優先
    fonts_dir = ASSETS / "fonts"
    if fonts_dir.is_dir():
        for pat in ("*NotoSansCJK*", "*NotoSansJP*", "*.otf", "*.ttf", "*.ttc"):
            hits = sorted(fonts_dir.glob(pat))
            if hits:
                return str(hits[0])
    # 2) 環境変数
    if settings.font_path and Path(settings.font_path).exists():
        return settings.font_path
    # 3) システムCJK
    for cand in _SYSTEM_FALLBACKS:
        if Path(cand).exists():
            return cand
    raise FileNotFoundError(
        "CJKフォントが見つかりません。assets/fonts に Noto Sans CJK JP を置くか "
        "FONT_PATH を設定してください。"
    )


@lru_cache(maxsize=32)
def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(_font_file(), size)


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_w: int, max_lines: int) -> list[str]:
    """日本語向けの文字単位折り返し（単語区切りがないため1文字ずつ計測）。"""
    lines: list[str] = []
    cur = ""
    for ch in text:
        if ch == "\n":
            lines.append(cur)
            cur = ""
            continue
        trial = cur + ch
        w = font.getbbox(trial)[2]
        if w > max_w and cur:
            lines.append(cur)
            cur = ch
        else:
            cur = trial
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        # 最終行を省略記号で詰める
        lines = lines[:max_lines]
        lines[-1] = lines[-1][:-1] + "…"
    return lines


def _render_multiline(
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
    stroke: tuple[int, int, int],
    stroke_px: int,
    line_gap: int = 12,
    underline: tuple[int, int, int] | None = None,
) -> Image.Image:
    ascent, descent = font.getmetrics()
    line_h = ascent + descent
    widths = [font.getbbox(ln)[2] for ln in lines]
    w = max(widths) + stroke_px * 2 + 16
    extra = 10 if underline else 0
    h = line_h * len(lines) + line_gap * (len(lines) - 1) + stroke_px * 2 + 8 + extra
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    y = stroke_px + 4
    for ln, lw in zip(lines, widths, strict=False):
        x = (w - lw) // 2
        draw.text(
            (x, y),
            ln,
            font=font,
            fill=fill,
            stroke_width=stroke_px,
            stroke_fill=stroke,
        )
        if underline:
            uy = y + line_h + 2
            draw.line([(x, uy), (x + lw, uy)], fill=underline, width=6)
        y += line_h + line_gap
    return img


def subtitle_png(
    text: str,
    accent: tuple[int, int, int],
    *,
    size: int,
    max_width: int,
    max_lines: int,
    stroke_px: int,
    fill: tuple[int, int, int],
    stroke: tuple[int, int, int],
) -> Image.Image:
    """字幕PNG（白文字+黒縁取り、話者色のアクセント下線、最大2行自動改行）。"""
    font = _font(size)
    lines = _wrap(text, font, max_width, max_lines)
    return _render_multiline(lines, font, fill, stroke, stroke_px, underline=accent)


def telop_png(
    text: str,
    *,
    size: int,
    fill: tuple[int, int, int] = (255, 255, 255),
    stroke: tuple[int, int, int] = (20, 20, 24),
    stroke_px: int = 8,
    max_width: int | None = None,
) -> Image.Image:
    """中央テロップ／フックPNG（縁取り付き大型文字）。"""
    font = _font(size)
    if max_width:
        lines = _wrap(text, font, max_width, 2)
    else:
        lines = text.split("\n")
    return _render_multiline(lines, font, fill, stroke, stroke_px)
