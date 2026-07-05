"""環境変数設定（pydantic-settings, SPEC 10章）。

M1 では render に関わる値のみ実際に使う。外部連携キーは未設定でも
import が失敗しないよう全て Optional にしてある（M2以降で利用）。
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# リポジトリルート（src/studio/shared/config.py から3つ上）
ROOT = Path(__file__).resolve().parents[3]
ASSETS = ROOT / "assets"
DATA = ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- LLM / 画像生成（M2以降）---
    anthropic_api_key: str | None = None
    fal_key: str | None = None
    daily_llm_call_limit: int = 30
    image_daily_limit: int = 5
    # コスト概算の単価(円/1000トークン)。目安値であり実際の予算判断前に
    # https://www.anthropic.com/pricing の最新値で必ず確認すること。
    llm_cost_jpy_per_1k: dict[str, dict[str, float]] = Field(
        default_factory=lambda: {
            "claude-haiku-4-5-20251001": {"input": 0.15, "output": 0.75},
        }
    )

    # --- collector（M2以降）---
    # RSS収集元。フィードURLは変更されることがあるため、取得失敗時は当該フィードのみ
    # skipする(collector側で担保)。運用しながら随時見直すこと。
    rss_feeds: list[str] = Field(
        default_factory=lambda: [
            "https://openai.com/news/rss.xml",
            "https://deepmind.google/blog/rss.xml",
            "https://ainow.ai/feed/",
        ]
    )

    # --- VOICEVOX（M2以降・任意）---
    voicevox_url: str = "http://localhost:50021"
    # 話者ID。きつね=低め落ち着き、うさぎ=高め素朴になる話者を選ぶこと。
    # `GET {voicevox_url}/speakers` で一覧・実際の名前を確認してから確定するのが確実
    # （デフォルト値は暫定。運用開始前に必ず自分の耳で聴いて選び直すこと）。
    voicevox_speaker_fox: int = 11
    voicevox_speaker_rabbit: int = 46

    # --- LINE / TikTok / R2 / CF（M3以降）---
    line_channel_access_token: str | None = None
    line_channel_secret: str | None = None
    line_admin_user_id: str | None = None
    tiktok_client_key: str | None = None
    tiktok_client_secret: str | None = None
    tiktok_refresh_token: str | None = None
    # TikTokに渡すOAuthのredirect_uri。Login Kitはhttps必須でlocalhostを直接登録できないため、
    # GitHub Pages上の静的な橋渡しページ(docs/oauth-callback.html)を経由し、そこから
    # tiktok_local_callback_port のローカルサーバへJSリダイレクトする(manual.md 6章参照)。
    tiktok_redirect_uri: str = "https://interkid.github.io/ai-news-studio/oauth-callback.html"
    # `studio auth tiktok` が一時的に待ち受けるローカルポート。上記ページのJSと値を合わせること。
    tiktok_local_callback_port: int = 8921
    r2_account_id: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    r2_bucket: str | None = None
    cf_kv_namespace_id: str | None = None
    cf_api_token: str | None = None

    # --- レンダリング ---
    font_path: str | None = None  # 未指定なら assets/fonts → システムCJKにフォールバック

    db_path: Path = Field(default=DATA / "studio.db")


settings = Settings()
