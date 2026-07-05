# 外部サービス設定マニュアル

このプロジェクトを最後まで動かすために必要な、外部サービスのアカウント作成・キー発行手順をまとめる。
`.env`に設定する環境変数名は SPEC 10章と対応している。設定後は `.env.example` を `.env` にコピーして値を埋めること。

設定が必要な時期の目安:
- **M2から**: Anthropic API（必須）、fal.ai（任意・未設定でも固定背景で動く）、VOICEVOX（任意・未設定でも概算秒数で動く）
- **M3から**: LINE、Cloudflare（R2 + Workers KV）
- **M4から**: TikTok Developers、GitHub Secrets

---

## 1. Anthropic API（LLM呼び出し・M2から必須） ✓

台本生成・ファクト検証・採点に使う。**これが無いと `studio pipeline` は動かない**（`--dry-run`はキー無しでもオフラインのダミー応答で配線確認ができる）。

1. https://console.anthropic.com/ でアカウント作成
2. 支払い方法を登録（クレジットカード）。従量課金なので、Billingページで**使用量アラート**を設定しておくことを推奨
3. 「API Keys」からキーを新規発行
4. `.env` に設定:
   ```
   ANTHROPIC_API_KEY=sk-ant-xxxxxxxx
   ```
5. （任意）`DAILY_LLM_CALL_LIMIT`（デフォルト30回/日）を必要に応じて調整

---

## 2. fal.ai（画像生成・M2から・任意）※後で

B-roll挿絵の生成に使う。**未設定でも動画は生成される**（brollが固定背景にフォールバックするだけ）。

1. https://fal.ai/ でアカウント作成
2. ダッシュボードからAPIキーを発行
3. `.env` に設定:
   ```
   FAL_KEY=xxxxxxxx
   ```
4. （任意）`IMAGE_DAILY_LIMIT`（デフォルト5枚/日）を調整

---

## 3. VOICEVOX Engine（音声合成・M2から・任意）✓

セリフの音声合成に使う。**未起動でも動画は生成される**（実測秒数の代わりに文字数からの概算秒数を使うだけ）。

### ローカル開発（Docker不要・推奨）
1. https://github.com/VOICEVOX/voicevox_engine/releases から自分のOS用のスタンドアロン版をダウンロード
2. 解凍して `run.exe`（Windows）等を実行 → `http://localhost:50021` にAPIが立つ
3. 使う話者を決める: `http://localhost:50021/speakers` をブラウザで開き、一覧から実際に声を聴いて選ぶ
4. `.env` に設定（値は選んだ話者のID。デフォルト値は暫定なので必ず自分で選び直すこと）:
   ```
   VOICEVOX_URL=http://localhost:50021
   VOICEVOX_SPEAKER_FOX=11
   VOICEVOX_SPEAKER_RABBIT=46
   ```

---

## 4. LINE Developers（承認通知・M3から）✓

生成された動画をLINEで受け取り、「承認」「却下」ボタンで判断するために使う。

現在はLINE Developersコンソールから直接チャネルを作ることはできず、**LINE公式アカウント経由**での作成に一本化されている。

1. https://developers.line.biz/ に手持ちのLINEアカウントでログイン
2. 「Messaging APIチャネルの作成」画面で案内される **「LINE公式アカウントを作成する」** ボタンを押す
3. 公式アカウント作成フォームに入力（アカウント名、メールアドレス、業種など）→ 作成
4. **LINE Official Account Manager**（https://manager.line.biz/）に移動し、対象アカウントの
   **設定 → Messaging API** タブを開き、**「Messaging APIを利用する」** を有効化
   - この際 Provider（入れ物）の新規作成を求められるので新規作成でよい
   - 有効化すると LINE Developers コンソール側にも自動でチャネルが作られる
5. LINE Developers コンソールに戻り、作成されたチャネルから取得:
   - **チャネルアクセストークン**（Messaging API設定タブ、長期発行ボタン）→ `LINE_CHANNEL_ACCESS_TOKEN`
   - **チャネルシークレット**（チャネル基本設定タブ）→ `LINE_CHANNEL_SECRET`
6. 応答設定は **LINE Official Account Manager** の「応答設定」で行う:
   - あいさつメッセージ・自動応答: **オフ**（ノイズになるため）
7. **Webhook URL欄について（今は空欄のままでよい）**:
   - LINE Developers コンソールのチャネル設定に「Webhook URL」の入力欄と、それとは別に
     「Webhookの利用」トグルがある。どちらもセットで機能する
   - Webhook URLは、ユーザーがBotにメッセージを送ったり「承認/却下」ボタンをタップした際に、
     LINEがそのイベントをPOSTしてくる送信先（＝Cloudflare Workerのエンドポイント）
   - **Cloudflare Worker（`workers/approval/`）をまだデプロイしていないので、入力するURLが無い。
     この欄は空欄のまま次に進んでよい。M3でWorkerを実装・デプロイした後にこの画面へ戻り、
     WorkerのURLを入力して「Webhookの利用」をオンにする**
8. 作成した公式アカウントを**自分のLINEアプリで友だち追加**（QRコードが管理画面にある）
9. **管理者のuserId取得**（`LINE_ADMIN_USER_ID`）:
   - LINEの`userId`は管理画面に直接表示されないことが多く、Webhookで受けて確認するのが確実
   - M3実装時に、Cloudflare Workerのログか一時的な確認用スクリプトで取得する手順を用意する（このステップは実装と一緒に行う）

`.env` に設定:
```
LINE_CHANNEL_ACCESS_TOKEN=xxxxxxxx
LINE_CHANNEL_SECRET=xxxxxxxx
LINE_ADMIN_USER_ID=Uxxxxxxxx
```

---

## 5. Cloudflare（R2 + Workers + KV・M3から）

動画のホスティング（R2）と、LINE Webhookの受信・承認状態の保存（Workers + KV）に使う。

### 5-1. Cloudflareアカウント✓
1. https://dash.cloudflare.com/ でアカウント作成

### 5-2. R2（動画ファイル置き場）✓
1. ダッシュボード左メニューから **R2** を開き、バケットを新規作成（例: `ai-news-studio`）
2. 「R2 API トークンを管理」からAPIトークンを発行（Object Read & Write権限）
   - 発行時に表示される **Access Key ID** / **Secret Access Key** を控える
3. アカウントID（ダッシュボード右側 or URLに表示）を控える
4. `.env` に設定:
   ```
   R2_ACCOUNT_ID=xxxxxxxx
   R2_ACCESS_KEY_ID=xxxxxxxx
   R2_SECRET_ACCESS_KEY=xxxxxxxx
   R2_BUCKET=ai-news-studio
   ```

### 5-3. Workers + KV（承認状態の保存）✓
1. ダッシュボードの **Workers & Pages** → **KV** から Namespace を新規作成（例: `approval-kv`）
   - 作成後に表示される **Namespace ID** を控える → `CF_KV_NAMESPACE_ID`
2. **My Profile → API Tokens** からAPIトークンを発行
   - 権限: `Workers Scripts:Edit`, `Workers KV Storage:Edit` を含める
   - → `CF_API_TOKEN`
3. Wrangler CLI（Node.js製、Workerのデプロイツール）のインストール:(後でClaudeCodeが実行予定)
   ```
   npm install -g wrangler
   ```
   - **`wrangler login`（ブラウザでの手動OAuth認可）は不要**。上記2.で発行した`CF_API_TOKEN`を
     環境変数 `CLOUDFLARE_API_TOKEN` としてセットしておけば、Wranglerはそれを使って
     非対話的にデプロイできる（`wrangler deploy`実行時にこの環境変数を渡すだけでよい）
4. Worker本体（`workers/approval/`）の実装・デプロイはM3のコード実装時に行う。デプロイ後にWorkerのURLをLINEのWebhook URLとして登録する（4.の手順8）

`.env` に設定:
```
CF_KV_NAMESPACE_ID=xxxxxxxx
CF_API_TOKEN=xxxxxxxx
```

---

## 6. TikTok Developers（投稿・M4から）✓（アプリ登録まで完了。以下は実施内容の記録）

生成された動画をTikTokの下書き（inbox）に送るために使う。

1. https://developers.tiktok.com/ でアカウント作成・アプリ登録（アプリ名: `ai-news-studio`）

2. **Web/Desktop URL・Privacy Policy URL・Terms of Service URLの用意**（Basic information入力時に必須だった）:
   - GitHub Pages（`github.com/interkid/ai-news-studio` の `docs/`フォルダ、Source: Deploy from a branch /
     Branch: `master` / Folder: `/docs`）で以下の3ページを公開:
     - Web/Desktop URL: `https://interkid.github.io/ai-news-studio/`
     - Privacy Policy URL: `https://interkid.github.io/ai-news-studio/privacy.html`
     - Terms of Service URL: `https://interkid.github.io/ai-news-studio/terms.html`
   - 個人利用の自動化ツールである旨・扱うスコープ（user.info.basic / video.upload / video.list）・
     第三者提供なしの旨を明記した内容にしてある
   - 初回デプロイが `Deployment failed, try again later` で失敗することがあったが、
     `.nojekyll`追加＋再pushで解消（GitHub Pages初回有効化直後によくある一時的な失敗）

3. **ドメイン所有権の検証（URL Properties → Verification method: signature file）**:
   - 「Domain」ではなく **「URL prefix」** を選択する
     （`interkid.github.io`は共有ドメインのため、ドメイン全体の所有権証明であるDomain方式は使えない。
     `github.io`配下の自分のパスだけを証明する場合はURL prefix方式が対応する）
   - TikTokが発行する検証ファイル（例: `tiktok<コード>.txt`、中身は`tiktok-developers-site-verification=<コード>`）
     を `docs/` 直下に設置してpush → `https://interkid.github.io/ai-news-studio/tiktok<コード>.txt`
     として公開されるようにする → Verify実行 → 完了

4. **Products追加**（Manage apps → 対象アプリ → Products → + Add products）:
   - **Login Kit** を追加（`user.info.basic`用）
   - **Content Posting API** を追加（`video.upload` / `video.list`用）
   - Share Kit・Webhook・Data Portability APIは本プロジェクトの用途には不要なので追加していない

5. 各Productの設定画面でスコープを有効化（完了）:
   - `video.upload`（ドラフト送信に必要）
   - `user.info.basic`
   - `video.list`（分析用、M5で使用）

6. アプリ管理画面から **Client Key** / **Client Secret** を取得
   ```
   TIKTOK_CLIENT_KEY=xxxxxxxx
   TIKTOK_CLIENT_SECRET=xxxxxxxx
   ```

7. **リダイレクトURIの登録**（`studio auth tiktok` 実行前に必要）:
   - **Login Kitの Redirect URI(Web)は https 必須で、`http://localhost:...` は直接登録できない**
     （実際にTikTok側で「Enter a valid URL beginning with https://」と拒否されることを確認済み）
   - 対策として、GitHub Pages上に橋渡し用の静的ページを1枚用意した:
     `docs/oauth-callback.html`（このページのJSが`window.location.search`をそのまま
     `http://localhost:8921/callback`へリダイレクトするだけの中継地点）
   - Manage apps → 対象アプリ → **Login Kit** の設定画面で、Redirect URI(Web)に以下を登録する:
     ```
     https://interkid.github.io/ai-news-studio/oauth-callback.html
     ```
   - `docs/oauth-callback.html` はまだGitHubにpushしていないので、登録前にpushしてGitHub Pagesに
     反映されていることを確認する
   - `.env`の`TIKTOK_REDIRECT_URI`（デフォルトで上記URLと一致）・`TIKTOK_LOCAL_CALLBACK_PORT`
     （デフォルト8921）を変えた場合は、上記ページ内のポート番号とTikTok側の登録値も合わせて変更すること

8. 初回のOAuth認可は `studio auth tiktok` をローカル実行する（実装済み）:
   - ブラウザで認可画面が開くので手持ちのTikTokアカウントでログイン・許可する
   - TikTokは認可後、上記のGitHub Pagesページへリダイレクト→そのページのJSが
     `http://localhost:8921/callback`へ再リダイレクト→ローカルの一時HTTPサーバがcodeを受け取り、
     トークン交換まで自動で行う。**取得したrefresh_tokenは`.env`に書く必要はなく、
     ローカルの`data/studio.db`（`oauth_tokens`テーブル）に保存される**
   - refresh_tokenはTikTok側の仕様で使うたびにローテーション（新しい値に置き換え）されるため、
     `.env`の`TIKTOK_REFRESH_TOKEN`は「DBにまだ何もない新しい環境（例: GitHub Actionsの
     初回実行時）向けの初期シード値」という位置づけになる
   ```
   TIKTOK_REFRESH_TOKEN=xxxxxxxx
   ```

9. **「Submit for App Review」は不要と確認済み（押さない）**:
   - Content Posting APIの設定ページに以下の記載があることを確認した:
     - **「Upload to TikTok」（inbox下書きアップロード）はデフォルトで有効・審査不要**
     - 「Direct Post」（プロフィールへの直接投稿）は別機能で、本プロジェクトでは使わない
     - 「Verify domains」は`pull_by_url`（URLから動画取得）方式専用のドメイン検証で、
       本プロジェクトは`push_by_file`（チャンクアップロード）方式のため不要
   - つまり「Submit for App Review」ボタンを押して本審査に進む必要はなく、
     「Upload at least one demo video...」等の本審査専用の必須項目も入力不要

10. 注意点:
    - ドラフト送信（inbox）は未監査アプリでも利用可能
    - Direct Post（直接公開）は未監査だとSELF_ONLY強制になるため使わない（このプロジェクトはinbox方式のみ使用）
    - レート制限: access_tokenあたり6リクエスト/分。チャンクアップロードは直列で行う（実装済み）

---

## 7. GitHub Actions（本番運用の実行基盤・M4から）

1. GitHubリポジトリの **Settings → Secrets and variables → Actions** に、上記で取得した値をすべて登録する

   | Secret名 | 値の出どころ |
   |---|---|
   | `ANTHROPIC_API_KEY` | 1. |
   | `FAL_KEY` | 2. |
   | `LINE_CHANNEL_ACCESS_TOKEN` | 4. |
   | `LINE_CHANNEL_SECRET` | 4. |
   | `LINE_ADMIN_USER_ID` | 4. |
   | `R2_ACCOUNT_ID` | 5-2. |
   | `R2_ACCESS_KEY_ID` | 5-2. |
   | `R2_SECRET_ACCESS_KEY` | 5-2. |
   | `R2_BUCKET` | 5-2. |
   | `CF_KV_NAMESPACE_ID` | 5-3. |
   | `CF_API_TOKEN` | 5-3. |
   | `TIKTOK_CLIENT_KEY` | 6. |
   | `TIKTOK_CLIENT_SECRET` | 6. |
   | `TIKTOK_REFRESH_TOKEN` | 6-8.（新しい環境向けの初期シード値。実運用ではDBのoauth_tokensが優先される） |

2. `daily.yml` / `publish.yml`（実装済み）/ `weekly.yml`（M5で実装）は、これらSecretsを環境変数として読み込む
   前提で作ってある。ただし**`daily.yml`/`publish.yml`は現状 `workflow_dispatch`（手動実行）のみが
   有効で、`schedule`（自動cron）はコメントアウトしてある**。動画の品質を目視確認できるまでは
   意図的に自動投稿をOFFにしている。有効化する際は各ymlの`# schedule:`以下のコメントを外すこと

---

## `.env` の作り方（ローカル開発）

1. リポジトリ直下の `.env.example` を `.env` にコピー
2. 上記の手順で取得した値を埋める
3. `.env` は `.gitignore` 済みなのでコミットされない

現時点（M2まで）で必須なのは **Anthropic API のみ**。他は無くても動作確認できる（フォールバックあり）。
