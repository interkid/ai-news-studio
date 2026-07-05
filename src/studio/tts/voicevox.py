"""VOICEVOX Engine 呼び出し（SPEC 7章 Stage 3）。

audio_query → synthesis でセリフごとにwavを生成する。ローカルはスタンドアロン版
(run.exe等)、CIはDockerサービスとして `VOICEVOX_URL` に起動している前提。
"""

from __future__ import annotations

import wave
from pathlib import Path

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ..shared.config import settings

_retry = retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))


def is_available(timeout: float = 2.0) -> bool:
    try:
        resp = httpx.get(f"{settings.voicevox_url}/version", timeout=timeout)
        return resp.status_code == 200
    except Exception:
        return False


def speaker_id_for(speaker: str) -> int:
    return settings.voicevox_speaker_fox if speaker == "fox" else settings.voicevox_speaker_rabbit


@_retry
def synthesize(text: str, speaker: str, out_path: Path) -> None:
    speaker_id = speaker_id_for(speaker)
    base = settings.voicevox_url
    q = httpx.post(
        f"{base}/audio_query", params={"text": text, "speaker": speaker_id}, timeout=15.0
    )
    q.raise_for_status()
    query = q.json()
    synth = httpx.post(
        f"{base}/synthesis", params={"speaker": speaker_id}, json=query, timeout=30.0
    )
    synth.raise_for_status()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(synth.content)


def wav_duration_sec(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def speaker_display_name(speaker_id: int) -> str | None:
    """`/speakers` から実際のキャラ名を取得する。取得できなければ None（推測しない）。"""
    try:
        resp = httpx.get(f"{settings.voicevox_url}/speakers", timeout=5.0)
        resp.raise_for_status()
        for character in resp.json():
            for style in character.get("styles", []):
                if style.get("id") == speaker_id:
                    return f"{character.get('name')}({style.get('name')})"
    except Exception:
        return None
    return None
