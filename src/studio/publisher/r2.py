"""Cloudflare R2 アップロード + 署名付きURL発行（SPEC 7章 Stage6）。

R2はS3互換APIのため boto3 で扱う。動画プレビュー用の署名付きURLは
有効期限72時間（LINEでの確認・承認に十分な猶予）。
"""

from __future__ import annotations

from pathlib import Path

import boto3

from ..shared.config import settings

PRESIGNED_URL_EXPIRE_SEC = 72 * 3600


class R2NotConfigured(RuntimeError):
    pass


def _client():
    if not (settings.r2_account_id and settings.r2_access_key_id and settings.r2_secret_access_key):
        raise R2NotConfigured(
            "R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY が未設定です"
        )
    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
    )


def upload_video(file_path: Path, key: str) -> str:
    """動画をR2にアップロードし、有効期限72hの署名付きURLを返す。"""
    if not settings.r2_bucket:
        raise R2NotConfigured("R2_BUCKET が未設定です")
    client = _client()
    client.upload_file(
        str(file_path), settings.r2_bucket, key, ExtraArgs={"ContentType": "video/mp4"}
    )
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.r2_bucket, "Key": key},
        ExpiresIn=PRESIGNED_URL_EXPIRE_SEC,
    )


def download_video(key: str, dest: Path) -> None:
    """R2から動画をダウンロードする。

    `studio pipeline`(動画生成+R2アップロード)と`studio publish`(TikTok送信)は
    GitHub Actions上では別ジョブ(別ランナー)で動くため、ローカルにレンダ済みファイルが
    残っていない場合にここでR2から取得し直す。
    """
    if not settings.r2_bucket:
        raise R2NotConfigured("R2_BUCKET が未設定です")
    client = _client()
    dest.parent.mkdir(parents=True, exist_ok=True)
    client.download_file(settings.r2_bucket, key, str(dest))
