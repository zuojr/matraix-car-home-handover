<div align="center">
  <h1>MatrAIx in the Wild</h1>
  <p><strong>面向真實世界決策的人格模擬控制實驗架構</strong></p>
  <p>
    <a href="../../README.md">English</a> |
    <a href="README.zh-CN.md">简体中文</a> |
    <strong>繁體中文</strong> |
    <a href="README.ko.md">한국어</a> |
    <a href="README.ja.md">日本語</a> |
    <a href="README.es.md">Español</a> |
    <a href="README.pt-BR.md">Português</a>
  </p>
  <p>
    <a href="https://matraix.ai/"><img alt="網站" src="https://img.shields.io/badge/Website-matraix.ai-4f7cff?style=for-the-badge"></a>
    <a href="https://matraix.ai/research/matraix-in-the-wild.html"><img alt="技術報告" src="https://img.shields.io/badge/Technical%20report-In%20the%20Wild-176b4d?style=for-the-badge"></a>
    <a href="../README.md"><img alt="文件" src="https://img.shields.io/badge/Docs-Handbook-5b5b5b?style=for-the-badge"></a>
    <a href="https://huggingface.co/datasets/MatrAIx2026/MatrAIx_Persona_1M_Public_Release"><img alt="Hugging Face" src="https://img.shields.io/badge/Hugging%20Face-Persona%201M-ffcc4d?style=for-the-badge"></a>
    <a href="../../LICENSE"><img alt="授權" src="https://img.shields.io/badge/License-MIT-c33b32?style=for-the-badge"></a>
  </p>
</div>

本倉庫伴隨我們關於面向真實世界決策的人格模擬的
[技術報告](https://matraix.ai/research/matraix-in-the-wild.html)。
它把指定人格隊列在產品環境中的行為轉化為可重複的測量，在一條管線中連接
**使用者模擬**、**產品旅程**與**業界標準的對照實驗**。

證據組織為四個相連的單位：*試驗*（一個人格 × 一種刺激）、*批次執行*
（一個隊列 × 一種固定刺激）、跨隊列或跨刺激的*對照比較*，以及面向決策的
*標準化報告*。每個單位都對應到下一層，因此彙總結果可追溯到構成它的觀測，
以及該層能夠支持的主張。

一項研究先將其目標隊列凍結為可複用的人格清單，再在書面實驗契約下將該隊列
置於問卷、聊天機器人、網站或作業系統應用中——什麼可變、什麼保持不變，以及
哪些指標是主指標、次指標或護欄。共享分配在各臂之間複用同一批人格 ID；拆分
分配則將他們分區。產品或模型修訂後，同一協議可重跑。

模擬回應不能替代來自真人的證據。它們使*被模擬的是誰*成為研究中可檢查的一部分，
並指出哪些方案、哪些人群差異、哪些未解問題值得後續真人評估。底層人口 Schema
與 Persona 1M 核心集在
[MatrAIx-Persona-8B](https://github.com/MatrAIx-ai/MatrAIx-Persona-8B)。

<p align="center">
  <img src="../assets/matraix-in-the-wild-infrastructure.png" alt="四步：合成隊列、批次執行、可選的對照實驗，然後產出決策報告" width="100%">
</p>

<p align="center"><em>隊列 → 批次執行 → 對照實驗 → 報告。每個彙總結果都能回到產生它的試驗。</em></p>

## 你可以問什麼

每項研究都是**誰 × 什麼**：一批人或幾批人，一種體驗或幾種版本。這樣就有四種設計。圖來自
[技術報告](https://matraix.ai/research/matraix-in-the-wild.html)
（細節略去）。它們說明的是問題的*類型*，不是必須照抄的任務。

<table>
  <tr>
    <th width="14%" align="center"><sub>誰 ↓ · 什麼 →</sub></th>
    <th width="43%" align="center">一種體驗</th>
    <th width="43%" align="center">幾種版本</th>
  </tr>
  <tr>
    <th valign="middle" align="center">一批人</th>
    <td valign="top" align="center">
      <img src="../assets/who-what-explore.png" alt="看反應：一批人遇到同一種註冊體驗" width="100%">
      <br><strong>看反應</strong><br>
      這批人對一個想法或體驗會怎麼反應？<br>
      <em>一次批次執行。適合看摩擦和尾部——本身還不是效應。</em>
    </td>
    <td valign="top" align="center">
      <img src="../assets/who-what-compare-alternatives.png" alt="比較方案：一批人看到原文與更清楚的措辭" width="100%">
      <br><strong>比較方案</strong><br>
      這批人對不同版本會怎麼反應？<br>
      <em>同一批人，不同的產品 / 文案 / 頁面（SUT）。</em>
    </td>
  </tr>
  <tr>
    <th valign="middle" align="center">幾批人</th>
    <td valign="top" align="center">
      <img src="../assets/who-what-compare-groups.png" alt="比較人群：幾批人看到同一種體驗" width="100%">
      <br><strong>比較人群</strong><br>
      不同的人面對同一體驗會怎麼反應？<br>
      <em>體驗固定；變的是模擬的是誰（PUT）。</em>
    </td>
    <td valign="top" align="center">
      <img src="../assets/who-what-crossed.png" alt="跨人群比較方案：版本與隊列交叉" width="100%">
      <br><strong>跨人群比較方案</strong><br>
      哪個版本對哪批人更好？<br>
      <em>兩個軸都變。</em>
    </td>
  </tr>
</table>

下面的第一個實驗是**比較方案**。該格（以及比較人群）的問卷和網頁示例在 `experiments/tasks/`。

## 從這裡開始

需要 [uv](https://docs.astral.sh/uv/) 和 Python 3.12。Node 20+ 只給 Playground 用。Docker 只給網頁 / OS-app 任務用——下面的問卷實驗不需要。Windows 請用
[WSL2](https://learn.microsoft.com/windows/wsl/install)，並把倉庫 clone 到 Linux 檔案系統裡（不要放在 `/mnt/c/…`）。

```bash
git clone https://github.com/MatrAIx-ai/MatrAIx_in_the_Wild.git
cd MatrAIx_in_the_Wild
uv venv --python 3.12
uv pip install -e .
uv pip install -e packages/playground
uv pip install -e packages/harbor-langsmith
uv pip install -e packages/rewardkit
```

把 `application/playground/.env.local.example` 複製為
`application/playground/.env.local` 並填入金鑰。示例檔案預設
`anthropic/claude-haiku-4-5`（`ANTHROPIC_API_KEY`）。其他前綴
（`ppapi/…`、`dashscope/…`、`openai/…`）見
[agents.md](../environment/agents.md)。

確認安裝（不需要金鑰）：

```bash
uv run matraix smoke application/tasks/example-survey_product-feedback
```

應看到 `Smoke: ok`。更長的步驟說明：
[quickstart](../quickstart.md)。

### 1. Playground —— 在介面裡跑實驗

```bash
# 終端 A
VENV=.venv bash application/playground/backend/run_dev.sh

# 終端 B
cd application/playground/frontend && npm ci && npm run dev
```

開啟 http://localhost:5173 → **Experiments** → **New experiment** →
[`survey-onboarding-framing`](../../experiments/tasks/survey-onboarding-framing/)
→ **Configure & Run** → 選一個小隊列 → **Launch 2-arm experiment**。

同一批人分別看到功能導向和結果導向的引導。滿意度是主指標；感知費力程度是護欄。

### 2. CLI —— 同一個實驗

```bash
uv run matraix experiment create experiments/tasks/survey-onboarding-framing \
  --name onboarding-first-run \
  --per-arm 4 \
  --seed 42
```

`--per-arm 4` 是低成本的第一次試跑（同一 4 個人走兩條臂）。它使用
`.env.local` 裡的人格模型。跑完後：

```bash
uv run matraix experiment list
uv run matraix experiment analyze <experiment_id>
```

`experiments/tasks/` 裡還有：`survey-upgrade-copy`（文案 A/B）、
`survey-trust-by-segment`（比較人群）、`web-compare-options`（網頁 A/B，
需要 Docker）。

真實隊列請匯入
[Persona 1M](https://huggingface.co/datasets/MatrAIx2026/MatrAIx_Persona_1M_Public_Release)：

```bash
huggingface-cli download MatrAIx2026/MatrAIx_Persona_1M_Public_Release \
  --repo-type dataset \
  --local-dir persona/datasets/matraix-persona-1m/release
```

倉庫內的 `matraix-persona-dev-sample`（約 200 人）只用於煙霧測試。

要加自己的研究，複製 `application/tasks/example-*` 或
`experiments/tasks/*`，然後依
[任務指南](../application/task-guide.md) 或
[實驗任務指南](../application/experiment-task-guide.md)。

## 一次執行裡發生什麼

1. **隊列** — 篩選並抽樣人格，然後凍結 ID，以便同一批人以後能見到新版本。
2. **批次** — 一種體驗，試驗彼此隔離。輸出落在
   `jobs/<job_name>/`。
3. **實驗** — 契約展開成各臂並啟動這些作業。
   共享分配讓同一批人跨臂復用；拆分分配則把他們分開。
4. **報告** — 按你指定的指標比較各臂。報告保留
   分母、排除項，以及回到每次試驗的路徑。

## 文件

| | |
|---|---|
| [技術報告](https://matraix.ai/research/matraix-in-the-wild.html) | 這套堆疊為什麼存在，以及研究如何設計 |
| [Quickstart](../quickstart.md) | 第一次執行的分步說明 |
| [實驗任務指南](../application/experiment-task-guide.md) | 編寫比較方案或比較人群實驗 |
| [實驗產物（HF）](../application/hf-experiment-artifacts.md) | 提交凍結隊列和試驗產物（私有資料集） |
| [Agent 與金鑰](../environment/agents.md) | 模型 id 和 API 金鑰 |
| [Handbook](../README.md) | 人格、應用與環境文件 |

```text
application/tasks/       示例任務（問卷、聊天、網頁、OS-app）
experiments/             對照實驗 + 計分卡
persona/                 Schema、資料集、抽樣
environment/             執行時、Agent、Docker / sidecar
application/playground/  視覺化執行器
configs/jobs/            作業配方
jobs/                    本機輸出（gitignored）
```

## 授權

MIT —— 見 [LICENSE](../../LICENSE)。
