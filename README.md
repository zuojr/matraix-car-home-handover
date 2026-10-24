# Car/Home public handover

独立公开的 Car/Home 实验代码交接仓库。包含运行所需的 MatrAIx 源码、六类车机与六类 Home 任务、Harbor 原生调度适配、sidecar、程序评分、测试和安装说明。

**开始运行：[中文交接指南](docs/journeys/COLLABORATOR_QUICKSTART_CN.md)。**
**架构与接口：[HANDOVER.md](docs/journeys/HANDOVER.md)。**

```sh
git clone https://github.com/zuojr/matraix-car-home-handover.git
cd matraix-car-home-handover
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[journeys]'
```

然后按交接指南准备固定的 SimuHome 源码、Docker、自己的完整原生 persona cohort，以及 SUT/PUT 模型配置。使用项目标准 `matraix experiment` 入口。新模型须先验证接口兼容性，不能只改名字就假设支持。

免费基础设施验收（干净、可丢弃 checkout；需要 Linux Docker）：

```sh
python scripts/validate_journey_harbor.py
```

脚本使用本机受控 API，不需要真实模型密钥、不调用付费模型，实际创建八臂 Harbor job/trial 并验证标准读取、JSON/CSV/PDF 导出、多工具调用、用量和错误停止排空。CI见 [Actions](https://github.com/zuojr/matraix-car-home-handover/actions/workflows/journey-sidecars.yml)。这不证明任意真实模型或 Windows Docker/云运行已经验证。

本仓库从已验证源提交 `9e432e33f868170915ecde0b1b16e27b3cb8e3e1` 创建新的独立历史。原私有 fork 和 PR #15 保持不变。任务、运行、评分核心实现与该源提交一致；公开版只调整交接入口、CI触发和数据排除。详见 [公开快照说明](docs/journeys/PUBLIC_HANDOVER.md)。

没有正式实验数据、真实研究 persona、轨迹、收据、账本、报告或密钥。保留的 `matraix-persona-dev-sample` 是固定 seed 的合成开发测试样例，供代码测试，不是正式研究的100个源persona。合作者自行准备研究样本和密钥。运行输出保留本地，不提交Git。

MIT 许可与各 vendored 原生环境的许可/来源声明均保留。更多上游平台介绍见 [README_UPSTREAM.md](README_UPSTREAM.md)。
