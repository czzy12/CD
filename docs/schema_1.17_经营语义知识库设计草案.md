# schema 1.17 正式设计：business_semantics_resolutions（方案 B）

状态：正式设计（接近可实施），尚未实施。
更新：2026-08-07

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

### 必填 / 可选

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
| review_status | 必填 | approved / candidate / rejected / deprecated |

### 枚举（以现有实现为准）

`concept_resolution_source`：

- `exact_alias`（整值别名精确命中，对应实现 knowledge_base + confidence=high）
- `knowledge_base`（关键词/归一化别名命中）
- `semantic_cache`（已验收语义缓存）
- `ai_candidate`（仅授权 fallback，review_status 必须为 candidate）
- `unresolved`（本地未覆盖）

`relation_resolution_source`：

- `exact_relation`（本行业 approved 精确关系）
- `specialty_relation`（专项概念关系）
- `inherited_relation`（父行业保守继承）
- `generic_business_relation`（通用经营锚点）
- `relation_cache`
- `ai_candidate`
- `unresolved`

### relation_id 审计方式

- `relation_id = sha256(industry_id + ":" + concept_id + ":" + relation_rules_version)[:16]`；
- 保存 relation_id 与 knowledge_version 即可重建判断：按 industry×concept 查对应版本 canonical；
- 不保存整份 Relation JSON（避免冗余大对象）。

## 四、生命周期与 Candidate 边界

```text
canonical / approved  -> 可形成正式 resolution（review_status=approved）
pending candidate     -> resolution 只能引用为 unresolved 或 candidate_ref，不得作为正式 relevance
rejected              -> 不进入正式 resolution
```

`review_status` 在 resolution 中只允许 approved；AI candidate 如需展示，通过
`candidate_ref` 引用审核队列，不写入正式字段值。

## 五、父行业继承审计

- 独立保存 `inherited=true` 与 `inherited_from_industry_id`；
- 不把继承信息只藏在 `relation_resolution_source=inherited_relation`；
- 继承不得自动升级 relevance（现有 resolver 已保证）。

## 六、legacy_shadow 与 diagnostics 分离

- 正式 resolution 只保存长期字段（concept/industry/relation/source/version/review_status）；
- legacy comparison（legacy_relevance / agreement）不进正式 schema，放入运行 diagnostics；
- 迁移期观察指标单独存 `outputs/` 报告，不污染长期业务 schema。

## 七、1.16 → 1.17 Migration

1. `SCHEMA_VERSION` 1.16 → 1.17；既有字段与结构不删除、不改义。
2. `build_bankflow_result` 在 shadow 开关下追加 `business_semantics_resolutions` 观察；
   生产 resolver 仍为 legacy_v11。
3. 旧 1.16 案件：
   - 读取兼容：新代码可读 1.16，无新观察时按 `resolutions=[]` 降级；
   - 不伪造：旧案件没有 knowledge 解析记录时，不生成 concept_id / relation_id / review_status，
     顶层 `migration_status="not_parsed"`。
4. migration 脚本只追加，不回写历史交易；1.16 → 1.17 幂等。

## 八、兼容策略（至少覆盖）

1. schema 1.16 文件由新代码读取；
2. schema 1.17 文件由新代码读取；
3. legacy_v11 在 1.17 下保持原行为；
4. knowledge_v1 可在 1.17 写 shadow resolution；
5. GUI 未适配 1.17 时不得崩（未知 observation_type 忽略）；
6. export/report 不因新字段改变旧结果；
7. replay_only 行为保持；
8. AI disabled 时可正常执行。

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
Commit 2（本阶段设计）  schema 1.17 contract + migration + compatibility tests
Commit 3（后续实施）    knowledge_v1 shadow resolution 写入 1.17
之后                    用户确认后 GUI 只读展示，再评估正式切换
```

不混提交；不改 GUI；不 push（除非授权）。

## 十二、Gate C 结论

完成 Gate A 后评估：

- 100 条 mismatch Gold Set 已形成（63 条泛化条目，knowledge accuracy 99%）；
- schema 字段可由现有 resolver 稳定生成（concept/relation source、inherited、version 均已实现）；
- 不依赖未完成的 AI candidate（当前理论 fallback 40，均以 unresolved 呈现）；
- 1.16 兼容方案明确；migration 不伪造历史结果。

条件满足，**建议进入 schema 1.17 实施（Commit 2）**；实施时保持 legacy_v11 生产裁决权不变。
