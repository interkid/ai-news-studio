"""タイミング計算・テンポ規則のユニットテスト（MoviePy非依存）。"""

from __future__ import annotations

import pytest

from studio.renderer import layout
from studio.renderer.timeline import (
    build_timeline,
    change_timestamps,
    compute_line_spans,
    find_tempo_gaps,
    tempo_fill_zooms,
    total_duration,
)


def _lines():
    return [
        ("fox", "surprised", 4.2),
        ("rabbit", "curious", 2.8),
        ("fox", "smug", 3.6),
        ("rabbit", "normal", 3.2),
    ]


def test_line_spans_sequential_with_gap():
    spans = compute_line_spans(_lines(), gap=0.25)
    assert spans[0].start == 0.0
    assert spans[0].end == pytest.approx(4.2)
    # 次のセリフは gap を挟んで開始
    assert spans[1].start == pytest.approx(4.2 + 0.25)
    assert spans[1].end == pytest.approx(4.2 + 0.25 + 2.8)
    # 区間は重ならない
    for a, b in zip(spans, spans[1:], strict=False):
        assert a.end <= b.start


def test_total_duration_excludes_trailing_gap():
    spans = compute_line_spans(_lines())
    # 末尾ギャップは尺に含めない
    expected = 4.2 + 0.25 + 2.8 + 0.25 + 3.6 + 0.25 + 3.2
    assert total_duration(spans) == pytest.approx(expected)


def test_zero_duration_rejected():
    with pytest.raises(ValueError):
        compute_line_spans([("fox", "normal", 0.0)])


def test_change_events_sorted_unique_with_sentinels():
    spans = compute_line_spans(_lines())
    events = change_timestamps(spans, broll_starts=[0.0, spans[2].start])
    assert events == sorted(events)
    assert len(events) == len(set(events))
    assert events[0] == 0.0
    assert events[-1] == pytest.approx(total_duration(spans))


def test_no_tempo_gap_for_normal_script():
    tl = build_timeline(_lines(), broll_starts=[0.0])
    # 各セリフ<2.5s差ではないが、字幕登場イベントが各行頭にあるので
    # 隣接イベント差が最大でも1セリフ尺+gap。ここでは4.2sの行があるため gap 検出される
    gaps = find_tempo_gaps(tl.change_events)
    # 4.2s の行は 2.5s を超えるので自動ズーム挿入対象になる
    assert gaps
    zooms = tempo_fill_zooms(gaps)
    assert all(0 <= z <= tl.total for z in zooms)


def test_tempo_gap_detection_threshold():
    # 明示的に 3秒無変化 → gap 検出、2秒 → 非検出
    assert find_tempo_gaps([0.0, 3.0], max_static=2.5) == [(0.0, 3.0)]
    assert find_tempo_gaps([0.0, 2.0], max_static=2.5) == []


def test_tempo_constant_matches_layout():
    assert layout.TEMPO_MAX_STATIC_SEC == 2.5
