"""候補の一括LLM採点（SPEC 7章 Stage 1 + M5-3a 3軸化 + M5-3e ジャンル分類）。

評価軸: キャッチーさ(フック性)・インパクト(意外性/規模)・有用さ(視聴者の実益)。
加重合計をランキングのソートキー(topics.relevance_score)に使う。
M5-3e: 同じ1回の呼び出しでジャンル分類も行う（LLM日次上限を消費しない設計）。
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field

from ..shared.genres import normalize_genre
from ..shared.llm import LLMClient
from .sources import Candidate

# 加重: TikTokはスクロールを止めさせることが最優先のためキャッチーさを最重視
WEIGHT_CATCHY = 0.4
WEIGHT_IMPACT = 0.3
WEIGHT_USEFUL = 0.3

# ジャンル定義（プロンプト共用。shared/genres.py の GENRES と対応）
_GENRE_GUIDE = (
    "hot_news(話題のAIニュース・企業/業界の動向) / "
    "tech_update(Claude・GPT・Gemini等のAI製品/モデルの新機能・アップデート情報) / "
    "workflow_case(個人の作業・業務をAIで効率化した具体的な事例やテクニック) / "
    "paper(AI研究論文・学術的成果) / "
    "work_style(AIによる働き方・雇用・キャリアへの影響) / "
    "vision(AIの将来予測・ビジョン・社会の長期的変化)"
)

SYSTEM_PROMPT = (
    "あなたはAI産業ニュースを扱う縦型ショート動画番組の編集者です。"
    "与えられた候補それぞれを次の3軸で0〜100点採点してください: "
    "(1)catchy: キャッチーさ。冒頭1文でスクロールの指を止められるフックが作れるか"
    "(具体的な数字・意外な事実があるほど高い) "
    "(2)impact: インパクト。業界・社会への影響の大きさや意外性 "
    "(3)useful: 有用さ。一般日本人視聴者の生活・仕事にどれだけ実益があるか。"
    f"さらに各候補を次の6ジャンルのいずれか1つに分類してください: {_GENRE_GUIDE}。"
    "出力は指定されたJSONスキーマに厳密に従うこと。"
    "キーは index・catchy・impact・useful・category の5つのみ。他のキーは絶対に追加しないこと。"
)


class _ScoredIndex(BaseModel):
    index: int
    catchy: float = Field(ge=0, le=100)
    impact: float = Field(ge=0, le=100)
    useful: float = Field(ge=0, le=100)
    category: str | None = None  # 欠落・未知値は normalize_genre でフォールバック


class _ScoringResult(BaseModel):
    scores: list[_ScoredIndex]


@dataclass
class TopicScore:
    catchy: float
    impact: float
    useful: float
    category: str = "hot_news"

    @property
    def total(self) -> float:
        return (
            WEIGHT_CATCHY * self.catchy + WEIGHT_IMPACT * self.impact + WEIGHT_USEFUL * self.useful
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
        '"useful": 60.0, "category": "hot_news"}, ...]}\n'
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
            scores[sc.index] = TopicScore(
                catchy=sc.catchy,
                impact=sc.impact,
                useful=sc.useful,
                category=normalize_genre(sc.category),
            )
    return scores


# --- 旧ストックの後付けジャンル分類（M5-3e移行用） -----------------------------

CLASSIFY_SYSTEM_PROMPT = (
    "あなたはAI産業ニュースを扱う縦型ショート動画番組の編集者です。"
    f"与えられた各ネタを次の6ジャンルのいずれか1つに分類してください: {_GENRE_GUIDE}。"
    "出力は指定されたJSONスキーマに厳密に従うこと。"
    "キーは index・category の2つのみ。他のキーは絶対に追加しないこと。"
)


class _ClassifiedIndex(BaseModel):
    index: int
    category: str


class _ClassifyResult(BaseModel):
    items: list[_ClassifiedIndex]


def classify_topics(llm: LLMClient, entries: list[tuple[str, str | None]]) -> list[str]:
    """(title, summary) の列をジャンル分類し、同じ長さのジャンルID配列を返す。

    採点済みスコアを持つ旧ストック（category=NULL）の移行専用。
    新規収集分は score_candidates が採点と同時に分類するのでこちらは通らない。
    """
    if not entries:
        return []
    listing = "\n".join(
        f"{i}: {title} — {(summary or '')[:120]}" for i, (title, summary) in enumerate(entries)
    )
    user = (
        f"ネタ一覧(index: タイトル — 概要):\n{listing}\n\n"
        '出力形式(JSONのみ): {"items": [{"index": 0, "category": "hot_news"}, ...]}\n'
        "全件ぶん出力すること。"
    )
    result = llm.complete_json(
        purpose="collector_classify",
        system=CLASSIFY_SYSTEM_PROMPT,
        user=user,
        schema=_ClassifyResult,
        max_tokens=2000,
    )
    categories = ["hot_news"] * len(entries)
    for it in result.items:
        if 0 <= it.index < len(entries):
            categories[it.index] = normalize_genre(it.category)
    return categories
