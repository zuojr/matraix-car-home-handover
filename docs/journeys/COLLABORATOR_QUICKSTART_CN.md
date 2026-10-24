# Car/Home：官方实验流程交接

本指南用于**新的原生 Harbor 实验**，不是历史结果导入。入口是仓库的 `matraix experiment`（或 Playground Experiments），不要求先运行 journeys 自建协调器。

## 1. 安装与版本

使用 Python 3.13、Git 和可运行 Linux 容器的 Docker Engine/Compose v2。先固定交接分支/标签，并保存 `git rev-parse HEAD`。源码准备和安装会联网下载软件，但不会调用模型。

```sh
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[journeys]'
python -m matraix.journeys setup-native --directory journey-runs/native/SimuHome
export SIMUHOME_ROOT="$(pwd)/journey-runs/native/SimuHome"
docker info
```

Windows 可用 `py -3.13 -m venv .venv` 和 `.venv\Scripts\python.exe`，环境变量用 `$env:NAME = "value"`。原生 Docker 端到端验收以 Linux CI 为准，Docker Desktop/WSL 未据此宣称已验证。短路径能减少 Windows 路径问题。SimuHome 固定 revision 由 setup-native 核验，CAR-bench 固定源码随包提供。

官方启动器在 Linux 优先使用 checkout 的 `.venv/bin/harbor`；请保留上面的虚拟环境步骤。若装在其他位置，通过项目已有的 `MATRIX_HARBOR_BIN` 指向该环境的 Harbor 可执行文件，避免隐式切换到 `uv run` 的另一个环境。Windows 示例：`$env:MATRIX_HARBOR_BIN = (Resolve-Path .venv/Scripts/harbor.exe).Path`。只全局 pip 安装而未配置启动器，不是本文的已验收安装方式。

## 2. Persona 和设计

先用项目 Persona 页面准备/保存原生 cohort，或使用已有 `saved-persona-dataset` / `generated-persona-dev*` pool。每个 pool 必须有 manifest.json 和原始 YAML，路径在 checkout 内。**原库画像全部属性原样保留**，不补值、不改写、不截断。所选身份必须为成人、Mandarin；Car 还要求有驾驶资格/状态。缺少这些字段的开发样例不自动算合格。

十二类任务入口：`experiments/tasks/journeys-car-j1` 至 `journeys-car-j6`、`journeys-home-h1` 至 `journeys-home-h6`。每类的 experiment.json 声明 condition × variant，共八个臂；同一场景使用同一份明确的源 persona ID 名单跨六类任务，不把重复参与当独立身份。

| 条件 | 当前信息披露 | Car 当前优先项 | Home 当前优先项 |
|---|---|---|---|
| C1 | 主动 | 时间 | 舒适 |
| C2 | 按需 | 时间 | 舒适 |
| C3 | 主动 | 避收费 | 较短空调运行时长 |
| C4 | 按需 | 避收费 | 较短空调运行时长 |

条件是任务内赋值，不替换原始画像。变体为 main/boundary。50人 × 8臂 × 六类任务 = 每场景2400例，不是300个独立persona。请自行在采集前固定样本和分析计划；标准通用分析不是旧4800例研究的四项专门推断方案。

## 3. 模型与密钥配置

SUT 是被测基线助手，PUT 是独立上下文的画像用户。两者允许不同服务，但须使用受支持的接口：

- Chat Completions：`POST <BASE_URL>/chat/completions`。SUT 要支持 function tools、tool_choice、完整多工具 call-ID history；PUT 要稳定输出有限 act/style JSON。
- 代码列明的 Sol 模型在 api.openai.com 使用 Responses 适配；须显式填写其支持的 reasoning 配置。
- 其他原生 Messages/GenerateContent/Responses-only 服务需要兼容网关或新的适配器。不能声称任意模型只改名字即可使用。

以下是**配置模板，必须替换占位值**；不要执行正式采集来测试未知接口。

```sh
export MATRIX_COMPUTE_FAMILY=local
export MATRIX_EXECUTION_PLANE=harbor
export JOURNEY_SUT_BASE_URL=https://YOUR-SUT-SERVICE/v1
export JOURNEY_SUT_MODEL=YOUR-SUT-API-MODEL-ID
export JOURNEY_SUT_OPTIONS_JSON='{}'
export JOURNEY_SUT_MAX_TOKENS=16384
export JOURNEY_PUT_BASE_URL=https://YOUR-PUT-SERVICE/v1
export JOURNEY_PUT_MODEL=YOUR-PUT-API-MODEL-ID
export JOURNEY_PUT_OPTIONS_JSON='{"response_format":{"type":"json_object"}}'
export JOURNEY_PUT_MAX_TOKENS=512
export JOURNEY_REQUEST_LIMIT=60000
```

通过本地秘密管理器注入 `JOURNEY_SUT_API_KEY`、`JOURNEY_PUT_API_KEY` 和一个随机 `JOURNEY_CONTROL_TOKEN`。不要把值写进配置、脚本、Git 或聊天。**原生流程使用这些环境变量，不自动加载 `_API_KEY_FILE`**。`--persona-model` 必须与 `JOURNEY_PUT_MODEL` 的实际 API ID 一致；没有隐式 LiteLLM 名称翻译。对只支持特定采样/推理选项的接口，填写其真实选项，不能沿用别家参数。

## 4. 官方启动入口

以下从 root 启动一个任务的八臂实验。`COHORT_DIR` 和 `SOURCE_ID_1 ...` 为你的原生 cohort 相对目录和 ID。

```sh
python -m matraix.cli experiment create experiments/tasks/journeys-car-j4 \
  --persona-pool COHORT_DIR --persona-ids SOURCE_ID_1 SOURCE_ID_2 \
  --persona-model "$JOURNEY_PUT_MODEL" --seed 20261029 \
  --mode force_docker --concurrent 1 --no-parallel-arms
```

由官方 ExperimentService 展开八臂、共享源名单，HarborJobService 在启动前绑定每臂私有任务/计划/compose，然后实际 Harbor 创建 job 和 trial。`--no-parallel-arms --concurrent 8` 的峰值是8个trial；开启并行臂时峰值为8×concurrent，请按机器资源选择，不能把每臂并发误作总并发。

每例单次尝试，Harbor retry=0；SUT最多160请求、PUT最多64轮。所有臂共享该实验的请求账本和停止闸门。API/协议错误停止新增API派发，在途调用排空，保留错误与未知用量；排队的trial可能仍被Harbor创建，但不得继续发API。不要删除锁/账本或用同名job自动续跑。

## 5. 原生产物、读取与导出

- `experiments/runs/<experiment-id>/`：官方实验 manifest。
- `jobs/<job>/config.json,result.json` 及 trial：Harbor实际运行产物。
- trial `verifier/structured_output.json,reward.txt,replay.json`：私有侧车原生回放后产生。
- trial artifacts：公开对话、simulator-records、sut-api-records；PUT收据在 agent 日志。
- `configs/jobs/_generated/journeys/`：**启动前**绑定的任务、完整源画像和模型配置指纹。
- `configs/jobs/_generated/journey-accounting/<experiment-id>/`：跨臂单份账本，不重复累计。

```sh
python -m matraix.cli results JOB_NAME --format json,csv -o journey-runs/exports/JOB_NAME
python -m matraix.cli experiment show EXPERIMENT_ID --format json
python -m matraix.cli experiment analyze EXPERIMENT_ID --format json,csv,pdf -o journey-runs/exports
```

这些使用项目标准读取器/分析器和PDF导出，不调用模型。通用分析的统计方法和校正在输出中列明；脚本化验收的p值没有模型性能意义，不沿用为正式研究结论。成功率看 programmatic_task_success，不看Harbor是否运行结束；H6部分完成单列。Harbor顶层tokens为PUT用量，SUT单独保留收据，不能加两遍；未报告用量/现金费用为null或unknown，不填免费/0，不用公开价推算成实际账单。

## 6. 免费验收与验证范围

在**干净、可丢弃的checkout** 中运行：

```sh
python scripts/validate_journey_harbor.py
```

该脚本要求真实Docker，只创建新的DAG合成验收画像和本机脚本化API，不读key文件，不接付费服务，不读取历史实验。它通过实际官方调度器运行J4八臂，检查job/trial/verifier/多工具调用/用量账本，并执行标准JSON/CSV/PDF导出及容器清理。验收目录已存在会拒绝覆盖，不做resume。

十二类任务、H4协商/授权、温控可达性、上下文隔离、错误停止排空的测试见 `VALIDATION.md`。CI任务 `official-harbor-eight-arm-acceptance` 才是原生端到端证据；参考模式容器检查和schema通过都不能替代它。具体通过情况必须看当前提交的CI，不能引用旧提交成功。

## 7. 排障与协议变化

- 发现任务但不生成job：检查模型options、cohort资格/源文件哈希、显式model ID和Docker运行平面；错误时不会自动回退host协调器。
- 容器构建失败：检查Docker、软件源和固定SimuHome下载。只修依赖问题，不把模型调用失败重发成成功。
- 429/HTTP/无响应：查同一实验账本和每请求receipt，保留failed/unknown。先排空；不自动重试或切模型。
- verifier失败：检查原生源码revision、代码/计划指纹和原始事件；不要手工写reward或重新定义成功。
- 首次完整实验前用自己的服务做独立、明确标记的兼容性pilot；这里的脚本API验收不证明所有真实模型兼容。

当前交互为 structured-journeys-v4 / journey-sidecar-v10。H4现在公开可接受方案、询问不等于同意、按具体操作授权；边界验收与公开0–40%方案范围一致，普通情形仍保护阅读灯和用户偏好。H1/H5动态与评分阈值保持不变。旧冻结包、旧轨迹、旧分数仍属于原版本，不得使用本次修复重新命名历史结果。

只提交代码/任务/配置示例/文档/测试。persona、轨迹、账本、收据、报告均留在独立运行数据目录，不进Git，不属于代码PR。
