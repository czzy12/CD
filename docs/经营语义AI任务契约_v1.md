# 经营语义 AI 任务契约 v1

更新：2026-08-07

## 一、总则

- 保留旧任务 `business_relevance`（`business-relevance-mvp-v11`）作为 legacy_v11 回归基线，不覆盖。
- 新增两个稳定任务：
  1. `semantic_concept_resolution`（prompt：`semantic-concept-v1`）
  2. `industry_concept_relevance`（prompt：`industry-concept-relevance-v1`）
- 每个任务独立版本号、输出 schema、测试、缓存版本与调用统计。
- AI 默认关闭（`allow_ai_fallback=false`）；未授权时未知项返回 undetermined，绝不联网。
- 模型可替换：`DeepSeekKnowledgeAdapter` 只是实现之一；解析器不依赖具体模型名。

## 二、公共安全约束

系统提示必须包含：

1. 只做语义分类，不做风控、欺诈、包装、准入判断；
2. 不能引用未提供字段；
3. 不能使用金额、日期、方向、银行名、账号、路径等未提供内容；
4. 不确定时返回 undetermined / low，不允许为覆盖率强行分类；
5. 只输出给定 JSON 结构，不输出 Markdown。

禁止发送：客户姓名、身份证、账号、金额、日期、流水方向、文件路径、PDF/Excel 全文、整个 standard_result。

## 三、Task 1：semantic_concept_resolution

输入仅允许：

- 已批准文本字段（`counterparty_name / merchant_name / summary / remark / purpose / product_description / merchant_category`）；
- concept 候选（标准概念 ID + 名称）；
- 与文字解释相关的安全边界。

输出（严格 JSON）：

```json
{
  "task_type": "semantic_concept_resolution",
  "concept_id": "logistics",
  "confidence": "high | medium | low",
  "reason": "…",
  "used_fields": ["remark"],
  "new_concept_candidate": null
}
```

现有概念无法覆盖时允许：

```json
{
  "new_concept_candidate": {
    "suggested_concept_id": "…",
    "name_zh": "…",
    "reason": "…"
  }
}
```

`new_concept_candidate` 只能进入待审核队列，不得自动创建正式概念。

本地校验（`DeepSeekKnowledgeAdapter._validate_concept_results`）：

- item_id 必须存在且唯一；
- confidence 必须为 high/medium/low；
- used_fields 非空且必须是指定条目真实提供的字段；
- concept_id 或 new_concept_candidate 至少一项存在；
- reason 非空；
- 任何违规整条拒绝并抛 `KnowledgeAIError`，不写入知识库。

## 四、Task 2：industry_concept_relevance

输入：

- 标准 industry 节点（含必要父行业）；
- 标准 concept（ID + 名称）；
- 产品/服务 specialty 摘要；
- 本地 classification constraints。

原则上不发送真实交易文字，只发送标准行业、标准概念、必要 specialty 与约束。

输出（严格 JSON）：

```json
{
  "task_type": "industry_concept_relevance",
  "relevance": "strong | medium | weak | none | undetermined",
  "reason": "…",
  "constraint_acknowledged": true
}
```

本地校验：

- item_id 必须存在；
- relevance 必须五值；
- `constraint_acknowledged` 必须为 true；
- reason 非空；
- 任何违规整条拒绝。

一个 industry × concept 原则上只判断一次，结果进入 Relation Cache 供所有客户复用。

## 五、AI 结果边界

- 结果默认 `ai_candidate`，不自动 approved；
- AI 或知识库都不能绕过本地硬护栏（`maximum_allowed_strength`、`directly_related_allowed`）；
- AI 不产生风险、欺诈、准入结论；
- AI 不改变原始流水事实；
- 调用统计只记录请求/缓存/知识库命中数，不记录客户敏感文本。

## 六、调用统计字段

```text
semantic_requests / semantic_cache_hits / semantic_kb_hits
relation_requests / relation_cache_hits / relation_kb_hits
parent_inheritance_hits / generic_business_hits
undetermined_count / candidate_count / legacy_alias_hits
```

目标：知识库成熟后，AI 调用随客户数量增加而下降，而不是线性增加。
