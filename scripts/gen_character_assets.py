"""M5-1: 選定画風(ピクサー調3DCG)の本番キャラ素材を Nano Banana Pro 編集モードで生成する。

使い方:
    uv run python scripts/gen_character_assets.py base       # ベースキャラ2枚
    uv run python scripts/gen_character_assets.py expressions # ベースから表情差分
    uv run python scripts/gen_character_assets.py all

生成物は assets/characters/_work/ に保存する（透過化・配置は別ステップ）。
表情差分は「ポーズ・体・照明を一切変えず顔だけ変える」指示で同一性を保つ。
"""

from __future__ import annotations

import base64
import io
import sys
from pathlib import Path

import httpx
from PIL import Image

from studio.shared.config import settings

EDIT_ENDPOINT = "https://fal.run/fal-ai/nano-banana-pro/edit"

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "characters"
STYLE_REF = ASSETS / "style_candidates" / "pixar_3dcg_v2.png"
WORK = ASSETS / "_work"

KEEP = (
    "Keep the exact same character design, Pixar-style 3DCG look, colors, outfit, "
    "body pose, arm position, leg position, lighting and plain flat light background. "
)
ONLY_FACE = "Change ONLY the face. Do not change the pose, body outline or anything else. "

BASE_PROMPTS = {
    # 解説役: きつね→「キャラメル色の垂れ耳うさぎ」へ変更(2026-07-07 ユーザ決定。
    # ペア構成の見直し。内部スピーカーID/ディレクトリ名は fox のまま)
    "fox": (
        "Using the same Pixar-style 3DCG look as this image, draw a completely "
        "original caramel-brown LOP-EARED rabbit character (both ears folded down, "
        "clearly different from an upright-eared white rabbit), wearing the small "
        "round glasses, red bow tie and navy vest from the fox in the reference. "
        "Full body, standing upright facing the viewer, both arms relaxed at the "
        "sides, calm gentle smile with mouth closed, feet clearly visible with a "
        "small margin below, centered, plain flat light gray background, no other "
        "characters, no text, NOT a fox."
    ),
    "rabbit": (
        "Extract only the rabbit character from this image and redraw it alone: "
        "same character design and same Pixar-style 3DCG look (cream-white rabbit, "
        "yellow neckerchief). Full body, standing upright facing the viewer, both "
        "arms relaxed at the sides, gentle happy smile with mouth closed, feet "
        "clearly visible with a small margin below, centered, plain flat light gray "
        "background, no other characters, no text."
    ),
}

EXPRESSION_PROMPTS: dict[str, dict[str, str]] = {
    "fox": {
        "surprised": "New face: wide open eyes, raised eyebrows, mouth open in shock.",
        "smug": (
            "New face: confident smug grin, half-lidded eyes, one eyebrow raised, mouth closed."
        ),
        "worried": (
            "New face: worried troubled expression, slanted eyebrows, small frown, mouth closed."
        ),
        "mouth_open": (
            "New face: same calm expression but mouth wide open as if talking mid-sentence."
        ),
    },
    "rabbit": {
        "surprised": "New face: wide open eyes, raised eyebrows, mouth open in shock.",
        "curious": (
            "New face: sparkling curious eyes, slightly raised eyebrows, "
            "small open mouth as if asking a question."
        ),
        "mouth_open": (
            "New face: same happy expression but mouth wide open as if talking mid-sentence."
        ),
    },
}


def to_data_uri(path: Path, max_w: int = 1024) -> str:
    img = Image.open(path).convert("RGB")
    if img.width > max_w:
        img = img.resize((max_w, int(img.height * max_w / img.width)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def edit(prompt: str, ref: Path, out: Path) -> bool:
    resp = httpx.post(
        EDIT_ENDPOINT,
        headers={"Authorization": f"Key {settings.fal_key}"},
        json={"prompt": prompt, "image_urls": [to_data_uri(ref)], "num_images": 1},
        timeout=240.0,
    )
    if resp.status_code != 200:
        print(f"NG {out.name}: HTTP {resp.status_code} {resp.text[:300]}")
        return False
    img = httpx.get(resp.json()["images"][0]["url"], timeout=60.0)
    img.raise_for_status()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(img.content)
    print(f"OK {out.relative_to(ASSETS)} ({len(img.content)} bytes)")
    return True


def gen_base() -> None:
    for who, prompt in BASE_PROMPTS.items():
        edit(prompt, STYLE_REF, WORK / who / "normal.png")


def gen_expressions() -> None:
    for who, table in EXPRESSION_PROMPTS.items():
        base = WORK / who / "normal.png"
        if not base.exists():
            sys.exit(f"{base} がありません。先に base を実行してください。")
        for state, face in table.items():
            edit(KEEP + ONLY_FACE + face, base, WORK / who / f"{state}.png")


def main() -> None:
    if not settings.fal_key:
        sys.exit("FAL_KEY が未設定です")
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode in ("base", "all"):
        gen_base()
    if mode in ("expressions", "all"):
        gen_expressions()


if __name__ == "__main__":
    main()
