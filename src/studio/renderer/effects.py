"""演出エフェクトライブラリ（SPEC 6章・全動画共通）。

zoom_in / pop_in / shake / flash / slide_in と Ken Burns を関数として提供。
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
