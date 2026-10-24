<div align="center">
  <h1>MatrAIx in the Wild</h1>
  <p><strong>現実の意思決定のためのペルソナシミュレーション対照実験アーキテクチャ</strong></p>
  <p>
    <a href="../../README.md">English</a> |
    <a href="README.zh-CN.md">简体中文</a> |
    <a href="README.zh-TW.md">繁體中文</a> |
    <a href="README.ko.md">한국어</a> |
    <strong>日本語</strong> |
    <a href="README.es.md">Español</a> |
    <a href="README.pt-BR.md">Português</a>
  </p>
  <p>
    <a href="https://matraix.ai/"><img alt="ウェブサイト" src="https://img.shields.io/badge/Website-matraix.ai-4f7cff?style=for-the-badge"></a>
    <a href="https://matraix.ai/research/matraix-in-the-wild.html"><img alt="技術報告" src="https://img.shields.io/badge/Technical%20report-In%20the%20Wild-176b4d?style=for-the-badge"></a>
    <a href="../README.md"><img alt="ドキュメント" src="https://img.shields.io/badge/Docs-Handbook-5b5b5b?style=for-the-badge"></a>
    <a href="https://huggingface.co/datasets/MatrAIx2026/MatrAIx_Persona_1M_Public_Release"><img alt="Hugging Face" src="https://img.shields.io/badge/Hugging%20Face-Persona%201M-ffcc4d?style=for-the-badge"></a>
    <a href="../../LICENSE"><img alt="ライセンス" src="https://img.shields.io/badge/License-MIT-c33b32?style=for-the-badge"></a>
  </p>
</div>

このリポジトリは、現実の意思決定のためのペルソナシミュレーションに関する
[技術報告](https://matraix.ai/research/matraix-in-the-wild.html)に
付随します。指定したペルソナコホートが製品環境で示す振る舞いを、繰り返し
可能な測定に変え、一本のパイプラインで **ユーザーシミュレーション**、
**製品ジャーニー**、**業界標準の対照実験**をつなぎます。

証拠は四つの連なった単位に整理されます。*試行*（ペルソナ一人 × 刺激一つ）、
*バッチ実行*（コホート一つ × 固定刺激一つ）、コホートや刺激をまたぐ
*対照比較*、そして意思決定のための *標準化レポート*。各単位は下の単位に
対応するため、集計結果は構成する観測と、その水準が支えうる主張まで辿れます。

研究はまず対象コホートを再利用可能なペルソナマニフェストとして凍結し、書面の
実験契約のもとでアンケート、チャットボット、ウェブサイト、OS アプリに晒します。
何が変わり、何が固定か、どの指標が主・副・ガードレールかです。共有割り当ては
アーム間で同じペルソナ ID を再利用し、分割割り当ては人を分けます。製品や
モデルの改訂後も、同じプロトコルを再実行できます。

シミュレーションの応答は、実在の人からの証拠の代わりにはなりません。*誰が
シミュレートされているか*を研究の検査可能な部分にし、どの代替案、どの集団差、
どの未解決の問いが続く人による評価に値するかを指します。基盤となる人口
スキーマと Persona 1M コアセットは
[MatrAIx-Persona-8B](https://github.com/MatrAIx-ai/MatrAIx-Persona-8B) にあります。

<p align="center">
  <img src="../assets/matraix-in-the-wild-infrastructure.png" alt="四段階: コホートを合成し、バッチ実行し、任意で対照実験を行い、意思決定レポートを出す" width="100%">
</p>

<p align="center"><em>コホート → バッチ実行 → 対照実験 → レポート。集計結果はそれぞれ、それを生んだ試行に戻ります。</em></p>

## 何を問えるか

すべての研究は**誰 × 何**です。コホートは一つまたは複数、体験は一つまたは
複数のバージョン。これで四つの設計になります。図は
[技術報告](https://matraix.ai/research/matraix-in-the-wild.html)
からのものです（詳細は省いてあります）。複製すべきタスクではなく、問いの*種類*を示します。

<table>
  <tr>
    <th width="14%" align="center"><sub>誰 ↓ · 何 →</sub></th>
    <th width="43%" align="center">体験が一つ</th>
    <th width="43%" align="center">バージョンが複数</th>
  </tr>
  <tr>
    <th valign="middle" align="center">コホート<br>が一つ</th>
    <td valign="top" align="center">
      <img src="../assets/who-what-explore.png" alt="反応を見る: 一つのコホートが一つの登録体験に出会う" width="100%">
      <br><strong>反応を見る</strong><br>
      この集団は、あるアイデアや体験にどう反応するか？<br>
      <em>バッチ実行です。摩擦と裾を見るのに向きます。それ自体は効果ではありません。</em>
    </td>
    <td valign="top" align="center">
      <img src="../assets/who-what-compare-alternatives.png" alt="案を比べる: 一つのコホートが原文と、より明確な文言を見る" width="100%">
      <br><strong>案を比べる</strong><br>
      この集団は、異なるバージョンにどう反応するか？<br>
      <em>同じ人、異なる製品 / コピー / ページ（SUT）。</em>
    </td>
  </tr>
  <tr>
    <th valign="middle" align="center">コホート<br>が複数</th>
    <td valign="top" align="center">
      <img src="../assets/who-what-compare-groups.png" alt="集団を比べる: 複数のコホートが同じ体験を見る" width="100%">
      <br><strong>集団を比べる</strong><br>
      異なる集団は、同じ体験にどう反応するか？<br>
      <em>体験は固定。変わるのは誰をシミュレートするか（PUT）。</em>
    </td>
    <td valign="top" align="center">
      <img src="../assets/who-what-crossed.png" alt="集団をまたいで案を比べる: バージョンとコホートを交差" width="100%">
      <br><strong>集団をまたいで案を比べる</strong><br>
      どのバージョンが、どの集団により合うか？<br>
      <em>両方の軸が変わります。</em>
    </td>
  </tr>
</table>

下の最初の実験は**案を比べる**です。そのマス（および集団を比べる）の
アンケートとウェブの例は `experiments/tasks/` にあります。

## ここから始める

[uv](https://docs.astral.sh/uv/) と Python 3.12 が必要です。Node 20+ は
Playground だけに使います。Docker はウェブ / OS-app タスクだけに必要で、
下のアンケート実験には不要です。Windows では
[WSL2](https://learn.microsoft.com/windows/wsl/install) を使い、Linux
ファイルシステム内に clone してください（`/mnt/c/…` ではない）。

```bash
git clone https://github.com/MatrAIx-ai/MatrAIx_in_the_Wild.git
cd MatrAIx_in_the_Wild
uv venv --python 3.12
uv pip install -e .
uv pip install -e packages/playground
uv pip install -e packages/harbor-langsmith
uv pip install -e packages/rewardkit
```

`application/playground/.env.local.example` を
`application/playground/.env.local` にコピーし、キーを入れてください。例のファイルの
既定は `anthropic/claude-haiku-4-5`（`ANTHROPIC_API_KEY`）です。他の接頭辞
（`ppapi/…`、`dashscope/…`、`openai/…`）は
[agents.md](../environment/agents.md) にあります。

インストールの確認（キー不要）:

```bash
uv run matraix smoke application/tasks/example-survey_product-feedback
```

`Smoke: ok` と出るはずです。より長い手順:
[quickstart](../quickstart.md)。

### 1. Playground — UI で実験を実行

```bash
# ターミナル A
VENV=.venv bash application/playground/backend/run_dev.sh

# ターミナル B
cd application/playground/frontend && npm ci && npm run dev
```

http://localhost:5173 → **Experiments** → **New experiment** →
[`survey-onboarding-framing`](../../experiments/tasks/survey-onboarding-framing/)
→ **Configure & Run** → 小さいコホートを選ぶ → **Launch 2-arm experiment**。

同じ人が、機能寄りのオンボーディングと成果寄りのオンボーディングを見ます。
満足度が主指標、知覚された手間がガードレールです。

### 2. CLI — 同じ実験

```bash
uv run matraix experiment create experiments/tasks/survey-onboarding-framing \
  --name onboarding-first-run \
  --per-arm 4 \
  --seed 42
```

`--per-arm 4` は安い最初の一回です（同じ 4 人が両方のアームに）。
`.env.local` のペルソナモデルを使います。終わったら:

```bash
uv run matraix experiment list
uv run matraix experiment analyze <experiment_id>
```

`experiments/tasks/` にはほかに `survey-upgrade-copy`（コピーの A/B）、
`survey-trust-by-segment`（集団を比べる）、`web-compare-options`（ウェブの A/B、
Docker が必要）があります。

本番のコホートには
[Persona 1M](https://huggingface.co/datasets/MatrAIx2026/MatrAIx_Persona_1M_Public_Release)
を取り込んでください:

```bash
huggingface-cli download MatrAIx2026/MatrAIx_Persona_1M_Public_Release \
  --repo-type dataset \
  --local-dir persona/datasets/matraix-persona-1m/release
```

リポジトリ内の `matraix-persona-dev-sample`（約 200 人）はスモーク専用です。

自分の研究を足すには、`application/tasks/example-*` または
`experiments/tasks/*` をコピーし、
[タスクガイド](../application/task-guide.md) または
[実験タスクガイド](../application/experiment-task-guide.md) に従ってください。

## 一回の実行で起きること

1. **コホート** — ペルソナを絞ってサンプルし、ID を凍結します。同じ人が
   あとで新しいバージョンに会えるようにするためです。
2. **バッチ** — 体験は一つ、試行は互いに隔離。出力は
   `jobs/<job_name>/` に落ちます。
3. **実験** — 契約がアームに展開され、それらのジョブが起動します。
   共有割り当ては同じ人をアーム間で再利用し、分割割り当ては人を分けます。
4. **レポート** — 指名した指標でアームを比較します。レポートは
   分母、除外、各試行へ戻る経路を残します。

## ドキュメント

| | |
|---|---|
| [技術報告](https://matraix.ai/research/matraix-in-the-wild.html) | このスタックが存在する理由と、研究の設計 |
| [Quickstart](../quickstart.md) | 最初の実行を手順どおりに |
| [実験タスクガイド](../application/experiment-task-guide.md) | 案の比較、または集団の比較を書く |
| [実験成果物（HF）](../application/hf-experiment-artifacts.md) | 凍結コホートと試行成果物を提出（非公開データセット） |
| [エージェントとキー](../environment/agents.md) | モデル id と API キー |
| [Handbook](../README.md) | ペルソナ、アプリケーション、環境のドキュメント |

```text
application/tasks/       例のタスク（アンケート、チャット、ウェブ、OS-app）
experiments/             対照実験 + スコアカード
persona/                 スキーマ、データセット、サンプリング
environment/             ランタイム、エージェント、Docker / sidecar
application/playground/  ビジュアルランナー
configs/jobs/            ジョブレシピ
jobs/                    ローカル出力（gitignored）
```

## ライセンス

MIT — [LICENSE](../../LICENSE)。
