"""TikTok Content Posting API — OAuth + inbox(下書き)チャンクアップロード(SPEC 8章)。

「Upload to TikTok」(inbox下書き)方式のみを扱う。審査不要・SELF_ONLY制限もない
（Direct Postは使わない。manual.md 6章参照）。

トークンは `oauth_tokens` テーブル(SQLite)に永続化する。refresh_tokenは使うたびに
ローテーションされる仕様のため、都度新しい値で上書きする。`.env`/GitHub Secretsの
TIKTOK_REFRESH_TOKENは、DBにまだ何も無い初回(`studio auth tiktok`実行直後や、
新しい環境へのDB引き継ぎ時)のシードとしてのみ使う。
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import httpx

from ..shared.config import settings
from ..shared.db import Database

API_BASE = "https://open.tiktokapis.com"
AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = f"{API_BASE}/v2/oauth/token/"
INIT_UPLOAD_URL = f"{API_BASE}/v2/post/publish/inbox/video/init/"
STATUS_FETCH_URL = f"{API_BASE}/v2/post/publish/status/fetch/"

SCOPES = "user.info.basic,video.upload,video.list"

# チャンクアップロード方式のPUT先が受け付けるチャンクサイズの上限。これ以下なら
# 1チャンクで送る(TikTok推奨: 動画サイズが上限以下ならtotal_chunk_count=1でよい)。
MAX_SINGLE_CHUNK_BYTES = 64 * 1024 * 1024
DEFAULT_CHUNK_BYTES = 10 * 1024 * 1024

# access_tokenの実際の有効期限より早め(5分前)にリフレッシュしてマージンを持つ。
EXPIRY_BUFFER_SEC = 300


class TikTokNotConfigured(RuntimeError):
    pass


class TikTokUploadFailed(RuntimeError):
    pass


def _require_client_credentials() -> tuple[str, str]:
    if not (settings.tiktok_client_key and settings.tiktok_client_secret):
        raise TikTokNotConfigured("TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET が未設定です")
    return settings.tiktok_client_key, settings.tiktok_client_secret


def build_authorize_url(state: str) -> str:
    client_key, _ = _require_client_credentials()
    params = {
        "client_key": client_key,
        "scope": SCOPES,
        "response_type": "code",
        "redirect_uri": settings.tiktok_redirect_uri,
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code_for_token(code: str) -> dict:
    client_key, client_secret = _require_client_credentials()
    resp = httpx.post(
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": settings.tiktok_redirect_uri,
        },
        timeout=15.0,
    )
    resp.raise_for_status()
    return resp.json()


def refresh_access_token(refresh_token: str) -> dict:
    client_key, client_secret = _require_client_credentials()
    resp = httpx.post(
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=15.0,
    )
    resp.raise_for_status()
    return resp.json()


def save_token(db: Database, token: dict) -> str:
    expires_at = (datetime.now(UTC) + timedelta(seconds=token["expires_in"])).isoformat()
    db.set_oauth_token(
        "tiktok",
        access_token=token["access_token"],
        refresh_token=token["refresh_token"],
        expires_at=expires_at,
    )
    return token["access_token"]


def get_access_token(db: Database) -> str:
    """有効なaccess_tokenを返す。DBに無い/期限切れならrefresh_tokenで更新する。"""
    row = db.get_oauth_token("tiktok")
    if row is not None:
        expires_at = datetime.fromisoformat(row["expires_at"])
        if datetime.now(UTC) < expires_at - timedelta(seconds=EXPIRY_BUFFER_SEC):
            return str(row["access_token"])
        refresh_token = row["refresh_token"]
    else:
        if not settings.tiktok_refresh_token:
            raise TikTokNotConfigured(
                "TIKTOK_REFRESH_TOKEN が未設定です。初回は `studio auth tiktok` を実行してください"
            )
        refresh_token = settings.tiktok_refresh_token
    token = refresh_access_token(refresh_token)
    return save_token(db, token)


def _chunk_ranges(total_size: int, chunk_size: int = DEFAULT_CHUNK_BYTES) -> list[tuple[int, int]]:
    """バイト範囲(start, end inclusive)のリストを返す。小さい動画は1チャンクにする。"""
    if total_size <= MAX_SINGLE_CHUNK_BYTES:
        return [(0, total_size - 1)]
    ranges = []
    start = 0
    while start < total_size:
        end = min(start + chunk_size, total_size) - 1
        ranges.append((start, end))
        start = end + 1
    return ranges


def init_inbox_upload(
    access_token: str, video_size: int, ranges: list[tuple[int, int]]
) -> tuple[str, str]:
    chunk_size = ranges[0][1] - ranges[0][0] + 1
    resp = httpx.post(
        INIT_UPLOAD_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        json={
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": video_size,
                "chunk_size": chunk_size,
                "total_chunk_count": len(ranges),
            }
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    data = resp.json()["data"]
    return data["publish_id"], data["upload_url"]


def upload_chunks(
    upload_url: str, file_path: Path, ranges: list[tuple[int, int]], total_size: int
) -> None:
    with file_path.open("rb") as f:
        for start, end in ranges:
            f.seek(start)
            chunk = f.read(end - start + 1)
            resp = httpx.put(
                upload_url,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {start}-{end}/{total_size}",
                },
                content=chunk,
                timeout=60.0,
            )
            resp.raise_for_status()


def fetch_status(access_token: str, publish_id: str) -> dict:
    resp = httpx.post(
        STATUS_FETCH_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        json={"publish_id": publish_id},
        timeout=15.0,
    )
    resp.raise_for_status()
    return resp.json()["data"]


_TERMINAL_SUCCESS = {"SEND_TO_USER_INBOX"}
_TERMINAL_FAILURE = {"FAILED"}


def wait_for_completion(
    access_token: str, publish_id: str, *, max_attempts: int = 10, interval_sec: float = 10.0
) -> dict:
    """status/fetch を成功/失敗の終端状態になるまでポーリングする。

    レート制限(6req/分)に対して余裕を持つ間隔にしてある。
    """
    for _ in range(max_attempts):
        data = fetch_status(access_token, publish_id)
        status = data.get("status")
        if status in _TERMINAL_SUCCESS:
            return data
        if status in _TERMINAL_FAILURE:
            raise TikTokUploadFailed(str(data.get("fail_reason") or "unknown reason"))
        time.sleep(interval_sec)
    raise TikTokUploadFailed(f"publish_id={publish_id} が時間内に完了しませんでした")


def publish_to_inbox(db: Database, file_path: Path) -> str:
    """動画をTikTokのinbox下書きへ送信し、publish_idを返す。"""
    access_token = get_access_token(db)
    video_size = file_path.stat().st_size
    ranges = _chunk_ranges(video_size)
    publish_id, upload_url = init_inbox_upload(access_token, video_size, ranges)
    upload_chunks(upload_url, file_path, ranges, video_size)
    wait_for_completion(access_token, publish_id)
    return publish_id
