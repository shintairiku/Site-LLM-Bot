# Site-LLM-Bot

住宅・リフォーム業向けサイトに埋め込む AI チャットボットです。販売先には、固定 Cloud Run URL で配信する `widget.js` を読み込む script タグを案内します。

## 販売先へ渡す script タグ

`tenant_id`、`tenant_name`、`public_token` は販売先ごとに差し替えます。

```html
<script
  id="site-llm-bot-widget"
  src="https://site-llm-bot-742231208085.asia-northeast1.run.app/static/widget.js"
  data-tenant-id="顧客別tenant-id"
  data-tenant-name="顧客名"
  data-public-token="顧客別public-token"
  data-api-base="https://site-llm-bot-742231208085.asia-northeast1.run.app"
  defer
></script>
```

`src` はウィジェット JS の配信元です。販売先サイトごとに変えず、固定 Cloud Run URL を使います。

`data-api-base` はチャット API の呼び出し先です。現在は同じ Cloud Run サービスを指定します。実際の送信先は `/v1/chat/message` が付いた URL になります。

```text
https://site-llm-bot-742231208085.asia-northeast1.run.app/v1/chat/message
```

## 配布物の考え方

固定 URL で `widget.js`、`widget.css`、`tenants/{tenant_id}.css` を配信するため、販売先へ物理ファイルを渡す必要はありません。販売先へ案内する配布物は script タグだけで足ります。

ただし、運用側では以下を Cloud Run 上で配信し続ける必要があります。

- `/static/widget.js`
- `/static/widget.css`
- `/static/tenants/{tenant_id}.css`

販売先を追加する場合は、`config/tenants.json` に次を登録します。

- `tenant_id`
- `public_token`
- `allowed_origins`
- `allowed_domains`
- 必要に応じて `static/tenants/{tenant_id}.css`

`public_token` はブラウザに表示される公開前提の値です。API 側では `tenant_id + public_token + Origin` の組み合わせで検証します。

## ローカル確認

```bash
.venv/bin/uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

確認先:

```text
http://127.0.0.1:8000/demo
```

## テスト

```bash
.venv/bin/pytest -q
```
