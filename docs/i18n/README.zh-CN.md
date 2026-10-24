<div align="center">
  <h1>MatrAIx in the Wild</h1>
  <p><strong>面向真实世界决策的人格模拟控制实验架构</strong></p>
  <p>
    <a href="../../README.md">English</a> |
    <strong>简体中文</strong> |
    <a href="README.zh-TW.md">繁體中文</a> |
    <a href="README.ko.md">한국어</a> |
    <a href="README.ja.md">日本語</a> |
    <a href="README.es.md">Español</a> |
    <a href="README.pt-BR.md">Português</a>
  </p>
  <p>
    <a href="https://matraix.ai/"><img alt="网站" src="https://img.shields.io/badge/Website-matraix.ai-4f7cff?style=for-the-badge"></a>
    <a href="https://matraix.ai/research/matraix-in-the-wild.html"><img alt="技术报告" src="https://img.shields.io/badge/Technical%20report-In%20the%20Wild-176b4d?style=for-the-badge"></a>
    <a href="../README.md"><img alt="文档" src="https://img.shields.io/badge/Docs-Handbook-5b5b5b?style=for-the-badge"></a>
    <a href="https://huggingface.co/datasets/MatrAIx2026/MatrAIx_Persona_1M_Public_Release"><img alt="Hugging Face" src="https://img.shields.io/badge/Hugging%20Face-Persona%201M-ffcc4d?style=for-the-badge"></a>
    <a href="../../LICENSE"><img alt="许可证" src="https://img.shields.io/badge/License-MIT-c33b32?style=for-the-badge"></a>
  </p>
</div>

本仓库伴随我们关于面向真实世界决策的人格模拟的
[技术报告](https://matraix.ai/research/matraix-in-the-wild.html)。
它把指定人格队列在产品环境中的行为转化为可重复的测量，在一条管线中连接
**用户模拟**、**产品旅程**与**业界标准的对照实验**。

证据组织为四个相连的单位：*试验*（一个人格 × 一种刺激）、*批量运行*
（一个队列 × 一种固定刺激）、跨队列或跨刺激的*对照比较*，以及面向决策的
*标准化报告*。每个单位都映射到下一层，因此汇总结果可追溯到构成它的观测，
以及该层能够支持的主张。

一项研究先将其目标队列冻结为可复用的人格清单，再在书面实验契约下将该队列
置于问卷、聊天机器人、网站或操作系统应用中——什么可变、什么保持不变，以及
哪些指标是主指标、次指标或护栏。共享分配在各臂之间复用同一批人格 ID；拆分
分配则将他们分区。产品或模型修订后，同一协议可重跑。

模拟响应不能替代来自真人的证据。它们使*被模拟的是谁*成为研究中可检查的一部分，
并指出哪些方案、哪些人群差异、哪些未解问题值得后续真人评估。底层人口 Schema
与 Persona 1M 核心集在
[MatrAIx-Persona-8B](https://github.com/MatrAIx-ai/MatrAIx-Persona-8B)。

<p align="center">
  <img src="../assets/matraix-in-the-wild-infrastructure.png" alt="四步：合成队列、批量运行、可选的对照实验，然后产出决策报告" width="100%">
</p>

<p align="center"><em>队列 → 批量运行 → 对照实验 → 报告。每个汇总结果都能回到产生它的试验。</em></p>

## 你可以问什么

每项研究都是**谁 × 什么**：一批人或几批人，一种体验或几种版本。这样就有四种设计。图来自
[技术报告](https://matraix.ai/research/matraix-in-the-wild.html)
（细节略去）。它们说明的是问题的*类型*，不是必须照抄的任务。

<table>
  <tr>
    <th width="14%" align="center"><sub>谁 ↓ · 什么 →</sub></th>
    <th width="43%" align="center">一种体验</th>
    <th width="43%" align="center">几种版本</th>
  </tr>
  <tr>
    <th valign="middle" align="center">一批人</th>
    <td valign="top" align="center">
      <img src="../assets/who-what-explore.png" alt="看反应：一批人遇到同一种注册体验" width="100%">
      <br><strong>看反应</strong><br>
      这批人对一个想法或体验会怎么反应？<br>
      <em>一次批量运行。适合看摩擦和尾部——本身还不是效应。</em>
    </td>
    <td valign="top" align="center">
      <img src="../assets/who-what-compare-alternatives.png" alt="比较方案：一批人看到原文与更清楚的措辞" width="100%">
      <br><strong>比较方案</strong><br>
      这批人对不同版本会怎么反应？<br>
      <em>同一批人，不同的产品 / 文案 / 页面（SUT）。</em>
    </td>
  </tr>
  <tr>
    <th valign="middle" align="center">几批人</th>
    <td valign="top" align="center">
      <img src="../assets/who-what-compare-groups.png" alt="比较人群：几批人看到同一种体验" width="100%">
      <br><strong>比较人群</strong><br>
      不同的人面对同一体验会怎么反应？<br>
      <em>体验固定；变的是模拟的是谁（PUT）。</em>
    </td>
    <td valign="top" align="center">
      <img src="../assets/who-what-crossed.png" alt="跨人群比较方案：版本与队列交叉" width="100%">
      <br><strong>跨人群比较方案</strong><br>
      哪个版本对哪批人更好？<br>
      <em>两个轴都变。</em>
    </td>
  </tr>
</table>

下面的第一个实验是**比较方案**。该格（以及比较人群）的问卷和网页示例在 `experiments/tasks/`。

## 从这里开始

需要 [uv](https://docs.astral.sh/uv/) 和 Python 3.12。Node 20+ 只给 Playground 用。Docker 只给网页 / OS-app 任务用——下面的问卷实验不需要。Windows 请用
[WSL2](https://learn.microsoft.com/windows/wsl/install)，并把仓库 clone 到 Linux 文件系统里（不要放在 `/mnt/c/…`）。

```bash
git clone https://github.com/MatrAIx-ai/MatrAIx_in_the_Wild.git
cd MatrAIx_in_the_Wild
uv venv --python 3.12
uv pip install -e .
uv pip install -e packages/playground
uv pip install -e packages/harbor-langsmith
uv pip install -e packages/rewardkit
```

把 `application/playground/.env.local.example` 复制为
`application/playground/.env.local` 并填入密钥。示例文件默认
`anthropic/claude-haiku-4-5`（`ANTHROPIC_API_KEY`）。其他前缀
（`ppapi/…`、`dashscope/…`、`openai/…`）见
[agents.md](../environment/agents.md)。

确认安装（不需要密钥）：

```bash
uv run matraix smoke application/tasks/example-survey_product-feedback
```

应看到 `Smoke: ok`。更长的步骤说明：
[quickstart](../quickstart.md)。

### 1. Playground —— 在界面里跑实验

```bash
# 终端 A
VENV=.venv bash application/playground/backend/run_dev.sh

# 终端 B
cd application/playground/frontend && npm ci && npm run dev
```

打开 http://localhost:5173 → **Experiments** → **New experiment** →
[`survey-onboarding-framing`](../../experiments/tasks/survey-onboarding-framing/)
→ **Configure & Run** → 选一个小队列 → **Launch 2-arm experiment**。

同一批人分别看到功能导向和结果导向的引导。满意度是主指标；感知费力程度是护栏。

### 2. CLI —— 同一个实验

```bash
uv run matraix experiment create experiments/tasks/survey-onboarding-framing \
  --name onboarding-first-run \
  --per-arm 4 \
  --seed 42
```

`--per-arm 4` 是低成本的第一次试跑（同一 4 个人走两条臂）。它使用
`.env.local` 里的人格模型。跑完后：

```bash
uv run matraix experiment list
uv run matraix experiment analyze <experiment_id>
```

`experiments/tasks/` 里还有：`survey-upgrade-copy`（文案 A/B）、
`survey-trust-by-segment`（比较人群）、`web-compare-options`（网页 A/B，
需要 Docker）。

真实队列请导入
[Persona 1M](https://huggingface.co/datasets/MatrAIx2026/MatrAIx_Persona_1M_Public_Release)：

```bash
huggingface-cli download MatrAIx2026/MatrAIx_Persona_1M_Public_Release \
  --repo-type dataset \
  --local-dir persona/datasets/matraix-persona-1m/release
```

仓库内的 `matraix-persona-dev-sample`（约 200 人）只用于冒烟。

要加自己的研究，复制 `application/tasks/example-*` 或
`experiments/tasks/*`，然后按
[任务指南](../application/task-guide.md) 或
[实验任务指南](../application/experiment-task-guide.md)。

## 一次运行里发生什么

1. **队列** — 筛选并抽样人格，然后冻结 ID，以便同一批人以后能见到新版本。
2. **批量** — 一种体验，试验彼此隔离。输出落在
   `jobs/<job_name>/`。
3. **实验** — 契约展开成各臂并启动这些作业。
   共享分配让同一批人跨臂复用；拆分分配则把他们分开。
4. **报告** — 按你指定的指标比较各臂。报告保留
   分母、排除项，以及回到每次试验的路径。

## 文档

| | |
|---|---|
| [技术报告](https://matraix.ai/research/matraix-in-the-wild.html) | 这套栈为什么存在，以及研究如何设计 |
| [Quickstart](../quickstart.md) | 第一次运行的分步说明 |
| [实验任务指南](../application/experiment-task-guide.md) | 编写比较方案或比较人群实验 |
| [实验产物（HF）](../application/hf-experiment-artifacts.md) | 提交冻结队列和试验产物（私有数据集） |
| [Agent 与密钥](../environment/agents.md) | 模型 id 和 API 密钥 |
| [Handbook](../README.md) | 人格、应用与环境文档 |

```text
application/tasks/       示例任务（问卷、聊天、网页、OS-app）
experiments/             对照实验 + 记分卡
persona/                 Schema、数据集、抽样
environment/             运行时、Agent、Docker / sidecar
application/playground/  可视化运行器
configs/jobs/            作业配方
jobs/                    本地输出（gitignored）
```

## 许可证

MIT —— 见 [LICENSE](../../LICENSE)。
