"""レンダリングのマジックナンバーを一元管理（SPEC 6章）。

タイミング・座標・演出パラメータの定数はすべてここに置く。
"""

from __future__ import annotations

# --- キャンバス ---
WIDTH = 1080
HEIGHT = 1920
FPS = 30
CANVAS = (WIDTH, HEIGHT)

# --- タイミング ---
GAP_SEC = 0.25  # セリフ間ギャップ
TEMPO_MAX_STATIC_SEC = 2.5  # これを超える無変化区間があれば自動ズームを挿入
TEMPO_MIN_CHANGE_SEC = 1.5  # 目安：1.5〜2.5秒ごとに変化
MOUTH_FPS = 8  # 口パクの開閉切替レート
HOOK_INTRO_SEC = 0.5  # 冒頭フックテロップのズームイン尺
CROSSFADE_SEC = 0.2  # B-roll切替クロスフェード

# --- Ken Burns ---
KEN_BURNS_START = 1.0
KEN_BURNS_END = 1.08
KEN_BURNS_PAN_PX = 24  # 全編でのゆるいパン量(px)

# --- キャラクター配置（画面下部） ---
FOX_CENTER_X = int(WIDTH * 0.28)
RABBIT_CENTER_X = int(WIDTH * 0.72)
CHAR_BOTTOM_Y = int(HEIGHT * 0.99)  # 足元の基準線
CHAR_TARGET_H = 760  # 素材を配置時にこの高さへ正規化
SPEAKER_SCALE_ACTIVE = 1.15  # 発話中の話者
SPEAKER_SCALE_IDLE = 1.0

# --- テロップ（中央） ---
TELOP_CENTER_Y = int(HEIGHT * 0.30)
TELOP_BOUNCE_SEC = 0.4  # 登場バウンス尺（scale 0.6→1.15→1.0）
TELOP_FONT_SIZE = 92
HOOK_FONT_SIZE = 104

# --- 字幕（キャラ上） ---
SUBTITLE_CENTER_Y = int(HEIGHT * 0.66)
SUBTITLE_FONT_SIZE = 60
SUBTITLE_MAX_LINES = 2
SUBTITLE_STROKE_PX = 4
SUBTITLE_MAX_WIDTH_PX = int(WIDTH * 0.86)

# --- 上部ロゴ／バッジ ---
LOGO_TOP_Y = 48
BADGE_TOP_Y = 160

# --- 色（話者アクセント） ---
FOX_ACCENT = (255, 138, 44)  # オレンジ
RABBIT_ACCENT = (120, 190, 255)  # 水色
SUBTITLE_FILL = (255, 255, 255)
SUBTITLE_STROKE = (20, 20, 24)

# --- 音声 ---
BGM_GAIN_DB = -18.0
SFX_SURPRISE = "pico"  # emotion=surprised の頭に「ピコン」


def accent_for(speaker: str) -> tuple[int, int, int]:
    return FOX_ACCENT if speaker == "fox" else RABBIT_ACCENT


def center_x_for(speaker: str) -> int:
    return FOX_CENTER_X if speaker == "fox" else RABBIT_CENTER_X
