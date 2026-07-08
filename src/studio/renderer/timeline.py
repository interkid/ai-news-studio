"""タイミング計算とテンポ規則（純Python・MoviePy非依存＝ユニットテスト対象）。

SPEC 6章:
- タイミングは Line.duration_sec の実測値から組む（セリフ間ギャップ 0.25秒）。
- テンポ規則: 画面のどこかが 1.5〜2.5秒ごとに必ず変化。無変化 2.5秒超は自動ズーム挿入。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import layout


@dataclass(frozen=True)
class LineSpan:
    """1セリフの時間区間。"""

    index: int
    speaker: str
    emotion: str
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Timeline:
    spans: list[LineSpan]
    total: float
    change_events: list[float] = field(default_factory=list)


def compute_line_spans(
    lines: list[tuple[str, str, float]], gap: float = layout.GAP_SEC
) -> list[LineSpan]:
    """(speaker, emotion, duration) の列から各セリフの [start,end] を組む。

    先頭は t=0 開始、以降は gap を挟んで直列配置。
    """
    spans: list[LineSpan] = []
    t = 0.0
    for i, (speaker, emotion, dur) in enumerate(lines):
        if dur <= 0:
            raise ValueError(f"line[{i}] の duration_sec は正の実測値が必要: {dur}")
        spans.append(LineSpan(i, speaker, emotion, t, t + dur))
        t += dur + gap
    return spans


def total_duration(spans: list[LineSpan], gap: float = layout.GAP_SEC) -> float:
    if not spans:
        return 0.0
    # 最後のセリフ末尾までが尺（末尾ギャップは含めない）
    return spans[-1].end


def change_timestamps(spans: list[LineSpan], broll_starts: list[float]) -> list[float]:
    """「画面が変化する」イベント時刻の集合（昇順・重複除去）。

    話者切替・各セリフ字幕の登場・B-roll切替を変化とみなす。
    t=0 と 総尺 も番兵として含める。
    """
    events: set[float] = {0.0}
    prev_speaker: str | None = None
    for s in spans:
        events.add(round(s.start, 3))  # 字幕登場＝変化
        if prev_speaker is not None and s.speaker != prev_speaker:
            events.add(round(s.start, 3))  # 話者切替（同時刻でも意味づけ）
        prev_speaker = s.speaker
    for b in broll_starts:
        events.add(round(b, 3))
    events.add(round(total_duration(spans), 3))
    return sorted(events)


def find_tempo_gaps(
    events: list[float], max_static: float = layout.TEMPO_MAX_STATIC_SEC
) -> list[tuple[float, float]]:
    """連続する変化イベント間で max_static を超える無変化区間を返す。

    返り値は (gap_start, gap_end) のリスト。空なら規則を満たしている。
    """
    gaps: list[tuple[float, float]] = []
    for a, b in zip(events, events[1:], strict=False):
        if (b - a) > max_static:
            gaps.append((a, b))
    return gaps


def tempo_fill_zooms(gaps: list[tuple[float, float]]) -> list[float]:
    """無変化区間の中点＝自動ズームを挿入すべき時刻。"""
    return [round((a + b) / 2, 3) for a, b in gaps]


def build_timeline(lines: list[tuple[str, str, float]], broll_starts: list[float]) -> Timeline:
    spans = compute_line_spans(lines)
    total = total_duration(spans)
    events = change_timestamps(spans, broll_starts)
    return Timeline(spans=spans, total=total, change_events=events)
