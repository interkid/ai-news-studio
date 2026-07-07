"""M5-1: 透過済みキャラ画像を共通bboxで切り出し、本番ディレクトリへ配置する。

- キャラごとに全状態のアルファbboxの和集合を取り、同じ矩形で切り出す
  (状態間で位置ズレ・スケールズレを起こさないため。レンダラーは高さ760pxへ正規化・
  足元基準線揃えを行うので、切り出し矩形が揃っていれば表情切替でガタつかない)
- mouth_closed は normal のコピー(シルエット完全一致の保証)
"""

from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "characters"
PAD = 12  # bbox余白px

STATES = {
    "fox": ["normal", "surprised", "smug", "worried", "mouth_open"],
    "rabbit": ["normal", "surprised", "curious", "mouth_open"],
}


def finalize(who: str) -> None:
    src_dir = ASSETS / "_work" / f"{who}_cut"
    out_dir = ASSETS / who
    out_dir.mkdir(parents=True, exist_ok=True)

    images = {s: Image.open(src_dir / f"{s}.png").convert("RGBA") for s in STATES[who]}
    sizes = {im.size for im in images.values()}
    if len(sizes) != 1:
        raise SystemExit(f"{who}: 画像サイズが不一致です: {sizes}")

    boxes = [im.getbbox() for im in images.values()]
    left = max(0, min(b[0] for b in boxes) - PAD)
    top = max(0, min(b[1] for b in boxes) - PAD)
    right = min(images["normal"].width, max(b[2] for b in boxes) + PAD)
    bottom = min(images["normal"].height, max(b[3] for b in boxes) + PAD)

    for state, im in images.items():
        cropped = im.crop((left, top, right, bottom))
        cropped.save(out_dir / f"{state}.png")
        print(f"OK {who}/{state}.png {cropped.size}")

    shutil.copyfile(out_dir / "normal.png", out_dir / "mouth_closed.png")
    print(f"OK {who}/mouth_closed.png (normalのコピー)")


if __name__ == "__main__":
    for who in STATES:
        finalize(who)
