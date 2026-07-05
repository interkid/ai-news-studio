"""台本1本ぶんのTTS実行（SPEC 7章 Stage 3）。

VOICEVOXが起動していれば実音声を生成し実測秒数をLineに記録する。
未起動時（ローカルdry-run等）は文字数からの概算秒数のみ付与し、
wav_pathはNoneのままにする——`studio pipeline --dry-run` をVOICEVOX無しで
最後まで通すためのフォールバック（ユーザ方針: コード先行＋モックで確認）。
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..shared.models import Line, Script
from . import voicevox

logger = logging.getLogger(__name__)

# 概算用の日本語発話速度（文字/秒）。VOICEVOX未起動時のみ使うラフな推定値。
FALLBACK_CHARS_PER_SEC = 6.5
FALLBACK_MIN_DURATION_SEC = 0.8


def _fallback_duration(text: str) -> float:
    return max(FALLBACK_MIN_DURATION_SEC, len(text) / FALLBACK_CHARS_PER_SEC)


def synthesize_script(script: Script, out_dir: Path) -> Script:
    """duration_sec(+可能ならwav_path)を埋めた Script のコピーを返す。"""
    available = voicevox.is_available()
    new_lines: list[Line] = []
    used_real_audio = False

    for i, line in enumerate(script.exchanges):
        if available:
            wav_path = out_dir / f"line_{i}_{line.speaker}.wav"
            try:
                voicevox.synthesize(line.text, line.speaker, wav_path)
                dur = voicevox.wav_duration_sec(wav_path)
                new_lines.append(
                    line.model_copy(update={"wav_path": str(wav_path), "duration_sec": dur})
                )
                used_real_audio = True
                continue
            except Exception:
                logger.warning("VOICEVOX合成に失敗(概算尺で代替): line=%d", i, exc_info=True)
        new_lines.append(line.model_copy(update={"duration_sec": _fallback_duration(line.text)}))

    updated = script.model_copy(update={"exchanges": new_lines})
    if used_real_audio:
        updated = _add_voicevox_credit(updated)
    return updated


def _add_voicevox_credit(script: Script) -> Script:
    if "VOICEVOX" in script.caption:
        return script
    fox_name = voicevox.speaker_display_name(voicevox.speaker_id_for("fox"))
    rabbit_name = voicevox.speaker_display_name(voicevox.speaker_id_for("rabbit"))
    if not fox_name and not rabbit_name:
        return script
    names = "・".join(n for n in (fox_name, rabbit_name) if n)
    return script.model_copy(update={"caption": f"{script.caption} VOICEVOX:{names}"})
