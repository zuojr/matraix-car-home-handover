# 显式继续未尝试案例

普通 `execute` 不会自动续跑。此工具只用于研究负责人明确授权的调度修订：
保留原冻结计划、配置和全部旧证据，继续从未尝试的案例。它不重试失败、partial
或已尝试但无终态的案例，不重置平台配额，也不改变评分与统计门槛。

## 准备前

先确认原协调器和服务完全退出、账本没有在途请求，并记录停止原因。原输出与冻结目录
保持只读。先生成 `ORIGINAL_RUN` 全部文件的 SHA256 清单，格式为
`{"files":{"相对原run的路径":"文件SHA256"}}`，保存于原run父目录的
`STOPPED_RAW_PRESERVATION_MANIFEST.json`。清单不能放在原run内，否则产生自引用。
授权JSON必须包含以下字段，哈希和数量由操作者从封存元数据取得并经负责人批准：

```json
{
  "authorized": true,
  "scope": "never_attempted_only",
  "plan_sha256": "CANONICAL_PLAN_DIGEST",
  "preservation_manifest_sha256": "PRESERVATION_FILE_SHA256",
  "statistics_unchanged": true,
  "retry": false,
  "expected_unattempted": 1
}
```

这里的1仅为格式示例，必须替换为真实未尝试数；`authorized`只能反映实际批准。
`plan_sha256`使用 `matraix.journeys.cohort.digest(load_plan(path))` 的规范化摘要，
不是直接对 plan.json 字节取SHA；封存清单哈希则使用文件原始字节。
工具会验证每个字段及封存文件；测试见 `tests/unit/matraix/test_journeys_recovery.py`。
同一依赖环境及固定原生源码必须可用，`SIMUHOME_ROOT`须正确。

```text
python scripts/journey_recovery.py prepare --plan ORIGINAL_FROZEN --prior ORIGINAL_RUN --config ORIGINAL_SETTINGS --amendment APPROVED_AMENDMENT_JSON --out NEW_RECOVERY_ROOT
python scripts/journey_recovery.py execute --recovery NEW_RECOVERY_ROOT --config NEW_RECOVERY_ROOT/settings.json --execute
```

路径是待替换的操作者输入，密钥按角色环境变量读取。`prepare`不调用模型，封存旧文件
哈希、尝试/排除名单及账本；`execute --execute`才是真实付费调用。新目录/锁存在时拒绝
再次执行，不得删除锁绕过。开始前检查授权、清单、资源上限和离线测试。

## 保留与核验

- 名单只依据 attempt/binding 元数据，不读成功分数挑案例；保持原计划顺序。
- 所有旧请求携入新账本并由 SQL 保护，包括失败和未知用量；累计上限不变。
- 仅新派发闸门依据授权打开，原账本停止标记不改。
- 新 API/429/quota/协议错误仍停止派发并排空，不自动第二次续跑。
- 完成后原生回放，`combined-final/record-provenance.json`保存原始位置和哈希；
  原始文件不改写，重复或错属记录拒绝合并。
- `remaining_collection_complete_with_retained_missing`表示剩余名单采集完且旧缺失保留，
  不表示所有任务成功，也不表示正式推断门槛满足。

成功率保持原计划分母、缺失[0,1]、部分完成单列。任何另行授权的技术补充尝试须使用
独立输出和明确的报告修订，不能覆盖首次尝试轨迹或冒称原先没有技术中断。
