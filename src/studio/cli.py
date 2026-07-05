"""studio コマンド（typer CLI）。

render / pipeline / publish / auth tiktok は実体を持つ。analyze は後続マイルストーンのスタブ。
"""

from __future__ import annotations

import logging
from pathlib import Path

import typer

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

app = typer.Typer(help="AI産業革命報道局 — TikTok半自動運用システム", no_args_is_help=True)
auth_app = typer.Typer(help="外部サービスの初回OAuth認可")
app.add_typer(auth_app, name="auth")


@app.command()
def render(
    script: Path = typer.Option(..., "--script", "-s", help="台本JSONのパス", exists=True),
    out: Path = typer.Option(Path("out.mp4"), "--out", "-o", help="出力mp4パス"),
    preview: bool = typer.Option(
        False, "--preview", help="低解像度・高速プレビュー（確認用）"
    ),
) -> None:
    """台本JSONから縦型ショート動画を1本レンダリングする。"""
    from studio.renderer.render import render_script

    result = render_script(script, out, preview=preview)
    typer.echo(f"[ok] generated: {result.path}  ({result.duration_sec:.2f}s)")


@app.command()
def pipeline(
    dry_run: bool = typer.Option(False, "--dry-run", help="投稿依頼なしで動画生成まで"),
) -> None:
    """収集→台本→採点→TTS→挿絵→レンダ→承認依頼。

    --dry-run は承認依頼(Stage6)を省略して動画生成までで止める。
    ANTHROPIC_API_KEY 未設定時はオフラインのダミー応答で配線確認ができる。
    """
    import datetime as dt

    from studio.pipeline import run as run_pipeline
    from studio.pipeline import run_dry
    from studio.shared.config import DATA, settings
    from studio.shared.db import Database
    from studio.shared.llm import build_llm_client

    db = Database(settings.db_path)
    llm = build_llm_client(db)
    run_dir = DATA / "runs" / dt.datetime.now().strftime("%Y%m%d_%H%M%S")

    try:
        result = run_dry(db, llm, run_dir) if dry_run else run_pipeline(db, llm, run_dir)
    finally:
        db.close()

    if result is None:
        typer.echo("[skip] 本日は投稿できる動画がありませんでした（品質基準を満たさず）。")
        raise typer.Exit(code=1)
    tag = "dry-run" if dry_run else "video"
    typer.echo(
        f"[ok] {tag}: {result.video_path}  ({result.duration_sec:.2f}s)  "
        f"topic={result.topic_id} script={result.script_id}"
    )
    if result.video_url:
        typer.echo("[ok] LINEに承認依頼を送信しました")


@auth_app.command("tiktok")
def auth_tiktok() -> None:
    """TikTokの初回OAuth認可を行い、トークンをDBに保存する（`studio publish`実行前に一度だけ）。

    TikTok Login Kitはhttps以外のredirect_uriを受け付けないため、実際の認可フローは
    GitHub Pages上の橋渡しページ(docs/oauth-callback.html, TIKTOK_REDIRECT_URI)を経由し、
    そこからローカルのtiktok_local_callback_portへJSリダイレクトされる形で完結する。
    事前にTikTok Developers の Login Kit 設定に TIKTOK_REDIRECT_URI を登録しておくこと。
    """
    import secrets
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import parse_qs, urlparse

    from studio.publisher import tiktok as tiktok_client
    from studio.shared.config import settings
    from studio.shared.db import Database

    state = secrets.token_urlsafe(16)
    auth_url = tiktok_client.build_authorize_url(state)
    typer.echo(f"ブラウザで以下のURLを開いて認可してください:\n{auth_url}")
    typer.launch(auth_url)

    callback: dict[str, str] = {}

    class _CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            qs = parse_qs(urlparse(self.path).query)
            callback["code"] = qs.get("code", [""])[0]
            callback["state"] = qs.get("state", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("認可が完了しました。このタブは閉じて構いません。".encode())

        def log_message(self, *args: object) -> None:
            return

    server = HTTPServer(("localhost", settings.tiktok_local_callback_port), _CallbackHandler)
    typer.echo(
        f"http://localhost:{settings.tiktok_local_callback_port}/callback でコールバック待機中..."
    )
    server.handle_request()
    server.server_close()

    if callback.get("state") != state:
        typer.echo("[error] stateが一致しません(CSRF対策のため中断しました)")
        raise typer.Exit(code=1)
    if not callback.get("code"):
        typer.echo("[error] 認可コードを受け取れませんでした")
        raise typer.Exit(code=1)

    token = tiktok_client.exchange_code_for_token(callback["code"])
    db = Database(settings.db_path)
    try:
        tiktok_client.save_token(db, token)
    finally:
        db.close()
    typer.echo("[ok] TikTokの認可が完了し、トークンをDBに保存しました。")


@app.command()
def publish() -> None:
    """承認検知→TikTokドラフト送信→LINE完了通知。"""
    from studio.publish import run as run_publish
    from studio.shared.config import settings
    from studio.shared.db import Database

    db = Database(settings.db_path)
    try:
        outcomes = run_publish(db)
    finally:
        db.close()

    if not outcomes:
        typer.echo("[skip] 送信待ちの動画はありませんでした。")
        return
    for o in outcomes:
        typer.echo(f"[{o.status}] script_id={o.script_id} {o.detail}")


@app.command()
def analyze() -> None:
    """週次分析→prompt_insights更新（M5で実装）。"""
    typer.echo("analyze は M5 で実装予定です。")
    raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
