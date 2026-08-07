# schema 1.17 设计草案：经营语义知识库（business_semantics）

状态：设计草案，仅讨论，未实施。
更新：2026-08-07

## 一、是否已具备升级必要（结论）

已具备启动设计的必要，理由如下：

1. 经营语义知识库已进入人工验收阶段，approved 知识将成为正式业务结果的一部分，
   审核人员需要看到“概念/行业/关系来源/知识库版本”，而不是只有 `medium/weak`；
2. “为什么这笔被判为 medium”需要可审计答案：`concept = logistics`、
   `industry = building_material_trade`、`relation = medium`、
   `source = approved_knowledge`、`knowledge_version = business-semantic-kb-v1`，
   仅保存强度无法回答；
3. 工作台后续需要展示知识来源、AI 候选、人工确认状态、行业归一化结果，
   这些信息必须跨程序保存，不能只存在于运行时内存或 shadow 报告；
4. shadow 第二轮仍有 121 条差异与 40 条强度上调需要逐条追溯，
   正式切换后必须有持久化的 provenance 字段支持复核。

升级前提（不满足不实施）：knowledge_v1 shadow 验收继续收敛、冲突候选裁决完成、
字段放置位置经用户确认、migration 与兼容测试通过。

## 二、候选字段

建议新增顶层 `business_semantics` 元数据（或挂接观察层，见第三节）：

```json
{
  "business_semantics": {
    "semantic_concept_id": "logistics",
    "semantic_concept_name": "物流运输",
    "industry_id": "internal.building_material_trade",
    "industry_name": "建材批发贸易（内部细分）",
    "relevance": "medium",
    "resolution_source": "knowledge_base",
    "knowledge_version": "business-semantic-kb-v1",
    "review_status": "approved"
  }
}
```

字段语义：

| 字段 | 说明 |
| --- | --- |
| semantic_concept_id | 稳定英文 slug，跨客户复用 |
| semantic_concept_name | 中文概念名 |
| industry_id | 归一化行业 ID（官方或内部细分） |
| industry_name | 行业名（展示用） |
| relevance | 仍只允许 strong/medium/weak/none/undetermined |
| resolution_source | deterministic / knowledge_base / cache / ai_candidate / undetermined |
| knowledge_version | 追溯知识库版本（business-semantic-kb-v1） |
| review_status | approved / candidate / rejected / deprecated |

不新增业务强度枚举；不改变 schema 1.16 既有字段含义。

## 三、放置位置（三选一，需用户确认）

### 方案 A：挂接现有经营候选条目（最小侵入）

在 `ai_business_relevance_candidates` 的每个候选条目上追加 `business_semantics` 对象。

- 优点：与既有观察同生命周期，GUI 改动最小；1.16 消费者忽略新字段即可。
- 缺点：候选条目与知识层一一绑定，批量结构里字段重复。

### 方案 B：新增独立观察类型（推荐）

新增 `result.observations[]` 类型 `business_semantics_resolutions`：

```json
{
  "observation_type": "business_semantics_resolutions",
  "value": {
    "knowledge_version": "business-semantic-kb-v1",
    "taxonomy_version": "gb-t-4754-2017-core-v1",
    "resolutions": [
      {
        "transaction_id": "tx:...",
        "semantic_concept_id": "logistics",
        "industry_id": "internal.building_material_trade",
        "relevance": "medium",
        "resolution_source": "knowledge_base",
        "review_status": "approved"
      }
    ]
  },
  "evidence_transaction_ids": ["tx:..."]
}
```

- 优点：与 legacy 候选解耦，知识层可独立升级/降级；审计与报告引用清晰。
- 缺点：新观察类型需要工作台模块或适配器支持。

### 方案 C：顶层只读 diagnostics

在标准结果顶层新增 `diagnostics.knowledge_v1`，只记录版本与运行统计，不逐笔展开。

- 优点：最保守，不进入业务观察。
- 缺点：无法回答“为什么这笔是 medium”的逐笔审计。

推荐：方案 B（独立观察），过渡期同时保留方案 A 的只读映射供 GUI 展示。

## 四、migration 计划

```text
1. schema 版本常量 SCHEMA_VERSION 1.16 → 1.17；
2. build_bankflow_result 增加 knowledge_v1 解析结果输出（shadow 开关默认仍 legacy）；
3. 写 migration 脚本：1.16 JSON → 1.17 时只追加 business_semantics 观察，
   不修改 original_transactions / facts / indicators / evidence；
4. 兼容测试：1.16 读取器读 1.17 必须忽略新字段不报错；
   1.17 读取器读 1.16 必须降级为“无知识层元数据”；
5. GUI 切换：工作台新增只读展示，切换前用户确认。
```

禁止边做边改：不因临时需要往 1.16 塞 concept_id / knowledge_version 等字段。

## 五、测试计划

- schema 版本与结构契约测试；
- 1.16 → 1.17 migration 幂等测试；
- 1.16 / 1.17 双向兼容读取测试；
- 知识层字段白名单与敏感数据测试（business_semantics 不携带客户身份）；
- 与 legacy_v11 shadow 对比不回归测试；
- 前端 TypeScript 类型契约（仅方案 B/C 新增 DTO 时）。

## 六、不做的内容

- 不修改 schema 1.16 既有字段含义；
- 不把 knowledge_v1 直接替换 legacy 生产主链（仍 shadow）；
- 不新增风险/欺诈/准入结论；
- 不把 AI candidate 写入正式 schema（只允许 approved，candidate 留在审核队列）。
