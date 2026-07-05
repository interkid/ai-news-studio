"""キャラクター素材・背景素材の解決（manifest.json 経由）。

SPEC 12章: キャラ画像は characters/manifest.json 経由で参照し、
プレースホルダから本番素材へ無改修で差し替え可能にする。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from ..shared.config import ASSETS

CHAR_DIR = ASSETS / "characters"
LAYOUT_DIR = ASSETS / "layout"
MANIFEST = CHAR_DIR / "manifest.json"


@lru_cache(maxsize=1)
def _manifest() -> dict:
    if not MANIFEST.exists():
        raise FileNotFoundError(
            f"{MANIFEST} がありません。scripts/gen_placeholders.py を実行してください。"
        )
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def character_image(speaker: str, key: str) -> Path:
    """speaker(fox|rabbit) の key(normal/surprised/mouth_open ...) の画像パス。

    存在しない表情は normal にフォールバックする。
    """
    m = _manifest()
    if speaker not in m:
        raise KeyError(f"manifest に speaker '{speaker}' がありません")
    entry = m[speaker]
    rel = entry.get(key) or entry["normal"]
    p = CHAR_DIR / rel
    if not p.exists():
        raise FileNotFoundError(f"素材が見つかりません: {p}")
    return p


def emotion_image(speaker: str, emotion: str) -> Path:
    """emotion に対応する表情画像（無ければ normal）。"""
    return character_image(speaker, emotion)


def mouth_image(speaker: str, is_open: bool) -> Path:
    return character_image(speaker, "mouth_open" if is_open else "mouth_closed")


def layout_asset(name: str) -> Path:
    p = LAYOUT_DIR / name
    if not p.exists():
        raise FileNotFoundError(f"レイアウト素材が見つかりません: {p}")
    return p


def background_for_corner(corner: str) -> Path:
    """コーナー別背景（無ければ共通 bg.png）。"""
    cand = LAYOUT_DIR / f"bg_{corner}.png"
    return cand if cand.exists() else layout_asset("bg.png")


def badge_for_corner(corner: str) -> Path | None:
    cand = LAYOUT_DIR / f"badge_{corner}.png"
    return cand if cand.exists() else None
