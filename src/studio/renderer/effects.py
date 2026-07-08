"""演出エフェクトライブラリ（SPEC 6章・全動画共通）。

zoom_in / pop_in / shake / flash / slide_in / drop_slam と Ken Burns を関数として提供。
M5演出強化: 冒頭インパクト（drop_slam=デカ文字ドロップ+着地シェイク）と、
emotion 連動の自動選択（speaker_entrance_scale / subtitle_entrance）を追加。
タイミング計算は純粋関数（slam_kinematics 等）に分離しユニットテスト対象とする。

MoviePy 2.x API（with_position / resized / with_start / with_opacity）で実装。
scale は resized(func) が元サイズに func(t) を掛ける挙動を利用し、
中心を固定するために with_position を時間関数で与える。
"""

from __future__ import annotations

import math
from collections.abc import Callable

from moviepy import ColorClip
from moviepy.Clip import Clip

from . import layout

Center = tuple[float, float]


def _lerp(a: float, b: float, u: float) -> float:
    return a + (b - a) * u


def _centered_scale(clip: Clip, center: Center, scale_fn: Callable[[float], float]) -> Clip:
    """clip を scale_fn(t) で拡縮しつつ center を固定する。"""
    cx, cy = center
    base_w, base_h = clip.w, clip.h
    scaled = clip.resized(scale_fn)

    def pos(t: float) -> tuple[float, float]:
        s = scale_fn(t)
        return (cx - base_w * s / 2, cy - base_h * s / 2)

    return scaled.with_position(pos)


def scale_bounce_fn(
    dur: float, s0: float = 0.6, s1: float = 1.15, s2: float = 1.0
) -> Callable[[float], float]:
    """登場バウンス：0→dur で s0→s1→s2。以降は s2 固定。"""

    def f(t: float) -> float:
        if t >= dur:
            return s2
        u = t / dur
        if u < 0.6:
            return _lerp(s0, s1, u / 0.6)
        return _lerp(s1, s2, (u - 0.6) / 0.4)

    return f


def zoom_in(clip: Clip, center: Center, dur: float = 0.4, s0: float = 0.6, s1: float = 1.0) -> Clip:
    def sf(t: float) -> float:
        return s1 if t >= dur else _lerp(s0, s1, t / dur)

    return _centered_scale(clip, center, sf)


def pop_in(clip: Clip, center: Center, dur: float = layout.TELOP_BOUNCE_SEC) -> Clip:
    return _centered_scale(clip, center, scale_bounce_fn(dur))


def shake(
    clip: Clip, center: Center, dur: float = 0.3, amp: float = 18.0, freq: float = 28.0
) -> Clip:
    cx, cy = center
    hw, hh = clip.w / 2, clip.h / 2

    def pos(t: float) -> tuple[float, float]:
        if t < dur:
            dx = amp * math.sin(2 * math.pi * freq * t) * (1 - t / dur)
            return (cx - hw + dx, cy - hh)
        return (cx - hw, cy - hh)

    return clip.with_position(pos)


def slide_in(
    clip: Clip, center: Center, dur: float = 0.3, from_dx: float = -80.0, from_dy: float = 0.0
) -> Clip:
    cx, cy = center
    hw, hh = clip.w / 2, clip.h / 2

    def pos(t: float) -> tuple[float, float]:
        u = min(t / dur, 1.0)
        ox = _lerp(from_dx, 0.0, u)
        oy = _lerp(from_dy, 0.0, u)
        return (cx - hw + ox, cy - hh + oy)

    return clip.with_position(pos)


def flash(
    at: float, size: tuple[int, int] = layout.CANVAS, frames: int = 2, opacity: float = 0.85
) -> Clip:
    """白フラッシュ（2フレーム）。CompositeVideoClip の最前面に重ねる想定。"""
    dur = frames / layout.FPS
    return (
        ColorClip(size=size, color=(255, 255, 255))
        .with_duration(dur)
        .with_start(at)
        .with_opacity(opacity)
    )


# ---- M5演出強化: 冒頭インパクト ---------------------------------------------


def slam_kinematics(
    t: float,
    drop_dur: float = layout.HOOK_DROP_SEC,
    from_dy: float = layout.HOOK_DROP_FROM_DY,
    from_scale: float = layout.HOOK_DROP_FROM_SCALE,
    shake_amp: float = layout.HOOK_SHAKE_AMP,
    shake_dur: float = layout.HOOK_SHAKE_SEC,
    shake_freq: float = 22.0,
) -> tuple[float, float, float]:
    """デカ文字ドロップの (dx, dy, scale) を返す純粋関数。

    0〜drop_dur: 上方から加速落下しつつ from_scale→1.0 に縮小（デカ文字→着地）。
    着地後 shake_dur: 減衰シェイク。以降は静止 (0, 0, 1.0)。
    """
    if t < drop_dur:
        u = t / drop_dur
        e = u * u  # ease-in（自由落下風の加速）
        return (0.0, from_dy * (1.0 - e), _lerp(from_scale, 1.0, e))
    ts = t - drop_dur
    if ts < shake_dur:
        damp = 1.0 - ts / shake_dur
        dx = shake_amp * math.sin(2 * math.pi * shake_freq * ts) * damp
        dy = 0.4 * shake_amp * math.sin(2 * math.pi * shake_freq * 1.3 * ts) * damp
        return (dx, dy, 1.0)
    return (0.0, 0.0, 1.0)


def drop_slam(
    clip: Clip,
    center: Center,
    drop_dur: float = layout.HOOK_DROP_SEC,
    from_dy: float = layout.HOOK_DROP_FROM_DY,
    from_scale: float = layout.HOOK_DROP_FROM_SCALE,
) -> Clip:
    """冒頭インパクト演出：デカ文字が落下して着地シェイク（フック既定）。

    着地の瞬間（t=drop_dur）に flash() を重ねる想定。
    """
    cx, cy = center
    base_w, base_h = clip.w, clip.h

    def sf(t: float) -> float:
        return slam_kinematics(t, drop_dur, from_dy, from_scale)[2]

    scaled = clip.resized(sf)

    def pos(t: float) -> tuple[float, float]:
        dx, dy, s = slam_kinematics(t, drop_dur, from_dy, from_scale)
        return (cx - base_w * s / 2 + dx, cy - base_h * s / 2 + dy)

    return scaled.with_position(pos)


# ---- M5演出強化: 感情連動の自動選択 ------------------------------------------


def speaker_entrance_scale(
    emotion: str,
    t_rel: float,
    base: float = layout.SPEAKER_SCALE_ACTIVE,
    dur: float = layout.SPEAKER_ENTRANCE_SEC,
) -> float:
    """発話開始からの経過時間 t_rel における話者キャラのスケール（純粋関数）。

    surprised: 大きくバウンス（base×0.9→×1.13→base）
    curious:   小さくバウンス（base×0.95→×1.06→base）
    smug:      ゆっくりせり上がる（base×0.93→base）
    それ以外:   base 固定（従来挙動）
    """
    if t_rel >= dur:
        return base
    u = t_rel / dur
    if emotion == "surprised":
        peak = base * 1.13
        if u < 0.5:
            return _lerp(base * 0.90, peak, u / 0.5)
        return _lerp(peak, base, (u - 0.5) / 0.5)
    if emotion == "curious":
        peak = base * 1.06
        if u < 0.5:
            return _lerp(base * 0.95, peak, u / 0.5)
        return _lerp(peak, base, (u - 0.5) / 0.5)
    if emotion == "smug":
        return _lerp(base * 0.93, base, u)
    return base


def subtitle_effect_name(emotion: str) -> str:
    """emotion → 字幕登場エフェクト名（純粋関数・テスト対象）。"""
    return {
        "surprised": "pop_in",
        "curious": "pop_in",
        "smug": "slide_in_right",
        "worried": "rise_in",
    }.get(emotion, "slide_in_left")


def subtitle_entrance(clip: Clip, center: Center, emotion: str) -> Clip:
    """emotion に応じた字幕の登場演出を適用する。"""
    name = subtitle_effect_name(emotion)
    if name == "pop_in":
        return pop_in(clip, center, dur=0.3)
    if name == "slide_in_right":
        return slide_in(clip, center, dur=0.3, from_dx=80.0)
    if name == "rise_in":
        return slide_in(clip, center, dur=0.35, from_dx=0.0, from_dy=50.0)
    return slide_in(clip, center, dur=0.25, from_dx=-60.0)


def ken_burns(
    clip: Clip,
    duration: float,
    size: tuple[int, int] = layout.CANVAS,
    z0: float = layout.KEN_BURNS_START,
    z1: float = layout.KEN_BURNS_END,
    pan_px: float = layout.KEN_BURNS_PAN_PX,
) -> Clip:
    """背景/B-roll のゆっくりズーム＋軽いパン。clip は size を覆う寸法である前提。"""
    w, h = size
    base_w, base_h = clip.w, clip.h

    def sf(t: float) -> float:
        return _lerp(z0, z1, min(t / duration, 1.0))

    scaled = clip.resized(sf)

    def pos(t: float) -> tuple[float, float]:
        u = min(t / duration, 1.0)
        px = _lerp(-pan_px / 2, pan_px / 2, u)
        s = sf(t)
        return (w / 2 - base_w * s / 2 + px, h / 2 - base_h * s / 2)

    return scaled.with_position(pos).with_duration(duration)
