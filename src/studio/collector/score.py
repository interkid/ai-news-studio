"""候補の一括LLM採点（SPEC 7章 Stage 1）。

評価観点: 「一般日本人視聴者へのインパクト」「一文で言える意外性」「生活・仕事への影響」。
1回の呼び出しでまとめて採点する（コスト最適化）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from ..shared.llm import LLMClient
from .sources import Candidate

SYSTEM_PROMPT = (
    "あなたはAI産業ニュースを扱う縦型ショート動画番組の編集者です。"
    "与えられた候補それぞれを0〜100点の単一スコアで採点してください。"
    "評価観点(内部で考慮するだけでよく、内訳をJSONに含めないこと): "
    "(1)一般日本人視聴者へのインパクト (2)一文で言える意外性 (3)生活・仕事への影響。"
    "出力は指定されたJSONスキーマに厳密に従うこと。"
    'キーは index と relevance_score の2つのみ。他のキー(impact/novelty/total等)は'
    "絶対に追加しないこと。"
)

# 実際のLLM応答で relevance_score の代わりに使われがちな別名（フォールバック用）
_SCORE_ALIASES = ("relevance_score", "total", "score", "overall", "overall_score")


class _ScoredIndex(BaseModel):
    index: int
    relevance_score: float = Field(ge=0, le=100)

    @model_validator(mode="before")
    @classmethod
    def _accept_alias_keys(cls, data):
        if isinstance(data, dict) and "relevance_score" not in data:
            for alias in _SCORE_ALIASES:
                if alias in data:
                    data = {**data, "relevance_score": data[alias]}
                    break
        return data


class _ScoringResult(BaseModel):
    scores: list[_ScoredIndex]


def score_candidates(llm: LLMClient, candidates: list[Candidate]) -> list[float]:
    """candidates と同じ長さのスコア配列を返す（未採点は0点）。"""
    if not candidates:
        return []
    listing = "\n".join(
        f"{i}: {c.title} — {(c.summary or '')[:120]}" for i, c in enumerate(candidates)
    )
    user = (
        f"候補一覧(index: タイトル — 概要):\n{listing}\n\n"
        '出力形式(JSONのみ): {"scores": [{"index": 0, "relevance_score": 87.0}, ...]}\n'
        "全候補ぶん出力すること。"
    )
    result = llm.complete_json(
        purpose="collector_score",
        system=SYSTEM_PROMPT,
        user=user,
        schema=_ScoringResult,
        max_tokens=2048,
    )
    scores = [0.0] * len(candidates)
    for sc in result.scores:
        if 0 <= sc.index < len(candidates):
            scores[sc.index] = sc.relevance_score
    return scores
