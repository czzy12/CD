# schema 1.17 Frozen Contract：business_semantics_resolutions（方案 B）

状态：**Frozen Contract / 实施基线**（2026-08-07，Gate B.1 冻结；Gate C1 契约修订；Gate C2 shadow writer 修订）。
更新：2026-08-07（Gate B.1 / C1 / C2 收口）

## 0. Foundation Stable Contract 冻结记录

- F-CONTRACT-1：Canonical 字段语义稳定（transaction_time / income / expense / balance / counterparty... / summary / remark / purpose / field_confidence）；schema 1.17 writer 只能消费这些字段，不得重新解释 parser raw 字段。
- F-CONTRACT-2：raw evidence traceability 必须保留；business semantics resolution 通过 `transaction_ref` / `semantic_signature_ref` 引用稳定对象，禁止复制整份 raw evidence。
- F-CONTRACT-3：metadata 缺失表达为 `unavailable`，不得被解释为“确认没有”，不得按文件名/客户名/对手/路径推断填充。
- F-CONTRACT-4：source_diagnostics（source_row_count / parsed / skipped / unparsed / ignored / review / unsupported）继续兼容，不为 business semantics 重构。
- F-CONTRACT-5：transaction_id 长期稳定承诺从 Foundation GREEN 基线开始；4,316 笔 remediation ID 变化不构成先例；此后 identity 变更属于 breaking change，需独立 migration。

## 一、设计原则

1. schema 1.17 ≠ knowledge_v1 接管生产：正式业务 resolver 仍是 legacy_v11，knowledge_v1 保持 shadow。
2. schema_version 与 knowledge_version 解耦：允许 `schema_version=1.17` + `knowledge_version=knowledge_v1.x`，
   知识库独立迭代。
3. 只承载长期、可审计、跨会话信息；可推导展示名只作历史快照，不作为逻辑判断依据。
4. pending AI candidate 不得成为正式 resolution；rejected 不得进入 resolution。
5. 旧 1.16 案件不伪造历史 knowledge resolution。

## 二、放置位置：方案 B（独立观察）

新增 `result.observations[]` 类型 `business_semantics_resolutions`，与
`ai_business_relevance_candidates` 并存：

- legacy 候选：继续由 `ai_business_relevance_candidates` 承载（生产判断来源）；
- knowledge shadow：由 `business_semantics_resolutions` 承载（长期审计与展示）；
- 两者互不覆盖；GUI 未适配 1.17 时忽略新观察不崩溃。

## 三、最终字段定义

```json
{
  "observation_type": "business_semantics_resolutions",
  "value": {
    "knowledge_version": "business-semantic-kb-v1",
    "taxonomy_version": "gb-t-4754-2017-core-v1",
    "semantic_kb_version": "semantic-concepts-v1",
    "relation_kb_version": "industry-relations-v1",
    "resolver_version": "knowledge-v1-resolver-1",
    "resolutions": [
      {
        "resolution_id": "res-000001",
        "transaction_ref": "tx:...",
        "semantic_signature_ref": "sig-...",

        "concept_id": "logistics",
        "concept_name_snapshot": "物流运输",
        "concept_resolution_source": "exact_alias",

        "industry_id": "internal.building_material_trade",
        "industry_name_snapshot": "建材批发贸易（内部细分）",

        "relation_id": "rel-9f3c2a1b",
        "relation_resolution_source": "exact_relation",

        "relevance": "medium",

        "inherited": false,
        "inherited_from_industry_id": "",

        "review_status": "approved"
      }
    ]
  },
  "parameters": {
    "shadow": true,
    "production_resolver": "legacy_v11"
  },
  "evidence_transaction_ids": ["tx:..."]
}
```

### 必填 / 可选（Gate B.1 修订后）

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| resolution_id | 必填 | 稳定 ID：`res-` + 序号 |
| transaction_ref / semantic_signature_ref | 必填其一 | 定位到原交易或语义签名 |
| concept_id | 条件必填 | unresolved 时为空 |
| concept_name_snapshot | 可选 | 历史展示快照，不作为逻辑依据 |
| concept_resolution_source | 必填 | 见枚举 |
| industry_id | 条件必填 | unresolved 时为空 |
| industry_name_snapshot | 可选 | 历史展示快照 |
| relation_id | 条件必填 | 关系存在时必填 |
| relation_resolution_source | 必填 | 见枚举 |
| relevance | 必填 | 五值契约 |
| inherited / inherited_from_industry_id | 必填 | 继承标记独立保存 |
| review_status | 必填 | approved / unresolved / candidate（rejected 属于 Candidate lifecycle，不进入 resolution 主契约） |
| candidate_ref | 可选 | 指向 KnowledgeCandidate；pending candidate 不得以 approved 写入正式 resolution |

### 枚举（以现有实现为准）

`concept_resolution_source`（由 resolver 直接输出，writer 只序列化）：

- `exact_alias`（整值别名精确命中，对应实现 knowledge_base + confidence=high）
- `knowledge_base`（关键词/归一化别名命中）
- `semantic_cache`（已验收语义缓存）
- `ai_candidate`（仅授权 fallback，review_status 必须为 candidate）
- `unresolved`（本地未覆盖）

`relation_resolution_source`（由 resolver 直接输出，writer 只序列化）：

- `exact_relation`（本行业 approved 精确关系）
- `specialty_relation`（专项概念关系）
- `inherited_relation`（父行业保守继承）
- `generic_business_relation`（通用经营锚点）
- `relation_cache`
- `ai_candidate`
- `unresolved`

### relation_id 审计方式

- `relation_id = "rel-" + sha256(canonical_payload)[:16]`；
- canonical_payload = `industry_id + concept_id + 最终 relevance + confidence_tier + review_status + relation_kb_version`（sort_keys 后 JSON 序列化）；
- relevance 或影响最终判断的 canonical 语义变化必然改变 relation_id；`created_by / reviewed_at / reason_template / JSON 格式 / key 顺序` 等非语义 metadata 不参与哈希；
- 保存 relation_id 与 knowledge_version 即可重建判断；不保存整份 Relation JSON。

### resolution_id 确定性

- `resolution_id = "res-" + sha256(signature_ref + industry_id + concept_id + relation_id + resolver_version + knowledge_version)[:16]`；
- 同输入 + 同版本 → 同 ID；数组顺序变化 → ID 不变；不使用姓名/案件 ID/卡号/路径/数组 index。

## 四、生命周期与 Candidate 边界

```text
canonical / approved  -> 可形成正式 resolution（review_status=approved）
pending candidate     -> resolution 只能引用为 unresolved 或 candidate_ref，不得作为正式 relevance
rejected              -> 不进入正式 resolution
```

`review_status` 在 resolution 中只允许 approved；AI candidate 如需展示，通过
`candidate_ref` 引用审核队列，不写入正式字段值。

Gate B.1 修订：`review_status` 正式枚举为 `approved / unresolved / candidate`。
`unresolved` 允许承载本地未解析（relevance=undetermined、concept/relation unresolved），
当前实现以 diagnostics 计数承载；`candidate` 仅表示存在 `candidate_ref`，不得被误读为 approved relevance。

## 五、父行业继承审计

- 独立保存 `inherited=true` 与 `inherited_from_industry_id`；
- 不把继承信息只藏在 `relation_resolution_source=inherited_relation`；
- 继承不得自动升级 relevance（现有 resolver 已保证）。

## 六、legacy_shadow 与 diagnostics 分离

- 正式 resolution 只保存长期字段（concept/industry/relation/source/version/review_status）；
- legacy comparison（legacy_relevance / agreement）不进正式 schema，放入运行 diagnostics；
- 迁移期观察指标单独存 `outputs/` 报告，不污染长期业务 schema。

## 六之一、migration_status 正式落位

- 正式位置：`business_semantics_resolutions.value.migration_status`；
- 枚举：`parsed` / `not_parsed`（暂不引入 partial）；
- `resolutions=[] + migration_status=not_parsed` 表示历史案件未运行 knowledge resolver，不解释为“已运行但没有经营语义”。

## 七、1.16 → 1.17 Migration

1. `SCHEMA_VERSION` 1.16 → 1.17；既有字段与结构不删除、不改义。
2. `build_bankflow_result` 在 shadow 开关下追加 `business_semantics_resolutions` 观察；
   生产 resolver 仍为 legacy_v11。
3. 旧 1.16 案件：
   - 读取兼容：新代码可读 1.16，无新观察时按 `resolutions=[]` 降级；
   - 不伪造：旧案件没有 knowledge 解析记录时，不生成 concept_id / relation_id / review_status，
     顶层 `migration_status="not_parsed"`。
4. migration 脚本只追加，不回写历史交易；1.16 → 1.17 幂等。

## 七之一、Resolver Source 由 resolver 输出

- `concept_resolution_source` / `relation_resolution_source` 由 resolver（SemanticResolver / IndustryRelationResolver / RelationKB）直接输出；
- schema writer 只序列化，不根据 `source / confidence / reason` 二次猜测；
- 当前代码真实可产生的枚举：concept = exact_alias / knowledge_base / semantic_cache / unresolved（ai_candidate 仅未来 AI 路径）；relation = exact_relation / specialty_relation / inherited_relation / generic_business_relation / relation_cache / unresolved（ai_candidate 仅未来 AI 路径）。

## 七之二、Per-entry Industry Context

- 不得用单案件统一行业画像覆盖所有 transaction；
- `build_business_semantics_resolutions(..., per_entry_profiles={transaction_id: IndustryProfile})` 按交易行业画像拆分语义桶；
- 无 per-entry 时使用 case_context 构建的真实模型画像（单案件单行业）；
- 多行业 legacy 场景（建材/烟酒超市/家具家电）沿用 Gate A 修正的 per-entry 机制。

## 八、兼容策略（至少覆盖）

1. schema 1.16 文件由新代码读取；
2. schema 1.17 文件由新代码读取；
3. legacy_v11 在 1.17 下保持原行为；
4. knowledge_v1 可在 1.17 写 shadow resolution；
5. GUI 未适配 1.17 时不得崩（未知 observation_type 忽略）；
6. export/report 不因新字段改变旧结果；
7. replay_only 行为保持；
8. AI disabled 时可正常执行。

### 方向明确的兼容性

- New-reader 读取 1.16：支持（validate_standard_result 接受 1.16）。
- New-reader 读取 1.17：支持。
- Old-reader 读取 1.17：不支持（旧代码不认识 schema_version=1.17）；文档不宣称“双向兼容”。
- GUI / DTO：对未知 observation_type 忽略、不崩；旧结果正常展示（tolerant DTO）。

## 九、示例 JSON（完整）

```json
{
  "schema_version": "1.17",
  "module": "bankflow",
  "analysis_source": "original_transactions",
  "result": {
    "observations": [
      {
        "observation_type": "business_semantics_resolutions",
        "value": {
          "knowledge_version": "business-semantic-kb-v1",
          "taxonomy_version": "gb-t-4754-2017-core-v1",
          "resolutions": [
            {
              "resolution_id": "res-000001",
              "transaction_ref": "tx:0001",
              "concept_id": "logistics",
              "concept_name_snapshot": "物流运输",
              "concept_resolution_source": "exact_alias",
              "industry_id": "internal.building_material_trade",
              "industry_name_snapshot": "建材批发贸易（内部细分）",
              "relation_id": "rel-9f3c2a1b",
              "relation_resolution_source": "exact_relation",
              "relevance": "medium",
              "inherited": false,
              "inherited_from_industry_id": "",
              "review_status": "approved"
            }
          ]
        },
        "parameters": {
          "shadow": true,
          "production_resolver": "legacy_v11"
        },
        "evidence_transaction_ids": ["tx:0001"]
      }
    ]
  }
}
```

## 十、测试方案

- schema 版本与结构契约测试；
- 1.16 → 1.17 migration 幂等；
- 1.16 / 1.17 双向兼容读取；
- legacy_v11 在 1.17 下行为不变；
- knowledge_v1 shadow resolution 写入；
- GUI 忽略新 observation_type 不崩；
- export/report 旧结果不变；
- replay_only / AI disabled 正常；
- Gold Set 测试继续作为知识层指标。

## 十一、Rollout Plan

```text
Commit 2（已完成）      schema 1.17 contract + migration + compatibility tests（4893b47）
Commit 3（已完成）      knowledge_v1 shadow resolution 写入 1.17（见 git log）
之后                    用户确认后 GUI 只读展示，再评估正式切换
```

不混提交；不改 GUI；不 push（除非授权）。实施明细与测试见
`docs/change-history/2026-08.md#chg-20260807-16`。

## 十二、Gate C 结论

完成 Gate A 后评估：

- 100 条 mismatch Gold Set 已形成（63 条泛化条目，knowledge accuracy 99%）；
- schema 字段可由现有 resolver 稳定生成（concept/relation source、inherited、version 均已实现）；
- 不依赖未完成的 AI candidate（当前理论 fallback 40，均以 unresolved 呈现）；
- 1.16 兼容方案明确；migration 不伪造历史结果。

条件满足，**建议进入 schema 1.17 实施（Commit 2）**；实施时保持 legacy_v11 生产裁决权不变。
