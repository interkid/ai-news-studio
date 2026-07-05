"""ファクト検証（SPEC 7章 Stage 2）。

source_url 本文を取得し、fact_claims / セリフと照合する。
「原文にない主張」「原文にない最上級・断定・恐怖煽り表現」はreject対象。
外部fetchはtenacityでリトライ+タイムアウトし、取得できなければreject
（検証できない台本は作らない）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape

import httpx
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential

from ..shared.llm import LLMCallError, LLMClient
from ..shared.models import Script

_retry = retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))

_TAG_BLOCK_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.I | re.S)
_ANY_TAG_RE = re.compile(r"<[^>]+>")

FACT_CHECK_SYSTEM = (
    "あなたは動画台本のファクトチェッカーです。原文(ソース本文抜粋)と台本のhook・セリフ・"
    "fact_claimsを照合し、(1)原文に書かれていない主張が含まれていないか (2)原文にない"
    "最上級・断定・恐怖煽り表現(例: 人類終了、○○消滅等)が含まれていないか、を判定してください。"
    'いずれかに該当すれば passed=false。出力はJSONのみ: {"passed": bool, "notes": "日本語で簡潔な理由"}'
)


@dataclass
class FactCheckResult:
    passed: bool
    notes: str


class _FactCheckJson(BaseModel):
    passed: bool
    notes: str


def _strip_html(raw_html: str) -> str:
    cleaned = _TAG_BLOCK_RE.sub(" ", raw_html)
    cleaned = _ANY_TAG_RE.sub(" ", cleaned)
    cleaned = unescape(cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def fetch_source_text(url: str, max_chars: int = 4000) -> str:
    resp = _retry(httpx.get)(
        url,
        timeout=20.0,
        follow_redirects=True,
        headers={"User-Agent": "ai-news-studio/0.1 (+fact-check)"},
    )
    resp.raise_for_status()
    return _strip_html(resp.text)[:max_chars]


def fact_check(llm: LLMClient, script: Script) -> FactCheckResult:
    try:
        source_text = fetch_source_text(str(script.source_url))
    except Exception as e:
        return FactCheckResult(passed=False, notes=f"ソース本文の取得に失敗: {e}")

    lines = "\n".join(f"{ln.speaker}: {ln.text}" for ln in script.exchanges)
    claims = "\n".join(f"- {c}" for c in script.fact_claims)
    user = (
        f"原文(冒頭抜粋):\n{source_text}\n\n"
        f"台本のhook: {script.hook}\n"
        f"台本のセリフ:\n{lines}\n\n"
        f"fact_claims:\n{claims}\n\n"
        "上記を照合し判定してください。"
    )
    try:
        result = llm.complete_json(
            purpose="scriptwriter_factcheck",
            system=FACT_CHECK_SYSTEM,
            user=user,
            schema=_FactCheckJson,
            temperature=0.0,
            max_tokens=400,
        )
    except LLMCallError as e:
        return FactCheckResult(passed=False, notes=f"検証応答の解析に失敗: {e}")
    return FactCheckResult(passed=result.passed, notes=result.notes)
