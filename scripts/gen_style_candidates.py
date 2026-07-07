"""M5-1: キャラ画風のスタイル候補を Nano Banana Pro で生成する（1回きりの選定用）。

きつね+うさぎを1枚に並べたスタイル見本を4案生成し、
assets/characters/style_candidates/ に保存する。人間が1案を選んだら
本番のベースキャラ確定・表情差分生成に進む（NEXT_STEPS.md M5-1）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

from studio.shared.config import settings

FAL_ENDPOINT = "https://fal.run/fal-ai/nano-banana-pro"

BASE_PROMPT = (
    "An original mascot duo for a Japanese short-video news show: an orange fox "
    "news presenter with chibi proportions (about 2.5 heads tall), round friendly "
    "face, big round eyes, wearing small round glasses, a red bow tie and a navy "
    "news-anchor vest; and a soft cream-white rabbit listener with chibi "
    "proportions, big sparkling eyes, rosy cheeks, wearing a small yellow "
    "neckerchief. Standing side by side, full body, facing the viewer, friendly "
    "expressions, simple plain light background, no text, no logos, vertical "
    "composition. Completely original character designs, must NOT resemble any "
    "existing movie or anime characters (especially NOT Zootopia's Nick Wilde or "
    "Judy Hopps: different proportions, different outfits, different face shapes). "
    "Clearly stylized cartoon animals, NOT photorealistic, not a real photograph. "
)

STYLES: dict[str, str] = {
    "pixar_3dcg": (
        "Pixar-style 3DCG render, soft studio lighting, expressive big eyes, "
        "subsurface scattering, high-quality animation film look"
    ),
    "atsunuri_fur": (
        "Richly painted thick-paint (atsunuri) digital illustration, detailed fur "
        "brushwork, warm cinematic lighting, painterly texture"
    ),
    "rich_anime": (
        "High-end modern Japanese anime style, clean sharp lineart, vivid cel shading "
        "with soft gradient accents, glossy finish"
    ),
    "storybook_watercolor": (
        "Premium storybook watercolor illustration, soft edges, gentle color washes, "
        "hand-drawn charm, cozy warm palette"
    ),
}

OUT_DIR = Path(__file__).resolve().parent.parent / "assets" / "characters" / "style_candidates"


def generate(style_name: str, style_prompt: str) -> None:
    resp = httpx.post(
        FAL_ENDPOINT,
        headers={"Authorization": f"Key {settings.fal_key}"},
        json={
            "prompt": BASE_PROMPT + style_prompt,
            "aspect_ratio": "9:16",
            "num_images": 1,
        },
        timeout=180.0,
    )
    if resp.status_code != 200:
        print(f"NG {style_name}: HTTP {resp.status_code} {resp.text[:500]}")
        return
    data = resp.json()
    image_url = data["images"][0]["url"]
    img = httpx.get(image_url, timeout=60.0)
    img.raise_for_status()
    out = OUT_DIR / f"{style_name}_v2.png"
    out.write_bytes(img.content)
    print(f"OK {style_name}: {out} ({len(img.content)} bytes)")


def main() -> None:
    if not settings.fal_key:
        sys.exit("FAL_KEY が未設定です")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    targets = sys.argv[1:] or list(STYLES)
    for name in targets:
        generate(name, STYLES[name])


if __name__ == "__main__":
    main()
