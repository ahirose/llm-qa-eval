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

## モデル × RAG を一括比較する

### 試験から回答リストを作る

`recommend.py` は全組み合わせを採点し、比較結果と推奨設定を出力します。全件を採点できた組み合わせのうち、正答率が最も高いものを選びます。同率なら RAG なし、平均回答時間が短いもの、設定名順で決めます。全件を採点できた組み合わせがなければ、推奨設定は空になります。

`answer_batch.py` は推奨設定と試験時と同じ TOML を読み込み、採点なしで質問に回答します。入力は `id` と `question` を持つ JSONL で、出力には質問と回答が入力順に並びます。失敗した質問にはエラー種別を記録します。既存の回答ファイルとの上書きを避けるため、再実行時は新しい出力ファイル名を指定します。

```powershell
python recommend.py --dataset cases.jsonl --models mock_a mock_b --rag none external --output runs/recommendation.json
python answer_batch.py --recommendation runs/recommendation.json --questions questions.jsonl --output runs/answers.jsonl
```

実 API で使う場合は両方のコマンドに `--config live.local.toml` を追加します。試験側のモデル名は `--models openai claude` に変更します。

### 比較結果だけを出す

`compare` は、モデルと RAG 条件の全組み合わせを同じ質問セット・採点モデルで実行します。次のコマンドは2モデル × 2条件の4組を試します。

```powershell
python harness.py compare --dataset cases.jsonl --models mock_a mock_b --rag none external
```

実サービスでは、`live.local.toml` の `[matrix.models]` に比較するモデルの別名と ID、`[matrix.retrievals]` に検索や直接入力の設定を記入します。必要な環境変数と `[judge]` を設定して実行します。

```powershell
python harness.py --config live.local.toml compare --dataset cases.jsonl --models openai claude --rag none external
```

`--rag` の既定値は `none external` です。直接ファイル入力も並べるには `--rag none external direct` を指定します。MCP は既定で無効です。`[matrix.mcp]` を設定すると全組み合わせで同じツールを使います。

端末には組み合わせごとの合格数、正答率、採点済み件数、エラー件数、平均回答時間が表示されます。平均回答時間には検索と MCP の時間を含み、回答を取得できたケースで集計します。ケース別の合否・使用量は同じ実行の JSONL で確認できます。

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
