<div align="center">
  <h1>MatrAIx in the Wild</h1>
  <p><strong>Arquitetura de simulação de personas e experimentos controlados para decisões do mundo real</strong></p>
  <p>
    <a href="../../README.md">English</a> |
    <a href="README.zh-CN.md">简体中文</a> |
    <a href="README.zh-TW.md">繁體中文</a> |
    <a href="README.ko.md">한국어</a> |
    <a href="README.ja.md">日本語</a> |
    <a href="README.es.md">Español</a> |
    <strong>Português</strong>
  </p>
  <p>
    <a href="https://matraix.ai/"><img alt="Site" src="https://img.shields.io/badge/Website-matraix.ai-4f7cff?style=for-the-badge"></a>
    <a href="https://matraix.ai/research/matraix-in-the-wild.html"><img alt="Relatório técnico" src="https://img.shields.io/badge/Technical%20report-In%20the%20Wild-176b4d?style=for-the-badge"></a>
    <a href="../README.md"><img alt="Docs" src="https://img.shields.io/badge/Docs-Handbook-5b5b5b?style=for-the-badge"></a>
    <a href="https://huggingface.co/datasets/MatrAIx2026/MatrAIx_Persona_1M_Public_Release"><img alt="Hugging Face" src="https://img.shields.io/badge/Hugging%20Face-Persona%201M-ffcc4d?style=for-the-badge"></a>
    <a href="../../LICENSE"><img alt="Licença" src="https://img.shields.io/badge/License-MIT-c33b32?style=for-the-badge"></a>
  </p>
</div>

Este repositório acompanha nosso
[relatório técnico](https://matraix.ai/research/matraix-in-the-wild.html)
sobre simulação de personas para decisões do mundo real. Ele transforma o
comportamento de coortes de personas especificadas em ambientes de produto em
medições repetíveis, e liga num só pipeline a **simulação de usuários**, as
**jornadas de produto** e os **experimentos controlados padrão da indústria**.

A evidência se organiza em quatro unidades encadeadas: um *ensaio* (uma
persona × um estímulo), uma *execução em lote* (uma coorte × um estímulo
fixo), uma *comparação controlada* entre coortes ou estímulos, e um
*relatório padronizado* para a decisão. Cada unidade se mapeia à de baixo,
de modo que um resultado agregado permanece rastreável às observações que o
compõem e às afirmações que aquele nível pode sustentar.

Um estudo congela sua coorte-alvo como um manifesto de personas reutilizável
e então a expõe a pesquisas, chatbots, sites ou apps de sistema sob um
contrato de experimento escrito: o que muda, o que permanece fixo e quais
métricas são primárias, secundárias ou de guarda. A atribuição compartilhada
reutiliza os mesmos IDs de persona entre braços; a atribuição dividida os
parte. O mesmo protocolo pode ser rodado de novo após uma revisão de produto
ou de modelo.

Respostas simuladas não substituem evidência de pessoas reais. Tornam *quem
é simulado* uma parte inspecionável do estudo, e identificam quais
alternativas, quais diferenças entre grupos e quais perguntas em aberto
merecem avaliação humana subsequente. O esquema populacional e o coreset
Persona 1M ficam em
[MatrAIx-Persona-8B](https://github.com/MatrAIx-ai/MatrAIx-Persona-8B).

<p align="center">
  <img src="../assets/matraix-in-the-wild-infrastructure.png" alt="Quatro passos: sintetizar uma coorte, executá-la em lote, opcionalmente um experimento controlado, e produzir um relatório de decisão" width="100%">
</p>

<p align="center"><em>Coorte → execução em lote → experimento controlado → relatório. Cada resultado agregado volta aos ensaios que o produziram.</em></p>

## O que você pode perguntar

Todo estudo é **quem × o quê**: uma coorte ou várias, uma experiência ou
várias versões. Isso dá quatro desenhos. As figuras vêm do
[relatório técnico](https://matraix.ai/research/matraix-in-the-wild.html)
(detalhes omitidos). Elas ilustram o *tipo* de pergunta, não uma tarefa que você precise clonar.

<table>
  <tr>
    <th width="14%" align="center"><sub>quem ↓ · o quê →</sub></th>
    <th width="43%" align="center">Uma experiência</th>
    <th width="43%" align="center">Várias versões</th>
  </tr>
  <tr>
    <th valign="middle" align="center">Uma<br>coorte</th>
    <td valign="top" align="center">
      <img src="../assets/who-what-explore.png" alt="Explorar respostas: uma coorte encontra uma experiência de cadastro" width="100%">
      <br><strong>Explorar respostas</strong><br>
      Como este grupo responde a uma ideia ou experiência?<br>
      <em>Uma execução em lote. Útil para atrito e caudas — não é um efeito por si só.</em>
    </td>
    <td valign="top" align="center">
      <img src="../assets/who-what-compare-alternatives.png" alt="Comparar alternativas: uma coorte vê o original contra um texto mais claro" width="100%">
      <br><strong>Comparar alternativas</strong><br>
      Como este grupo responde a versões diferentes?<br>
      <em>As mesmas pessoas, produto / texto / página diferentes (SUT).</em>
    </td>
  </tr>
  <tr>
    <th valign="middle" align="center">Várias<br>coortes</th>
    <td valign="top" align="center">
      <img src="../assets/who-what-compare-groups.png" alt="Comparar grupos: várias coortes veem a mesma experiência" width="100%">
      <br><strong>Comparar grupos</strong><br>
      Como grupos diferentes respondem à mesma experiência?<br>
      <em>A experiência fica fixa; muda quem é simulado (PUT).</em>
    </td>
    <td valign="top" align="center">
      <img src="../assets/who-what-crossed.png" alt="Comparar alternativas entre grupos: versões cruzadas com coortes" width="100%">
      <br><strong>Comparar alternativas entre grupos</strong><br>
      Qual versão funciona melhor para qual grupo?<br>
      <em>Os dois eixos variam.</em>
    </td>
  </tr>
</table>

O primeiro experimento abaixo é **Comparar alternativas**. Os exemplares de
pesquisa e web dessa célula (e de Comparar grupos) estão em `experiments/tasks/`.

## Comece aqui

Você precisa de [uv](https://docs.astral.sh/uv/) e Python 3.12. Node 20+ é só
para o Playground. Docker é só para tarefas web / OS-app — não para o
experimento de pesquisa abaixo. No Windows use
[WSL2](https://learn.microsoft.com/windows/wsl/install) e clone dentro do
sistema de arquivos Linux (não em `/mnt/c/…`).

```bash
git clone https://github.com/MatrAIx-ai/MatrAIx_in_the_Wild.git
cd MatrAIx_in_the_Wild
uv venv --python 3.12
uv pip install -e .
uv pip install -e packages/playground
uv pip install -e packages/harbor-langsmith
uv pip install -e packages/rewardkit
```

Copie `application/playground/.env.local.example` para
`application/playground/.env.local` e acrescente uma chave. O arquivo de
exemplo usa por padrão `anthropic/claude-haiku-4-5` (`ANTHROPIC_API_KEY`).
Outros prefixos (`ppapi/…`, `dashscope/…`, `openai/…`) estão em
[agents.md](../environment/agents.md).

Confirme a instalação (sem chave):

```bash
uv run matraix smoke application/tasks/example-survey_product-feedback
```

Você deve ver `Smoke: ok`. Passo a passo mais longo:
[quickstart](../quickstart.md).

### 1. Playground — rode um experimento na interface

```bash
# Terminal A
VENV=.venv bash application/playground/backend/run_dev.sh

# Terminal B
cd application/playground/frontend && npm ci && npm run dev
```

Abra http://localhost:5173 → **Experiments** → **New experiment** →
[`survey-onboarding-framing`](../../experiments/tasks/survey-onboarding-framing/)
→ **Configure & Run** → escolha uma coorte pequena → **Launch 2-arm experiment**.

As mesmas pessoas veem onboarding enquadrado por funcionalidade e por
resultado. Satisfação é a métrica primária; esforço percebido é a guarda.

### 2. CLI — o mesmo experimento

```bash
uv run matraix experiment create experiments/tasks/survey-onboarding-framing \
  --name onboarding-first-run \
  --per-arm 4 \
  --seed 42
```

`--per-arm 4` é uma primeira passada barata (as mesmas 4 pessoas nos dois
braços). Usa o modelo de persona de `.env.local`. Quando terminar:

```bash
uv run matraix experiment list
uv run matraix experiment analyze <experiment_id>
```

Também em `experiments/tasks/`: `survey-upgrade-copy` (A/B de texto),
`survey-trust-by-segment` (comparar grupos), `web-compare-options` (A/B web,
precisa de Docker).

Para uma coorte real, importe
[Persona 1M](https://huggingface.co/datasets/MatrAIx2026/MatrAIx_Persona_1M_Public_Release):

```bash
huggingface-cli download MatrAIx2026/MatrAIx_Persona_1M_Public_Release \
  --repo-type dataset \
  --local-dir persona/datasets/matraix-persona-1m/release
```

O `matraix-persona-dev-sample` do repositório (~200 pessoas) é só para fumaça.

Para acrescentar o seu estudo, copie `application/tasks/example-*` ou
`experiments/tasks/*` e siga o
[guia de tarefas](../application/task-guide.md) ou o
[guia de tarefas de experimento](../application/experiment-task-guide.md).

## O que acontece numa execução

1. **Coorte** — filtre e amostre personas, depois congele os IDs para que as
   mesmas pessoas possam encontrar uma versão nova depois.
2. **Lote** — uma experiência, ensaios isolados. As saídas ficam em
   `jobs/<job_name>/`.
3. **Experimento** — o contrato se desdobra em braços e dispara esses jobs.
   A atribuição compartilhada reutiliza as mesmas pessoas entre braços; a
   atribuição dividida as separa.
4. **Relatório** — os braços são comparados nas métricas que você nomeou. O
   relatório guarda denominadores, exclusões e um caminho de volta a cada ensaio.

## Docs

| | |
|---|---|
| [Relatório técnico](https://matraix.ai/research/matraix-in-the-wild.html) | Por que esta stack existe, e como os estudos são desenhados |
| [Quickstart](../quickstart.md) | Primeira execução, passo a passo |
| [Guia de tarefas de experimento](../application/experiment-task-guide.md) | Escreva um experimento de comparar alternativas ou comparar grupos |
| [Artefatos de experimento (HF)](../application/hf-experiment-artifacts.md) | Envie uma coorte congelada e os artefatos dos ensaios (dataset privado) |
| [Agentes e chaves](../environment/agents.md) | Ids de modelo e chaves de API |
| [Handbook](../README.md) | Docs de persona, aplicação e ambiente |

```text
application/tasks/       Tarefas de exemplo (pesquisa, chat, web, OS-app)
experiments/             Experimentos controlados + scorecard
persona/                 Esquema, datasets, amostragem
environment/             Runtime, agentes, Docker / sidecars
application/playground/  Runner visual
configs/jobs/            Receitas de jobs
jobs/                    Saídas locais (gitignored)
```

## Licença

MIT — veja [LICENSE](../../LICENSE).
