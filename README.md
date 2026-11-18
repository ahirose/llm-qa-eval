# Security Q&A Harness

固定の質問・模範回答セットで、根拠の取得方式、MCP ツール、回答モデルの変更が正答率・応答時間・トークン使用量にどう影響するかを比較する Python CLI です。設定は TOML、データセットとログは JSONL、モックは Python 標準ライブラリで動作します。Python 3.11 以上が必要です。

## すぐに試す

ZIP を展開し、README があるフォルダで実行します。

```powershell
python -m unittest -v
python harness.py ask --profile direct "Where should I report a suspected security incident?"
python harness.py eval --dataset cases.jsonl --profiles baseline direct search tool
```

モックの2問では baseline が 0/2、ほかの3方式が 2/2 になるよう設計しています。この結果は配線の確認用です。

## 実サービスを接続する

1. 仮想環境で `python -m pip install -r requirements.txt` を実行します。
2. `live.example.toml` を同じフォルダの `live.local.toml` にコピーします。利用可能なモデル ID と、使用する場合は MCP のツール名・引数名を入力します。
3. 利用するサービスの認証情報と接続先 URL を、OS またはシークレットマネージャー経由で実行プロセスの環境変数に設定します。モデルは `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`、検索・MCP はサンプル設定にある環境変数を参照します。Bearer 認証が不要なら、そのプロファイルから `token_env` を外します。
4. 同じ質問セット、同じ採点モデルで比較します。まず `baseline direct`、検索の準備ができたら `direct search`、MCP は `baseline tool`、モデル変更は `direct claude_direct` を比較します。

```powershell
python harness.py --config live.local.toml eval --dataset cases.jsonl --profiles baseline direct
```

### 切り替え

- `model` は `provider`、`id`、任意の `max_tokens`。OpenAI Responses API と Anthropic Messages API を使用します。利用モデルはアカウントと入力形式に合わせて指定します。
- `retrieval.mode` は `none` / `direct-file` / `external-search`。直接入力は設定ファイルを基準とした `files` で UTF-8 の TXT・Markdown または PDF を指定します。OpenAI は `input_file`、Anthropic は PDF を `document`、テキストファイルをメッセージ内のテキストブロックで送ります。合計5 MiB が上限です。
- 外部検索は HTTPS の JSON API に `POST {"query":"...","top_k":3}` を送り、`{"results":[{"id":"doc-1","text":"passage"}]}` を受け取ります。既存の Pinecone 検索を使う場合は、質問の埋め込みとインデックス照会を担当する検索サービスから、この形式で結果を返します。
- `mcp.mode` は `none` / `remote`。MCP Python SDK v1 の Streamable HTTP で、設定された信頼済みサーバー上の参照系ツールを各質問で一度呼びます。`arguments` の固定引数に、`question_arg`（既定値 `query`）で質問を追加します。比較条件を固定するため、モデルにはツールの戻り値を渡します。ツールはテキストの content ブロックを返す必要があります。

質問は設定に応じて外部検索・MCP・モデルに送信されます。回答モデルには取得結果またはファイルが、採点モデルには質問・模範回答・候補回答が送信されます。接続前にデータの取り扱いを確認し、デモには同梱の架空データを使ってください。秘密値を設定・データセット・ツール引数に記入しないでください。

## 評価とログ

各データ行は `id`、`question`、`reference` の文字列を持ちます。`judge` は全プロファイル共通です。実モデルの採点では JSON の合否と理由を検証し、採点形式の異常は実行エラーとしてカウントします。正答率は合格数÷採点済み件数、カバレッジは採点済み件数÷全件です。カバレッジとエラー件数も併せて確認してください。

`runs/` の JSONL は設定・データセットの SHA-256、ケース ID、方式、モデル ID、使用量、回答生成（取得・MCP を含む）と採点の所要時間、合否、エラー段階を記録します。質問・模範回答・原文の検索結果は保存しません。`--log-content` を付けると生成回答と採点理由もローカルに保存します。保存内容に元の資料が引用される可能性があります。

応募デモでは、同じ資料を検索側とファイル側に用意し、モデルと採点条件を固定して、検索なし・外部検索・直接入力を比較できます。過去の Security Q&A Assistant の 70%→90% は当時の結果として扱い、このサンプルの結果とは区別します。実験を報告する際は、データセット、モデル ID、検索インデックスの版と、正答率・件数・カバレッジを添えられます。

## 検証範囲

同梱テストはモックでの CLI 比較、取得エラー時の集計、外部検索のリクエスト形式、採点 JSON の型、重複 ID を確認します。実アカウントでの OpenAI / Anthropic 呼び出し、PDF 入力、外部検索、MCP 接続、Pinecone のインデックス照会は未検証です。API の仕様は以下を参照しました。

- [OpenAI Responses API のファイル入力](https://developers.openai.com/api/docs/guides/file-inputs)
- [Anthropic Messages API](https://platform.claude.com/docs/en/api/messages/create) · [PDF 入力](https://platform.claude.com/docs/en/build-with-claude/pdf-support)
- [MCP Python SDK v1](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x)
