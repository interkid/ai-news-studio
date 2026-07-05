"""Cloudflare Workers KVから承認状態を読む(SPEC 8章)。

承認/却下の書き込みはworkers/approval/(LINE Webhook)が行う。ここでは読むだけ。
KVはR2と同じCloudflareアカウント配下のため、アカウントIDは r2_account_id を流用する。
"""

from __future__ import annotations

import httpx

from ..shared.config import settings

KV_API_BASE = "https://api.cloudflare.com/client/v4"


class KVNotConfigured(RuntimeError):
    pass


def get_video_approval(video_id: int) -> dict | None:
    """`video:{video_id}` キーの承認状態を返す。未承認(キー未作成)ならNone。

    戻り値の例: {"status": "approved"} / {"status": "rejected", "reason": "..."}
    """
    if not (settings.r2_account_id and settings.cf_kv_namespace_id and settings.cf_api_token):
        raise KVNotConfigured(
            "R2_ACCOUNT_ID / CF_KV_NAMESPACE_ID / CF_API_TOKEN が未設定です"
        )
    url = (
        f"{KV_API_BASE}/accounts/{settings.r2_account_id}/storage/kv/namespaces/"
        f"{settings.cf_kv_namespace_id}/values/video:{video_id}"
    )
    resp = httpx.get(
        url, headers={"Authorization": f"Bearer {settings.cf_api_token}"}, timeout=15.0
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()
