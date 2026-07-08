"""Anthropic呼び出しの集約層（SPEC 2章・12章）。

- 呼び出しは必ずここを経由し、日次上限(DAILY_LLM_CALL_LIMIT)超過時は例外で停止する。
- llm_usage にコストを必ず記録する。
- ANTHROPIC_API_KEY 未設定時は MockProvider にフォールバックし、
  `studio pipeline --dry-run` 等をキー無しで動作確認できるようにする
  （ユーザ方針: コード先行＋モックで確認）。

コスト概算(est_cost_jpy)は config.py の単価を用いる。単価は目安であり、
実際の予算判断の前に https://www.anthropic.com/pricing の最新値で必ず確認すること。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel

from .config import settings
from .db import Database

MODEL_HAIKU = "claude-haiku-4-5-20251001"

T = TypeVar("T", bound=BaseModel)


class DailyLimitExceeded(RuntimeError):
    pass


class LLMCallError(RuntimeError):
    pass


@dataclass
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int


class LLMProvider(Protocol):
    def complete(
        self, *, system: str, user: str, temperature: float, max_tokens: int
    ) -> LLMResult: ...


class AnthropicProvider:
    """本物のAnthropic API呼び出し（`pipeline` extra が要る）。"""

    def __init__(self, api_key: str, model: str = MODEL_HAIKU) -> None:
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def complete(
        self, *, system: str, user: str, temperature: float = 1.0, max_tokens: int = 1024
    ) -> LLMResult:
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        return LLMResult(
            text=text,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
        )


class MockProvider:
    """キー無し／テスト用のモック。purpose毎に登録した応答を返す。

    未登録の purpose で呼ばれたら明示的に落とす（サイレントな不正動作を避ける）。
    """

    def __init__(self, responses: dict[str, Callable[[str], str] | str]) -> None:
        self._responses = responses
        self.calls: list[str] = []

    def complete_for(
        self, purpose: str, *, system: str, user: str, temperature: float, max_tokens: int
    ) -> LLMResult:
        self.calls.append(purpose)
        if purpose not in self._responses:
            raise LLMCallError(
                f"MockProvider: purpose '{purpose}' の応答が未登録です。テスト/dry-run側で"
                "responses に追加してください。"
            )
        resp = self._responses[purpose]
        text = resp(user) if callable(resp) else resp
        # モックはコスト計上ゼロ（実APIを叩いていないため）
        return LLMResult(text=text, input_tokens=0, output_tokens=0)


class LLMClient:
    """日次上限チェック＋コストログを一元化するラッパー。

    real provider は purpose を知らないため、呼び出し側が complete(purpose=...) するたびに
    MockProvider へは purpose を渡し、AnthropicProvider へは渡さない形で吸収する。
    """

    def __init__(
        self, db: Database, provider: LLMProvider | MockProvider, model: str = MODEL_HAIKU
    ) -> None:
        self.db = db
        self.provider = provider
        self.model = model

    def complete(
        self,
        *,
        purpose: str,
        system: str,
        user: str,
        temperature: float = 1.0,
        max_tokens: int = 1024,
    ) -> str:
        if self.db.llm_calls_today() >= settings.daily_llm_call_limit:
            raise DailyLimitExceeded(
                f"本日のLLM呼び出し上限({settings.daily_llm_call_limit}回)に達しました。"
                "DAILY_LLM_CALL_LIMIT を変更するか翌日に再実行してください。"
            )
        if isinstance(self.provider, MockProvider):
            result = self.provider.complete_for(
                purpose, system=system, user=user, temperature=temperature, max_tokens=max_tokens
            )
        else:
            result = self.provider.complete(
                system=system, user=user, temperature=temperature, max_tokens=max_tokens
            )
        cost = _estimate_cost_jpy(self.model, result.input_tokens, result.output_tokens)
        self.db.log_llm_usage(
            purpose=purpose,
            model=self.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            est_cost_jpy=cost,
        )
        return result.text

    def complete_json(
        self,
        *,
        purpose: str,
        system: str,
        user: str,
        schema: type[T],
        temperature: float = 1.0,
        max_tokens: int = 1024,
    ) -> T:
        text = self.complete(
            purpose=purpose,
            system=system,
            user=user,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        payload = _extract_json(text)
        return schema.model_validate(payload)


def _extract_json(text: str) -> dict:
    """LLM応答からJSONオブジェクトを取り出す（コードフェンス混入に耐える）。"""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```")[1]
        if t.startswith("json"):
            t = t[4:]
    try:
        return json.loads(t)
    except json.JSONDecodeError as e:
        raise LLMCallError(f"LLM応答をJSONとして解析できません: {text[:200]!r}") from e


def _estimate_cost_jpy(model: str, input_tokens: int, output_tokens: int) -> float:
    rate = settings.llm_cost_jpy_per_1k.get(model)
    if rate is None:
        return 0.0
    return (input_tokens / 1000) * rate["input"] + (output_tokens / 1000) * rate["output"]


def _extract_field(user_text: str, label: str) -> str | None:
    m = re.search(rf"{label}:\s*(\S+)", user_text)
    return m.group(1) if m else None


def _dry_run_collector_score(user_text: str) -> str:
    """候補一覧(各行 'index: title — summary')から、順位に応じた固定3軸スコアを返す。

    category はジャンル一覧を巡回するダミー（曜日ローテの配線確認用）。
    """
    from .genres import GENRES

    indices = re.findall(r"^(\d+):", user_text, re.MULTILINE)
    scores = [
        {
            "index": int(i),
            "catchy": max(45.0, 95.0 - int(i) * 3),
            "impact": max(45.0, 90.0 - int(i) * 3),
            "useful": max(45.0, 85.0 - int(i) * 3),
            "category": GENRES[int(i) % len(GENRES)],
        }
        for i in indices
    ]
    return json.dumps({"scores": scores})


def _dry_run_collector_classify(user_text: str) -> str:
    """旧ストック後付け分類のダミー（全件 hot_news 扱い）。"""
    indices = re.findall(r"^(\d+):", user_text, re.MULTILINE)
    items = [{"index": int(i), "category": "hot_news"} for i in indices]
    return json.dumps({"items": items})


def _dry_run_script_json(user_text: str) -> str:
    """本物のLLMを使わず、構造的に妥当な台本を1件返す（内容はダミー）。

    実際のトピック内容は反映しない——dry-runは「配線が最後まで通るか」の確認用であり、
    ファクト検証も本関数と対で常にpassするダミーにしているため内容不整合は生じない。
    """
    source_url = _extract_field(user_text, "ソースURL") or "https://example.com/"
    payload = {
        "corner": "paper",
        "hook": "精度94%の衝撃",
        "exchanges": [
            {
                "speaker": "fox",
                "text": "精度94%、AIが医療診断を大きく変えます",
                "emotion": "surprised",
            },
            {"speaker": "rabbit", "text": "えっ、お医者さんいらずになるの？", "emotion": "curious"},
            {"speaker": "fox", "text": "画像診断で専門医に並ぶ正答率が出たんだ", "emotion": "smug"},
            {
                "speaker": "rabbit",
                "text": "あなたの健康にも直結する大事な話だね",
                "emotion": "normal",
            },
        ],
        "brolls": [
            {
                "prompt": "a friendly cartoon AI analyzing a chart on a screen",
                "caption_ja": "dry-run用ダミー挿絵",
                "start_line": 0,
            }
        ],
        "caption": "AI関連の最新研究を解説(dry-run)。※AI生成/出典はコメント欄",
        "source_url": source_url,
        "fact_claims": ["画像診断でAIが専門医に並ぶ正答率を示した", "報告された精度は94%"],
        "visual_keyword": "AI最新研究",
    }
    return json.dumps(payload, ensure_ascii=False)


def _dry_run_factcheck(_user_text: str) -> str:
    return json.dumps({"passed": True, "notes": "dry-run: ファクト検証はモックです"})


def _dry_run_scorer(user_text: str) -> str:
    indices = re.findall(r"^\[(\d+)\]", user_text, re.MULTILINE)
    scores = [
        {
            "index": int(i),
            "quality_score": max(40.0, 90.0 - int(i) * 5),
            "reason": "dry-run固定スコア",
        }
        for i in indices
    ]
    return json.dumps({"scores": scores})


def _dry_run_inspect(_user_text: str) -> str:
    return json.dumps({"ok": True, "reason": "dry-run", "revised_prompt": None})


def _dry_run_responses() -> dict[str, Callable[[str], str]]:
    """ANTHROPIC_API_KEY未設定時、`studio pipeline --dry-run` を最後まで通すための
    決め打ち応答集。内容は構造チェック用のダミーであり実トピックの要約ではない。
    """
    return {
        "collector_score": _dry_run_collector_score,
        "collector_classify": _dry_run_collector_classify,
        "scriptwriter_generate": _dry_run_script_json,
        "scriptwriter_factcheck": _dry_run_factcheck,
        "scorer": _dry_run_scorer,
        "imagegen_inspect": _dry_run_inspect,
    }


def build_llm_client(db: Database) -> LLMClient:
    """設定に応じて本物/モックを選ぶファクトリ。"""
    if settings.anthropic_api_key:
        return LLMClient(db, AnthropicProvider(settings.anthropic_api_key))
    return LLMClient(db, MockProvider(responses=_dry_run_responses()))
