"""M5演出強化の純粋関数テスト（MoviePy非依存）。

drop_slam のタイミング計算（slam_kinematics）と、emotion 連動の
自動選択（speaker_entrance_scale / subtitle_effect_name）を検証する。
"""

from __future__ import annotations

import pytest

from studio.renderer import layout
from studio.renderer.effects import (
    slam_kinematics,
    speaker_entrance_scale,
    subtitle_effect_name,
)

# Line.emotion の Literal と揃える（models.py 変更時はここも更新）
ALL_EMOTIONS = ["normal", "surprised", "smug", "worried", "curious"]


# ---- slam_kinematics（デカ文字ドロップ） ------------------------------------


def test_slam_starts_above_and_big():
    dx, dy, s = slam_kinematics(0.0)
    assert dx == 0.0
    assert dy == pytest.approx(layout.HOOK_DROP_FROM_DY)  # 画面上方から
    assert s == pytest.approx(layout.HOOK_DROP_FROM_SCALE)  # デカ文字


def test_slam_lands_at_center_scale_1():
    _, dy, s = slam_kinematics(layout.HOOK_DROP_SEC)
    # 着地の瞬間: 位置ずれなし（シェイクは t=着地 で sin(0)=0）・等倍
    assert dy == pytest.approx(0.0, abs=1e-6)
    assert s == pytest.approx(1.0)


def test_slam_fall_is_monotonic_and_accelerating():
    ts = [i * layout.HOOK_DROP_SEC / 10 for i in range(11)]
    dys = [slam_kinematics(t)[1] for t in ts]
    # 落下中 dy は単調に 0 へ近づく（負→0）
    assert all(a <= b for a, b in zip(dys, dys[1:], strict=False))
    # ease-in: 前半の移動量 < 後半の移動量
    assert (dys[5] - dys[0]) < (dys[10] - dys[5])


def test_slam_shake_decays_then_settles():
    t_mid = layout.HOOK_DROP_SEC + layout.HOOK_SHAKE_SEC * 0.25
    dx_mid, _, s_mid = slam_kinematics(t_mid)
    assert s_mid == pytest.approx(1.0)  # シェイク中も等倍
    assert abs(dx_mid) <= layout.HOOK_SHAKE_AMP  # 振幅は上限内
    # シェイク終了後は完全静止
    t_after = layout.HOOK_DROP_SEC + layout.HOOK_SHAKE_SEC + 0.01
    assert slam_kinematics(t_after) == (0.0, 0.0, 1.0)


# ---- speaker_entrance_scale（感情連動の話者スケール） ------------------------


def test_entrance_scale_settles_to_active_scale():
    for emo in ALL_EMOTIONS:
        s = speaker_entrance_scale(emo, layout.SPEAKER_ENTRANCE_SEC + 0.1)
        assert s == pytest.approx(layout.SPEAKER_SCALE_ACTIVE)


def test_entrance_scale_surprised_overshoots():
    base = layout.SPEAKER_SCALE_ACTIVE
    peak_t = layout.SPEAKER_ENTRANCE_SEC * 0.5
    assert speaker_entrance_scale("surprised", peak_t) > base
    # curious も膨らむが surprised より控えめ
    assert speaker_entrance_scale("curious", peak_t) < speaker_entrance_scale("surprised", peak_t)


def test_entrance_scale_smug_rises_monotonically():
    base = layout.SPEAKER_SCALE_ACTIVE
    ts = [i * layout.SPEAKER_ENTRANCE_SEC / 8 for i in range(9)]
    scales = [speaker_entrance_scale("smug", t) for t in ts]
    assert all(a <= b for a, b in zip(scales, scales[1:], strict=False))
    assert scales[0] < base  # 小さめから
    assert scales[-1] == pytest.approx(base)


def test_entrance_scale_normal_is_constant():
    for t in (0.0, 0.1, 0.2, 1.0):
        assert speaker_entrance_scale("normal", t) == pytest.approx(layout.SPEAKER_SCALE_ACTIVE)


# ---- subtitle_effect_name（感情→字幕エフェクトの対応表） ---------------------


def test_subtitle_effect_covers_all_emotions():
    known = {"pop_in", "slide_in_right", "rise_in", "slide_in_left"}
    for emo in ALL_EMOTIONS:
        assert subtitle_effect_name(emo) in known


def test_subtitle_effect_mapping():
    assert subtitle_effect_name("surprised") == "pop_in"
    assert subtitle_effect_name("smug") == "slide_in_right"
    assert subtitle_effect_name("worried") == "rise_in"
    assert subtitle_effect_name("normal") == "slide_in_left"  # 従来挙動を維持
    assert subtitle_effect_name("unknown") == "slide_in_left"  # 未知はフォールバック
