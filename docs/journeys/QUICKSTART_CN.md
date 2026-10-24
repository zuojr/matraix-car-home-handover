# 独立host协调器工具（非原生实验入口）

新实验请使用 [官方Harbor交接](COLLABORATOR_QUICKSTART_CN.md)。以下独立工具不表示官方实验链已接通。

# Car/Home：正式冻结、输出与可选 Harbor 路径

第一次接自己的模型 API，请先完成[合作者入口](COLLABORATOR_QUICKSTART_CN.md)：
安装 Python 3.13、固定原生源码、配置角色密钥、零请求检查、内置16例接口验证和完整 pilot。
这里的命令均从仓库根目录执行；每次使用新目录，替换实际的来源路径、IDs 与模型配置。
本指南不会自动启动任何实验。

## 1. 正式计划

先固定获准的抽样框、原始身份名单、排除规则与样本量。不按结果挑人，不把开发验证
画像混入正式样本，不推断补齐缺失属性。各源 persona 保留六任务、四条件、两变体。
以下命令只准备本地文件，不调用模型；一行可在 PowerShell/Linux shell 使用：

```sh
python -m matraix.journeys prepare --repo . --purpose formal --car-pool persona/datasets/YOUR_CAR_POOL --car-ids CAR_ID1 CAR_ID2 --home-pool persona/datasets/YOUR_HOME_POOL --home-ids HOME_ID1 HOME_ID2 --out journey-runs/formal-plan
```

示例 IDs 必须替换为完整名单。两人仅说明命令语法，不满足正式统计门槛。
复制 `configs/journeys/formal-spec.template.json` 到私有研究目录，填写与实际计划匹配的
来源数、审批说明和统计设计。模板的 `approved=false` 不代替研究负责人批准。
程序至少20个源 persona/场景的限制是技术门槛，默认50也不是功效保证。

## 2. 冻结与执行

```sh
python -m matraix.journeys freeze --plan journey-runs/formal-plan --config journey-runs/my-model.json --spec journey-runs/approved-formal-spec.json --out journey-runs/formal-frozen
```

冻结生成新目录，绑定原始来源、代码、模型/API选项、交互预算、并发和统计方案。
不能手改冻结目录、复用其他模型的计划或解除旧锁。确认来源和真实调用授权后，以下
命令才会发送完整画像及任务并产生费用：

```sh
python -m matraix.journeys execute --plan journey-runs/formal-frozen --config journey-runs/my-model.json --out journey-runs/formal-run --execute
```

凭据按合作者入口的角色环境变量读取，不写入 JSON。PowerShell 可选包装：

```powershell
.\scripts\run_journeys.ps1 -Plan journey-runs/formal-frozen -Config journey-runs/my-model.json -Output journey-runs/formal-run -Execute
```

只启动一个协调器。API/429/协议错误停止新派发并排空，保留失败、缺失、未知用量和
未尝试计数；不自动重试、续跑或切模型。诊断前先核对 STOP、completion、账本和服务退出。
续跑未尝试案例需要单独授权，见 [RECOVERY_CN.md](RECOVERY_CN.md)。

## 3. 输出与离线汇总

| 内容 | 相对运行目录的位置 |
|---|---|
| 计划、来源和哈希 | `plan/` |
| 无密钥配置、环境版本 | `settings.json`、`environment.json` |
| PUT动作与公共对话 | `actor/<case>/` |
| SUT请求、工具批次、回复和回执 | `sut-api-records/` |
| 原生事件、检查点和最终状态 | `records/` |
| 独立回放、标准评分 envelope | `verifier/` |
| 停止/完成、固定分母及请求账本 | `completion.json`、`requests.sqlite3` |
| 服务退出、内存、用量与耗时 | `service_lifecycle.json`、`memory.json`、`resources.json` |
| 程序结果及简明报告 | `analysis/descriptive.json`、`REPORT_CN.md` |

```sh
python -m matraix.journeys analyze --plan journey-runs/formal-frozen --records journey-runs/formal-run/records --out journey-runs/formal-analysis
```

分析不调用模型。主成功率为已确认完整成功/全部计划案例，部分完成、技术缺失和
未尝试分别列出。缺失[0,1]是识别范围，不是置信区间。总体先看四个预定对照，再看
各任务与轨迹；独立单位是源 persona。推断仅在批准的固定最终检查和完整性/已知用量
门槛满足时运行。方法、比较和限制见 [RESEARCH_FRAME_CN.md](RESEARCH_FRAME_CN.md)。

## 4. 可选 Harbor/容器路径

```sh
python -m matraix.journeys materialize --repo .
python -m matraix.journeys resolve-harbor --repo . --plan journey-runs/my-model-pilot-plan --out journey-runs/harbor-pilot --put-model YOUR_ACTUAL_PUT_API_ID
harbor run -c journey-runs/harbor-pilot/recipes/CASE_ID.yaml
```

`CASE_ID`替换为生成 recipe 文件名。此路径需要 Docker、Harbor 和对应 API 配置，
适用于 pilot；复用标准 shared-chat-persona 环境及私有 sidecar overlay。
正式采集使用 `execute`，确保双角色同账本和冻结配置核验。
架构与隔离边界见 [HANDOVER.md](HANDOVER.md)，离线检查见 [VALIDATION.md](VALIDATION.md)。

## 5. 本地打包

`release-local`可验证和打包合格研究输出，拒绝把API验证/参考模式制品当实验发布。
它不证明符合外部数据集的实际上传规范。公开前单独核对目标说明、许可、秘密与访问权限；
不要把原画像、轨迹、收据或密钥提交到 Git。
