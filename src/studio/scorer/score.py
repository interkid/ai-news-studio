"""投稿前LLM採点で1案に絞る（SPEC 7章 Stage 5）。

評価観点: 「フック強度」「中学生が1回で理解できるか」「オチの引き」「ビート構成」。
最高得点の1案を selected、他は rejected(理由保存)にする。
TTS・挿絵・レンダはこの後、selected の1案のみに対して実行する（実行順の注意）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from ..shared.db import Database
from ..shared.llm import LLMClient
from ..shared.models import Script

SCORER_SYSTEM = (
    "あなたは縦型ショート動画の採用可否を決める編集長です。台本候補それぞれを0〜100点の"
    "単一スコアで採点してください。評価観点(内部で考慮するだけでよく、内訳をJSONに"
    "含めないこと): (1)フック強度: hookと第一声が具体的な事実・数字でスクロールの指を"
    "止めるか(抽象的な煽りだけなら減点) (2)中学生が1回で理解できるか "
    "(3)オチの引き: 最後のセリフが視聴者自身への示唆・問いかけで終わり、コメントや保存を"
    "したくなるか (4)ビート構成: つかみ→リアクション→核心→オチの流れが成立しているか。"
    "出力は指定されたJSONスキーマに厳密に従うこと。"
    "キーは index・quality_score・reason の3つのみ。他のキーは絶対に追加しないこと。"
)

# 実際のLLM応答で quality_score の代わりに使われがちな別名（フォールバック用）
_SCORE_ALIASES = ("quality_score", "total", "score", "overall", "overall_score")


class _ScoredScript(BaseModel):
    index: int
    quality_score: float = Field(ge=0, le=100)
    reason: str

    @model_validator(mode="before")
    @classmethod
    def _accept_alias_keys(cls, data):
        if isinstance(data, dict) and "quality_score" not in data:
            for alias in _SCORE_ALIASES:
                if alias in data:
                    data = {**data, "quality_score": data[alias]}
                    break
        if isinstance(data, dict) and "reason" not in data:
            data = {**data, "reason": ""}
        return data


class _ScoringResult(BaseModel):
    scores: list[_ScoredScript]


def _format_script(i: int, s: Script) -> str:
    lines = "\n".join(f"  {ln.speaker}: {ln.text}" for ln in s.exchanges)
    return f"[{i}] corner={s.corner} hook={s.hook!r}\n{lines}"


def score_scripts(llm: LLMClient, scripts: list[Script]) -> list[tuple[float, str]]:
    """scripts と同じ長さの (quality_score, reason) を返す。"""
    if not scripts:
        return []
    listing = "\n\n".join(_format_script(i, s) for i, s in enumerate(scripts))
    user = (
        f"候補一覧:\n{listing}\n\n"
        '出力形式(JSONのみ): {"scores": [{"index": 0, "quality_score": 85.0, '
        '"reason": "簡潔な日本語理由"}, ...]}\n全候補ぶん出力すること。'
    )
    result = llm.complete_json(
        purpose="scorer", system=SCORER_SYSTEM, user=user, schema=_ScoringResult, max_tokens=1500
    )
    out = [(0.0, "")] * len(scripts)
    for sc in result.scores:
        if 0 <= sc.index < len(scripts):
            out[sc.index] = (sc.quality_score, sc.reason)
    return out


def append_note(db: Database, script_id: int, note: str) -> None:
    row = db.get_script(script_id)
    existing = row["fact_check_notes"]
    combined = f"{existing}; scorer: {note}" if existing else f"scorer: {note}"
    db.update_script(script_id, fact_check_notes=combined)


def select_script(db: Database, llm: LLMClient, script_ids: list[int]) -> int | None:
    """script_ids(fact_check_passed)を採点し、最高得点をselectedにしてそのidを返す。

    script_ids が空なら None（当日は投稿しない、を呼び出し側が判断する）。
    """
    if not script_ids:
        return None
    rows = [db.get_script(sid) for sid in script_ids]
    scripts = [Script.model_validate_json(r["script_json"]) for r in rows]
    scored = score_scripts(llm, scripts)
    best_i = max(range(len(scored)), key=lambda i: scored[i][0])
    for i, sid in enumerate(script_ids):
        score, reason = scored[i]
        if i == best_i:
            db.update_script(sid, quality_score=score, status="selected")
            append_note(db, sid, reason)
        else:
            db.update_script(sid, quality_score=score, status="rejected")
            append_note(db, sid, reason)
    return script_ids[best_i]
