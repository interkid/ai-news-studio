"""SQLite接続・マイグレーション・薄いリポジトリ層（SPEC 4章）。

ORM不使用。sqlite3標準ライブラリ + テーブルごとの薄い関数群。
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY,
    source_url TEXT NOT NULL,
    source_type TEXT NOT NULL,        -- arxiv | rss | hn | manual
    title TEXT NOT NULL,
    summary TEXT,
    collected_at TEXT NOT NULL,
    relevance_score REAL,             -- 3軸の加重合計（ランキングのソートキー）
    category TEXT,                    -- ジャンル(shared/genres.py の GENRES)。NULL=未分類(旧データ)
    status TEXT DEFAULT 'new'         -- new(ストック) | scripted | skipped | expired
);

CREATE TABLE IF NOT EXISTS scripts (
    id INTEGER PRIMARY KEY,
    topic_id INTEGER REFERENCES topics(id),
    corner TEXT NOT NULL,
    script_json TEXT NOT NULL,
    fact_check_passed INTEGER,
    fact_check_notes TEXT,
    quality_score REAL,
    status TEXT DEFAULT 'draft'       -- draft | rejected | selected
);

CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY,
    script_id INTEGER REFERENCES scripts(id),
    file_path TEXT,
    r2_url TEXT,
    duration_sec REAL,
    approval_status TEXT DEFAULT 'pending',
    rejection_reason TEXT,
    tiktok_publish_id TEXT,
    posted_at TEXT
);

CREATE TABLE IF NOT EXISTS metrics (
    video_id INTEGER REFERENCES videos(id),
    fetched_at TEXT,
    views INTEGER, likes INTEGER, comments INTEGER, shares INTEGER,
    PRIMARY KEY (video_id, fetched_at)
);

CREATE TABLE IF NOT EXISTS prompt_insights (
    id INTEGER PRIMARY KEY,
    week TEXT,
    insight TEXT NOT NULL,
    active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS llm_usage (
    called_at TEXT, purpose TEXT, model TEXT,
    input_tokens INTEGER, output_tokens INTEGER, est_cost_jpy REAL
);

CREATE TABLE IF NOT EXISTS oauth_tokens (
    provider TEXT PRIMARY KEY,       -- 例: 'tiktok'
    access_token TEXT,
    refresh_token TEXT,
    expires_at TEXT                  -- access_tokenの有効期限(UTC ISO)
);
"""


# 既存DBへ追加するtopicsの3軸スコア列（M5-3a ネタストック化）。
# relevance_score は加重合計として引き続きソートキーに使う。
_TOPIC_SCORE_COLUMNS = ("catchy_score", "impact_score", "useful_score")

# ネタストックの鮮度規則（M5-3a）: 収集後 GRACE 日は満点、以降1日ごとに DECAY 点減点、
# EXPIRE 日を超えた 'new' は自動失効させる（AIニュースの鮮度優先）。
STOCK_GRACE_DAYS = 3
STOCK_DECAY_PER_DAY = 2.0
STOCK_EXPIRE_DAYS = 30

# 鮮度減衰後の実効スコア（julianday はISO8601文字列を直接受け付ける）
_EFFECTIVE_SCORE_SQL = (
    f"relevance_score - {STOCK_DECAY_PER_DAY} * "
    f"MAX(0, julianday('now') - julianday(collected_at) - {STOCK_GRACE_DAYS})"
)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    """薄いリポジトリ層。1接続を使い回す想定（CLI一回実行の寿命）。"""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        """既存DBに後付け列を足す（CREATE TABLE IF NOT EXISTS では既存DBに反映されないため）。"""
        existing = {r["name"] for r in self.conn.execute("PRAGMA table_info(topics)")}
        for col in _TOPIC_SCORE_COLUMNS:
            if col not in existing:
                self.conn.execute(f"ALTER TABLE topics ADD COLUMN {col} REAL")
        if "category" not in existing:  # M5-3e ジャンル週間ローテ
            self.conn.execute("ALTER TABLE topics ADD COLUMN category TEXT")

    def close(self) -> None:
        self.conn.close()

    # --- topics ---------------------------------------------------------

    def insert_topic(
        self,
        *,
        source_url: str,
        source_type: str,
        title: str,
        summary: str | None,
        relevance_score: float | None = None,
        catchy_score: float | None = None,
        impact_score: float | None = None,
        useful_score: float | None = None,
        category: str | None = None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO topics (source_url, source_type, title, summary, collected_at, "
            "relevance_score, catchy_score, impact_score, useful_score, category) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                source_url,
                source_type,
                title,
                summary,
                now_iso(),
                relevance_score,
                catchy_score,
                impact_score,
                useful_score,
                category,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def topic_url_known(self, source_url: str) -> bool:
        """同一URLのネタが(状態を問わず)既にあるか。日次収集の重複ストックを防ぐ。"""
        row = self.conn.execute(
            "SELECT 1 FROM topics WHERE source_url = ? LIMIT 1", (source_url,)
        ).fetchone()
        return row is not None

    def expire_stale_topics(self) -> int:
        """鮮度切れ(STOCK_EXPIRE_DAYS超)の 'new' を失効させ、件数を返す。"""
        cur = self.conn.execute(
            "UPDATE topics SET status = 'expired' WHERE status = 'new' "
            f"AND julianday('now') - julianday(collected_at) > {STOCK_EXPIRE_DAYS}"
        )
        self.conn.commit()
        return cur.rowcount

    def stock_ranking(self, limit: int) -> list[sqlite3.Row]:
        """ストック('new')を鮮度減衰後の実効スコア降順で返す。

        行には effective_score 列が付く。ランキング配信・当日ネタ選定の両方で使う。
        """
        return self.conn.execute(
            f"SELECT *, {_EFFECTIVE_SCORE_SQL} AS effective_score FROM topics "
            "WHERE status = 'new' AND relevance_score IS NOT NULL "
            "ORDER BY effective_score DESC LIMIT ?",
            (limit,),
        ).fetchall()

    def stock_ranking_by_category(self, category: str, limit: int) -> list[sqlite3.Row]:
        """指定ジャンルのストックを実効スコア降順で返す（曜日ローテの当日枠選抜用）。"""
        return self.conn.execute(
            f"SELECT *, {_EFFECTIVE_SCORE_SQL} AS effective_score FROM topics "
            "WHERE status = 'new' AND relevance_score IS NOT NULL AND category = ? "
            "ORDER BY effective_score DESC LIMIT ?",
            (category, limit),
        ).fetchall()

    def topics_missing_category(self, limit: int = 200) -> list[sqlite3.Row]:
        """ジャンル未分類のストック（M5-3e導入前の旧データ）。collector実行時に後付け分類する。"""
        return self.conn.execute(
            "SELECT id, title, summary FROM topics "
            "WHERE status = 'new' AND category IS NULL LIMIT ?",
            (limit,),
        ).fetchall()

    def set_topic_category(self, topic_id: int, category: str) -> None:
        self.conn.execute("UPDATE topics SET category = ? WHERE id = ?", (category, topic_id))
        self.conn.commit()

    def set_topic_status(self, topic_id: int, status: str) -> None:
        self.conn.execute("UPDATE topics SET status = ? WHERE id = ?", (status, topic_id))
        self.conn.commit()

    def get_topic(self, topic_id: int) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM topics WHERE id = ?", (topic_id,)).fetchone()
        if row is None:
            raise KeyError(f"topic id={topic_id} が見つかりません")
        return row

    # --- scripts ---------------------------------------------------------

    def insert_script(
        self,
        *,
        topic_id: int,
        corner: str,
        script_json: str,
        fact_check_passed: bool | None = None,
        fact_check_notes: str | None = None,
        quality_score: float | None = None,
        status: str = "draft",
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO scripts (topic_id, corner, script_json, fact_check_passed, "
            "fact_check_notes, quality_score, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                topic_id,
                corner,
                script_json,
                None if fact_check_passed is None else int(fact_check_passed),
                fact_check_notes,
                quality_score,
                status,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_script(
        self,
        script_id: int,
        *,
        fact_check_passed: bool | None = None,
        fact_check_notes: str | None = None,
        quality_score: float | None = None,
        status: str | None = None,
    ) -> None:
        fields, values = [], []
        if fact_check_passed is not None:
            fields.append("fact_check_passed = ?")
            values.append(int(fact_check_passed))
        if fact_check_notes is not None:
            fields.append("fact_check_notes = ?")
            values.append(fact_check_notes)
        if quality_score is not None:
            fields.append("quality_score = ?")
            values.append(quality_score)
        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if not fields:
            return
        values.append(script_id)
        self.conn.execute(f"UPDATE scripts SET {', '.join(fields)} WHERE id = ?", values)
        self.conn.commit()

    def get_script(self, script_id: int) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM scripts WHERE id = ?", (script_id,)).fetchone()
        if row is None:
            raise KeyError(f"script id={script_id} が見つかりません")
        return row

    # --- videos ---------------------------------------------------------

    def insert_video(
        self, *, script_id: int, file_path: str | None = None, duration_sec: float | None = None
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO videos (script_id, file_path, duration_sec) VALUES (?, ?, ?)",
            (script_id, file_path, duration_sec),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_video_by_script_id(self, script_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM videos WHERE script_id = ?", (script_id,)
        ).fetchone()

    def set_video_r2_url(self, script_id: int, r2_url: str) -> None:
        self.conn.execute("UPDATE videos SET r2_url = ? WHERE script_id = ?", (r2_url, script_id))
        self.conn.commit()

    def set_video_approval_status(
        self, script_id: int, status: str, rejection_reason: str | None = None
    ) -> None:
        self.conn.execute(
            "UPDATE videos SET approval_status = ?, "
            "rejection_reason = COALESCE(?, rejection_reason) WHERE script_id = ?",
            (status, rejection_reason, script_id),
        )
        self.conn.commit()

    def set_video_published(self, script_id: int, tiktok_publish_id: str) -> None:
        self.conn.execute(
            "UPDATE videos SET tiktok_publish_id = ?, posted_at = ? WHERE script_id = ?",
            (tiktok_publish_id, now_iso(), script_id),
        )
        self.conn.commit()

    def videos_awaiting_publish(self) -> list[sqlite3.Row]:
        """承認結果がまだ確定していない、またはTikTok送信がまだの動画。"""
        return self.conn.execute(
            "SELECT * FROM videos WHERE posted_at IS NULL AND approval_status != 'rejected'"
        ).fetchall()

    # --- oauth_tokens --------------------------------------------------------

    def get_oauth_token(self, provider: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM oauth_tokens WHERE provider = ?", (provider,)
        ).fetchone()

    def set_oauth_token(
        self, provider: str, *, access_token: str, refresh_token: str, expires_at: str
    ) -> None:
        self.conn.execute(
            "INSERT INTO oauth_tokens (provider, access_token, refresh_token, expires_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(provider) DO UPDATE SET "
            "access_token = excluded.access_token, refresh_token = excluded.refresh_token, "
            "expires_at = excluded.expires_at",
            (provider, access_token, refresh_token, expires_at),
        )
        self.conn.commit()

    # --- prompt_insights ---------------------------------------------------

    def active_insights(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT insight FROM prompt_insights WHERE active = 1 ORDER BY id"
        ).fetchall()
        return [r["insight"] for r in rows]

    # --- llm_usage ---------------------------------------------------------

    def log_llm_usage(
        self,
        *,
        purpose: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        est_cost_jpy: float,
    ) -> None:
        self.conn.execute(
            "INSERT INTO llm_usage (called_at, purpose, model, input_tokens, output_tokens, "
            "est_cost_jpy) VALUES (?, ?, ?, ?, ?, ?)",
            (now_iso(), purpose, model, input_tokens, output_tokens, est_cost_jpy),
        )
        self.conn.commit()

    def llm_calls_today(self) -> int:
        today = datetime.now(UTC).date().isoformat()
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM llm_usage WHERE substr(called_at, 1, 10) = ?", (today,)
        ).fetchone()
        return int(row["n"])

    def images_today(self) -> int:
        # imagegen も llm_usage に purpose='imagegen' として計上する運用にする
        today = datetime.now(UTC).date().isoformat()
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM llm_usage WHERE substr(called_at, 1, 10) = ? "
            "AND purpose = 'imagegen'",
            (today,),
        ).fetchone()
        return int(row["n"])


@contextmanager
def open_db(path: Path):
    db = Database(path)
    try:
        yield db
    finally:
        db.close()
