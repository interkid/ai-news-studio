"""候補の一括LLM採点（SPEC 7章 Stage 1 + M5-3a 3軸化）。

評価軸: キャッチーさ(フック性)・インパクト(意外性/規模)・有用さ(視聴者の実益)。
加重合計をランキングのソートキー(topics.relevance_score)に使う。
1回の呼び出しでまとめて採点する（コスト最適化）。
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field

from ..shared.llm import LLMClient
from .sources import Candidate

# 加重: TikTokはスクロールを止めさせることが最優先のためキャッチーさを最重視
WEIGHT_CATCHY = 0.4
WEIGHT_IMPACT = 0.3
WEIGHT_USEFUL = 0.3

SYSTEM_PROMPT = (
    "あなたはAI産業ニュースを扱う縦型ショート動画番組の編集者です。"
    "与えられた候補それぞれを次の3軸で0〜100点採点してください: "
    "(1)catchy: キャッチーさ。冒頭1文でスクロールの指を止められるフックが作れるか"
    "(具体的な数字・意外な事実があるほど高い) "
    "(2)impact: インパクト。業界・社会への影響の大きさや意外性 "
    "(3)useful: 有用さ。一般日本人視聴者の生活・仕事にどれだけ実益があるか。"
    "出力は指定されたJSONスキーマに厳密に従うこと。"
    "キーは index・catchy・impact・useful の4つのみ。他のキーは絶対に追加しないこと。"
)


class _ScoredIndex(BaseModel):
    index: int
    catchy: float = Field(ge=0, le=100)
    impact: float = Field(ge=0, le=100)
    useful: float = Field(ge=0, le=100)


class _ScoringResult(BaseModel):
    scores: list[_ScoredIndex]


@dataclass
class TopicScore:
    catchy: float
    impact: float
    useful: float

    @property
    def total(self) -> float:
        return (
            WEIGHT_CATCHY * self.catchy
            + WEIGHT_IMPACT * self.impact
            + WEIGHT_USEFUL * self.useful
        )


def score_candidates(llm: LLMClient, candidates: list[Candidate]) -> list[TopicScore]:
    """candidates と同じ長さのスコア配列を返す（未採点は全軸0点）。"""
    if not candidates:
        return []
    listing = "\n".join(
        f"{i}: {c.title} — {(c.summary or '')[:120]}" for i, c in enumerate(candidates)
    )
    user = (
        f"候補一覧(index: タイトル — 概要):\n{listing}\n\n"
        '出力形式(JSONのみ): {"scores": [{"index": 0, "catchy": 80.0, "impact": 70.0, '
        '"useful": 60.0}, ...]}\n'
        "全候補ぶん出力すること。"
    )
    result = llm.complete_json(
        purpose="collector_score",
        system=SYSTEM_PROMPT,
        user=user,
        schema=_ScoringResult,
        max_tokens=3000,
    )
    scores = [TopicScore(0.0, 0.0, 0.0)] * len(candidates)
    for sc in result.scores:
        if 0 <= sc.index < len(candidates):
            scores[sc.index] = TopicScore(catchy=sc.catchy, impact=sc.impact, useful=sc.useful)
    return scores
