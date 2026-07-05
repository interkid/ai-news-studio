"""fal.ai FLUX schnell での画像生成（SPEC 2章・7章 Stage 3.5）。

イラスト調スタイルをテンプレートで固定し、1080x1920に収まる構図を指定する。
fal.ai のリクエスト形式は変更されうるため、実キー投入後に最新ドキュメントで
挙動を確認すること。失敗時は呼び出し側(orchestrator)が固定背景へフォールバックする。
"""

from __future__ import annotations

from pathlib import Path

import httpx

from ..shared.config import settings

FAL_ENDPOINT = "https://fal.run/fal-ai/flux/schnell"

STYLE_SUFFIX = (
    "flat vector illustration, cute soft character design, pastel colors, "
    "clean shapes, NOT photorealistic, not photo, vertical composition"
)


class ImageGenUnavailable(RuntimeError):
    pass


def generate_image(prompt: str, out_path: Path) -> None:
    if not settings.fal_key:
        raise ImageGenUnavailable("FAL_KEY が未設定です")

    resp = httpx.post(
        FAL_ENDPOINT,
        headers={"Authorization": f"Key {settings.fal_key}"},
        json={
            "prompt": f"{prompt}, {STYLE_SUFFIX}",
            "image_size": "portrait_16_9",
            "num_images": 1,
        },
        timeout=60.0,
    )
    resp.raise_for_status()
    data = resp.json()
    image_url = data["images"][0]["url"]

    img_resp = httpx.get(image_url, timeout=30.0)
    img_resp.raise_for_status()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(img_resp.content)
