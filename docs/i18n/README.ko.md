<div align="center">
  <h1>MatrAIx in the Wild</h1>
  <p><strong>현실 세계 의사결정을 위한 페르소나 시뮬레이션 통제 실험 아키텍처</strong></p>
  <p>
    <a href="../../README.md">English</a> |
    <a href="README.zh-CN.md">简体中文</a> |
    <a href="README.zh-TW.md">繁體中文</a> |
    <strong>한국어</strong> |
    <a href="README.ja.md">日本語</a> |
    <a href="README.es.md">Español</a> |
    <a href="README.pt-BR.md">Português</a>
  </p>
  <p>
    <a href="https://matraix.ai/"><img alt="웹사이트" src="https://img.shields.io/badge/Website-matraix.ai-4f7cff?style=for-the-badge"></a>
    <a href="https://matraix.ai/research/matraix-in-the-wild.html"><img alt="기술 보고서" src="https://img.shields.io/badge/Technical%20report-In%20the%20Wild-176b4d?style=for-the-badge"></a>
    <a href="../README.md"><img alt="문서" src="https://img.shields.io/badge/Docs-Handbook-5b5b5b?style=for-the-badge"></a>
    <a href="https://huggingface.co/datasets/MatrAIx2026/MatrAIx_Persona_1M_Public_Release"><img alt="Hugging Face" src="https://img.shields.io/badge/Hugging%20Face-Persona%201M-ffcc4d?style=for-the-badge"></a>
    <a href="../../LICENSE"><img alt="라이선스" src="https://img.shields.io/badge/License-MIT-c33b32?style=for-the-badge"></a>
  </p>
</div>

이 저장소는 현실 세계의 의사결정을 위한 페르소나 시뮬레이션에 관한
[기술 보고서](https://matraix.ai/research/matraix-in-the-wild.html)를
동반합니다. 지정된 페르소나 코호트가 제품 환경에서 보이는 행동을 반복
가능한 측정으로 바꾸며, 하나의 파이프라인에서 **사용자 시뮬레이션**,
**제품 여정**, **업계 표준의 통제 실험**을 연결합니다.

증거는 네 개의 연결된 단위로 조직됩니다. *시행*(페르소나 하나 × 자극 하나),
*배치 실행*(코호트 하나 × 고정 자극 하나), 코호트 또는 자극을 가로지르는
*통제 비교*, 그리고 의사결정을 위한 *표준화 보고서*. 각 단위는 아래 단위에
대응하므로, 집계 결과는 구성 관측과 그 수준이 지지할 수 있는 주장까지
추적됩니다.

연구는 목표 코호트를 재사용 가능한 페르소나 매니페스트로 고정한 뒤, 서면
실험 계약 아래에서 설문, 챗봇, 웹사이트, OS 앱에 노출합니다. 무엇이
바뀌고, 무엇이 고정되는지, 어떤 지표가 주·부·가드레일인지입니다. 공유
배정은 팔 사이에 같은 페르소나 ID를 재사용하고, 분할 배정은 그들을
나눕니다. 제품이나 모델이 바뀐 뒤에도 같은 프로토콜을 다시 실행할 수
있습니다.

시뮬레이션 응답은 실제 사람의 증거를 대체하지 않습니다. *누구를
시뮬레이션하는지*를 연구의 검사 가능한 부분으로 만들고, 어떤 대안, 어떤
집단 차이, 어떤 열린 질문이 이어질 사람 평가에 값어치 있는지를
가리킵니다. 기반 인구 스키마와 Persona 1M 코어셋은
[MatrAIx-Persona-8B](https://github.com/MatrAIx-ai/MatrAIx-Persona-8B)에
있습니다.

<p align="center">
  <img src="../assets/matraix-in-the-wild-infrastructure.png" alt="네 단계: 코호트 합성, 배치 실행, 선택적 통제 실험, 의사결정 보고서" width="100%">
</p>

<p align="center"><em>코호트 → 배치 실행 → 통제 실험 → 보고서. 집계 결과는 각각 그것을 만든 시행으로 돌아갑니다.</em></p>

## 무엇을 물을 수 있나

모든 연구는 **누구 × 무엇**입니다. 코호트 하나 또는 여러 개, 경험 하나
또는 여러 버전. 그래서 설계는 네 가지입니다. 그림은
[기술 보고서](https://matraix.ai/research/matraix-in-the-wild.html)에서
가져왔습니다(세부 생략). 복제해야 하는 태스크가 아니라, 질문의 *종류*를 보여 줍니다.

<table>
  <tr>
    <th width="14%" align="center"><sub>누구 ↓ · 무엇 →</sub></th>
    <th width="43%" align="center">경험 하나</th>
    <th width="43%" align="center">버전 여러 개</th>
  </tr>
  <tr>
    <th valign="middle" align="center">코호트<br>하나</th>
    <td valign="top" align="center">
      <img src="../assets/who-what-explore.png" alt="반응 살펴보기: 코호트 하나가 가입 경험 하나를 만남" width="100%">
      <br><strong>반응 살펴보기</strong><br>
      이 집단은 아이디어나 경험에 어떻게 반응하는가?<br>
      <em>배치 실행입니다. 마찰과 꼬리를 보는 데 유용하고, 그 자체로 효과는 아닙니다.</em>
    </td>
    <td valign="top" align="center">
      <img src="../assets/who-what-compare-alternatives.png" alt="대안 비교: 코호트 하나가 원문과 더 분명한 문구를 봄" width="100%">
      <br><strong>대안 비교</strong><br>
      이 집단은 서로 다른 버전에 어떻게 반응하는가?<br>
      <em>같은 사람, 다른 제품 / 카피 / 페이지 (SUT).</em>
    </td>
  </tr>
  <tr>
    <th valign="middle" align="center">코호트<br>여러 개</th>
    <td valign="top" align="center">
      <img src="../assets/who-what-compare-groups.png" alt="집단 비교: 여러 코호트가 같은 경험을 봄" width="100%">
      <br><strong>집단 비교</strong><br>
      서로 다른 집단은 같은 경험에 어떻게 반응하는가?<br>
      <em>경험은 고정, 누구를 시뮬레이션하는지가 바뀝니다 (PUT).</em>
    </td>
    <td valign="top" align="center">
      <img src="../assets/who-what-crossed.png" alt="집단을 가로질러 대안 비교: 버전과 코호트를 교차" width="100%">
      <br><strong>집단을 가로질러 대안 비교</strong><br>
      어떤 버전이 어떤 집단에 더 나은가?<br>
      <em>두 축이 모두 변합니다.</em>
    </td>
  </tr>
</table>

아래 첫 실험은 **대안 비교**입니다. 그 칸(그리고 집단 비교)의 설문·웹
예시는 `experiments/tasks/`에 있습니다.

## 여기서 시작

[uv](https://docs.astral.sh/uv/)와 Python 3.12가 필요합니다. Node 20+는
Playground에만 필요합니다. Docker는 웹 / OS-app 태스크에만 필요하고, 아래
설문 실험에는 필요 없습니다. Windows에서는
[WSL2](https://learn.microsoft.com/windows/wsl/install)를 쓰고 Linux
파일시스템 안에 clone하세요 (`/mnt/c/…` 아님).

```bash
git clone https://github.com/MatrAIx-ai/MatrAIx_in_the_Wild.git
cd MatrAIx_in_the_Wild
uv venv --python 3.12
uv pip install -e .
uv pip install -e packages/playground
uv pip install -e packages/harbor-langsmith
uv pip install -e packages/rewardkit
```

`application/playground/.env.local.example`을
`application/playground/.env.local`로 복사하고 키를 넣으세요. 예시 파일의
기본값은 `anthropic/claude-haiku-4-5`(`ANTHROPIC_API_KEY`)입니다. 다른 접두사
(`ppapi/…`, `dashscope/…`, `openai/…`)는
[agents.md](../environment/agents.md)에 있습니다.

설치 확인(키 없음):

```bash
uv run matraix smoke application/tasks/example-survey_product-feedback
```

`Smoke: ok`가 보여야 합니다. 더 긴 안내:
[quickstart](../quickstart.md).

### 1. Playground — UI에서 실험 실행

```bash
# 터미널 A
VENV=.venv bash application/playground/backend/run_dev.sh

# 터미널 B
cd application/playground/frontend && npm ci && npm run dev
```

http://localhost:5173 → **Experiments** → **New experiment** →
[`survey-onboarding-framing`](../../experiments/tasks/survey-onboarding-framing/)
→ **Configure & Run** → 작은 코호트를 고름 → **Launch 2-arm experiment**.

같은 사람이 기능 프레이밍과 성과 프레이밍 온보딩을 봅니다. 만족도가 주
지표이고, 체감 노력은 가드레일입니다.

### 2. CLI — 같은 실험

```bash
uv run matraix experiment create experiments/tasks/survey-onboarding-framing \
  --name onboarding-first-run \
  --per-arm 4 \
  --seed 42
```

`--per-arm 4`는 싼 첫 실행입니다(같은 4명이 두 팔에). `.env.local`의
페르소나 모델을 씁니다. 끝나면:

```bash
uv run matraix experiment list
uv run matraix experiment analyze <experiment_id>
```

`experiments/tasks/`에도 있습니다. `survey-upgrade-copy`(카피 A/B),
`survey-trust-by-segment`(집단 비교), `web-compare-options`(웹 A/B,
Docker 필요).

실제 코호트는
[Persona 1M](https://huggingface.co/datasets/MatrAIx2026/MatrAIx_Persona_1M_Public_Release)을
가져오세요:

```bash
huggingface-cli download MatrAIx2026/MatrAIx_Persona_1M_Public_Release \
  --repo-type dataset \
  --local-dir persona/datasets/matraix-persona-1m/release
```

저장소의 `matraix-persona-dev-sample`(약 200명)은 스모크 전용입니다.

자기 연구를 추가하려면 `application/tasks/example-*` 또는
`experiments/tasks/*`를 복사한 뒤
[태스크 가이드](../application/task-guide.md) 또는
[실험 태스크 가이드](../application/experiment-task-guide.md)를 따르세요.

## 한 번의 실행에서 일어나는 일

1. **코호트** — 페르소나를 거르고 샘플한 뒤 ID를 고정해, 같은 사람이
   나중에 새 버전을 만날 수 있게 합니다.
2. **배치** — 경험 하나, 격리된 시행. 출력은
   `jobs/<job_name>/`에 있습니다.
3. **실험** — 계약이 팔로 펼쳐지고 그 잡이 시작됩니다.
   공유 배정은 같은 사람을 팔 사이에 재사용하고, 분할 배정은 사람을 나눕니다.
4. **보고서** — 지정한 지표로 팔을 비교합니다. 보고서는
   분모, 제외, 각 시행으로 돌아가는 경로를 남깁니다.

## 문서

| | |
|---|---|
| [기술 보고서](https://matraix.ai/research/matraix-in-the-wild.html) | 이 스택이 왜 있는지, 연구를 어떻게 설계하는지 |
| [Quickstart](../quickstart.md) | 첫 실행을 단계별로 |
| [실험 태스크 가이드](../application/experiment-task-guide.md) | 대안 비교 또는 집단 비교 실험 작성 |
| [실험 산출물 (HF)](../application/hf-experiment-artifacts.md) | 고정 코호트와 시행 산출물 제출(비공개 데이터셋) |
| [에이전트와 키](../environment/agents.md) | 모델 id와 API 키 |
| [Handbook](../README.md) | 페르소나, 애플리케이션, 환경 문서 |

```text
application/tasks/       예시 태스크 (설문, 채팅, 웹, OS-app)
experiments/             통제 실험 + 스코어카드
persona/                 스키마, 데이터셋, 샘플링
environment/             런타임, 에이전트, Docker / sidecar
application/playground/  시각 러너
configs/jobs/            잡 레시피
jobs/                    로컬 출력 (gitignored)
```

## 라이선스

MIT — [LICENSE](../../LICENSE).
