# HANDOFF — Current State Freeze（流水分析 / Bankflow Verification）

- 创建日期：2026-08-09（Asia/Shanghai）
- 任务类型：Current State Freeze + Handoff（仅交接，不开发）
- **CURRENT HANDOFF SOURCE OF TRUTH：本文件 `HANDOFF_CURRENT_STATE.md`**
- 本文件为本次任务唯一有意新增/变更文件；未 commit、未 push。

---

## 1. Repository Identity

- Repo 绝对路径：`D:\Investigator PDF\CD-bankflow-refactor`
- Git toplevel：`D:/Investigator PDF/CD-bankflow-refactor`
- Remote `origin`：
  - fetch：`https://github.com/czzy12/CD.git`
  - push：`https://github.com/czzy12/CD.git`
- 项目正式名称（业务层）：流水分析 / Bankflow Verification

## 2. Branch / HEAD

- 当前分支：`work/deepseek-12b2-followup`
- 本地 HEAD：`47c4d0b0fbd43fe8e41e8cb702befdff186e0b83`
- `origin/work/deepseek-12b2-followup`：`47c4d0b0fbd43fe8e41e8cb702befdff186e0b83`
- HEAD 与 origin 一致，符合预期。

## 3. Git Working Tree

- tracked modified files：**无**
- staged files：**无**
- untracked files（交接前已存在，本次未动）：
  - `CD-bankflow-refactor.bundle`（3,581,573 bytes；mtime 2026-08-04 11:32:14；仍存在，保持 untracked）
  - `docs/续接_2026-08-08_Gate_F1.1b后.md`（5,419 bytes；mtime 2026-08-08 15:47:04；保持 untracked）
- ignored 但与项目状态有关的重要路径（`git status --ignored`）：
  - `outputs/`（repo 内 ignored 目录）
  - `web_frontend/dist/`、`web_frontend/node_modules/`
  - 各 `__pycache__/`、`build-webview2-spike/`、`dist-webview2-spike/`
  - `web_frontend/tsconfig.node.tsbuildinfo`、`web_frontend/tsconfig.tsbuildinfo`、`web_frontend/vite.config.d.ts`、`web_frontend/vite.config.js`
- 新增本 HANDOFF 后，唯一新增/变更项为 `HANDOFF_CURRENT_STATE.md`；其余 working tree 状态与交接前完全一致。

## 4. Recent Commits（`git log --oneline -10`）

```text
47c4d0b docs(eval): record F3B/F3B.1/F4-R1 state and handoff for new window
5ba96f1 fix(eval): parse bracketed address labels in 0808 metadata
7662121 feat(eval): add dropdown xlsx review files with chinese options
1388719 feat(eval): add chinese header review files for human gold
24d1467 fix(eval): populate review identifiers and regenerate f3b review files
98debc8 feat(eval): prepare human gold review workflow for gate f3b
7482d4c test(eval): rebuild independent production holdout pools
d8be907 docs(eval): freeze human gold review standard v1
628c9c5 feat(eval): ingest manually confirmed 0808 pristine cases
b197db7 docs(eval): record manual metadata expansion gate
```

## 5. Production State

- 正式 Production：`legacy_v11`（未变更）
- `knowledge_v1`：shadow / candidate 层
- 当前正式 Candidate：`production-candidate-v2.1-runtime`
- Candidate 状态：`evaluated_not_promoted`（不可进入 Production）

## 6. Schema State

- Schema：`1.17`（正式，未变更）

## 7. Candidate Identity

- Semantic Candidate（predecessor）：`production-candidate-v2`
  - Semantic checksum：`4e80dfdfd19de7d844c7509d7e02631e844c695bf9855fe6c4ddb547bf2681ea`
  - 24 个 prediction-affecting repo files 已冻结；交接时逐文件 SHA256 复核：24/24 一致、mismatch=0
- Runtime Candidate：`production-candidate-v2.1-runtime`
  - Runtime aggregate checksum：`d5a65e0fe9a4734e3717200c864e2d88b2f97218819438484a25105a0e6090bb`
  - prediction-affecting surface：25（24 repo files + 1 external runtime config）
  - `runtime_source = external_frozen_config`

## 8. Gold Freeze

- Transaction Gold（v1.1 amended）：`production_transaction_evidence_human_gold_v1_1.jsonl`
  - checksum：`a02456225c7f9c596c8aef347abf70c36dbe5a50bd2a5838b95fe3def963a3f2`
  - 总数：100
- Case Gold：`production_case_human_gold_v1.json`
  - checksum：`7713408a6f73013ff476cd2ce36f02a9030a2a3eece5a6dbb03d835a1664aeb7`
  - 总数：5
- Gold Freeze aggregate：`bfa5a0c1034307f4299586f792e2e14991d605459f81754648d85e9e2511a0dd`
- Gate F3B / F3B.1 状态：`PASS`
- Gold 只读；交接时复核 checksum 与 read-only 均保持。

## 9. Runtime Freeze

- 外部 runtime config：`%LOCALAPPDATA%\BankFlowReview\ai_runtime.json`
  - 绝对路径：`C:\Users\lenovo\AppData\Local\BankFlowReview\ai_runtime.json`
  - SHA256：`dee20b0697c9d8820b75c632322c54d54fa79be08ae1bd8f6b68ce6a72eff7cd`
  - 解析 batch_size：`20`
  - model：`deepseek-v4-flash`；base_url：`https://api.deepseek.com`；timeout_seconds：`60.0`
  - 文件大小：887 bytes；mtime：2026-08-09 17:32:02
- `max_tokens=4096` 实际来源：
  - 冻结代码路径：`bankflow_v2/knowledge/ai_contracts.py` 的 `_post()`（`"max_tokens": 4096`）
  - 调用路径：`call_transaction_evidence_ai()` / `call_case_synthesis_ai()` → `_post()`
  - 该文件属于 24 个 prediction-affecting repo files，其 SHA256 已由 freeze manifest 核验
  - 外部 config 文件本身**不含** `max_tokens` 键；manifest 中记录的 4096 为有效契约值
- Gate F4-R1 状态：`PASS`

## 10. Gate History

- Gate F3B-FREEZE：PASS（Human Gold v1：Transaction 100/100、Case 5/5）
- Gate F3B.1：PASS（v1.1 amendment：43 条 none/sufficient 修正，unresolved semantic conflict=0）
- Gate F4 Phase A（v2, batch=50）：BLOCKED（provider 输出截断；诊断归档于 `production-candidate-v2-blind-run-20260809/blocked_run_diagnostics/`，仅历史参考，禁止复用）
- Gate F4-R1：PASS（runtime contract revision：batch_size=50→20，max_tokens=4096 不变；synthetic 20/20）
- Gate F4 Blind Run Restart（v2.1-runtime）：Integrity PASS（详见第 11-13 节）
- Architecture Review：Candidate v2.1 = `evaluated_not_promoted`

## 11. F4 Integrity

- run_id：`blind-20260809-095415`
- Prediction Freeze aggregate：`5bd61e491309c39f648498b2a09ebfc18a817896e70a299ae963927b32e72aa1`
- 关键事实（以 manifest 与实际产物复核）：
  - Gold Phase A 未加载：`gold_labels_loaded_during_phase_a = false`
  - 100 Transaction 从 holdout 全量重新执行（未复用任何 blocked diagnostics）
  - 5 Case 完整执行
  - Prediction Freeze 完成（`PREDICTION_FREEZE_COMPLETE` checkpoint）后才进入 Phase B
  - Gold / Candidate 均未修改（`candidate_modified=0`、`gold_modified=0`）
  - Gold 加载后无 prediction rerun（`post_gold_prediction_rerun=0`）
  - push = no
- runner（`D:\Codex Deepseek\Flow\_f4_phase_a.py`）SHA256：`9e4396303581463259bbe89c0eaf17fcd4650820ac2a895a087d415db3c9519e`（记录于 manifest，运行期间未修改）

## 12. F4 Quality Metrics

### Transaction

- Relation：exact 36/100；accuracy 0.36；macro F1 0.4128
- Evidence Role：exact 61/100；accuracy 0.61；macro F1 0.4655
- Business Trace：exact 13/100；accuracy 0.13；macro F1 0.1226
- Joint：3/3=5、2/3=25、1/3=45、0/3=25
- none ↔ undetermined：relation=36、trace=10
- trace 边界/强度：weak↔none=9、medium↔weak=7、strong overclaim=51、strength underclaim=0

### Routing / Resolver

- Route agreement：37/100
- False Local Resolution：29
- Local resolved：32；AI eligible：68；insufficient：0
- Local-resolved：N=32，joint=0.125，relation=0.3125，role=0.75，trace=0.3125
- Transaction AI-resolved：N=68，joint=0.0147，relation=0.3824，role=0.5441，trace=0.0441
- insufficient/abstained：N=0

### Case

- Presence exact：1/5
- Industry consistency exact：0/5
- Joint exact：0/5
- Evidence ref integrity：5/5 PASS（refs 均在对应 CaseEvidencePack 内、回指真实 Candidate Transaction Evidence、无跨案 ref、hallucination=0）

### Runtime（本 run）

- 交易 provider 批次：4（20+20+20+8）；provider 实际调用：9（4 交易 + 5 案件）
- retries=0、failures=0（全部 finish_reason=stop、JSON valid、无 missing/duplicate）
- Token：交易 prompt 7,761 / completion 6,689；案件 prompt 74,312 / completion 2,025
- Latency：交易均值 8,794.3ms；案件均值 4,160.2ms

## 13. F4 Error Summary

- total error items：102
- Primary counts：
  - E1=28、E2=15、E3=13、E4=12、E5=29、E8=5、E6=0、E7=0、E9=0、E10=0
- **重要说明**：`E6=0` 不应解释为 Transaction AI 无 semantic failure；当前 primary taxonomy 会把 AI semantic failure 分散到 E1-E4 等 primary error 中。E6/E7 在本轮仅作为 secondary error type 记录。
- Top 5 模式（详见 error inventory）：
  1. E3：ai→ai，role neutral_transfer→direct_business，trace undetermined→medium（5）
  2. E1：ai→ai，relation none→undetermined，role personal→personal，trace none→medium（5）
  3. E8：案件级（5）
  4. E4：case_aggregation→ai，trace undetermined→weak（4）
  5. E1：ai→ai，relation none→undetermined，role neutral→neutral，trace none→weak（4）

## 14. Frozen Artifact Paths + SHA256

目录：`D:\Investigator PDF\outputs\knowledge-v1\production-candidate-v2.1-blind-run-20260809`

| 文件 | 大小 | SHA256 | 只读 |
| --- | --- | --- | --- |
| `production_candidate_v2_1_blind_transaction_predictions.jsonl` | 144,690 | `bb70e9a31f5dfcd8ab7faa6a1627ae5ec2bb15daca65e72fa3a5a111f14245cd` | 是 |
| `production_candidate_v2_1_blind_case_predictions.json` | 126,288 | `a030eb61ab7feeb23f69db876cf98634d8c8d5b4f7a57fed76d7327f2abfdd57` | 是 |
| `production_candidate_v2_1_blind_run_manifest.json` | 9,335 | `1f75abfeadd48c186a5f67def30d7487f596ca70530cdc81e8ae76b43f39f26d` | 是 |
| `production_candidate_v2_1_blind_prediction_checksums.json` | 1,437 | `1602fa152a13e766c4218af11a9f6378ea7f39b54c38b5e09072352f6e2709b4` | 是 |
| `production_candidate_v2_1_blind_score_report.json` | 68,011 | `1e5da3bdbf6a4d7682a9cbff2f683a4e775739a8e0d3dfc0d8aa7ef81c93017c` | 否 |
| `production_candidate_v2_1_blind_error_inventory.json` | 55,492 | `bbf41fa4cc9eee735dd4f60caec530ffe8fb6cbeeee6bbbdfae2c95ac7e9ce97` | 否 |
| `production_candidate_v2_1_blind_error_report.md` | 1,249 | `da2f3b41ca2db04ea85a01b58b04d1f506d7a1ff933fd25c151dcec43726824e` | 否 |
| `frozen_runtime_snapshot_ai_runtime.json` | 887 | `dee20b0697c9d8820b75c632322c54d54fa79be08ae1bd8f6b68ce6a72eff7cd` | 是 |
| `PREDICTION_FREEZE_COMPLETE` | 296 | `29ae9e3a7578d78a82797cd2d8b122030b88bb3a53479586588df5ec351b38ec` | 是 |
| `blind_preflight_ok.json` | 2,204 | `6f323e17d4c55bb7056279997a0da64ebec17b120760faaa0add93882b294143` | 是 |

- 另含 `case_evidence_packs/`（5 个 pack，只读）与 `cache/knowledge_v1_runtime.db`（本 run 私有副本）。
- 以上文件本次仅核验，未修改；原只读状态保持不变。

## 15. External Runtime Snapshot

- 运行期快照：`frozen_runtime_snapshot_ai_runtime.json`（见第 14 节，SHA256=`dee20b06…`）
- source path：`C:\Users\lenovo\AppData\Local\BankFlowReview\ai_runtime.json`
- source checksum = snapshot checksum = `dee20b0697c9d8820b75c632322c54d54fa79be08ae1bd8f6b68ce6a72eff7cd`
- source == snapshot：true
- frozen batch_size：20；frozen max_tokens：4096（来源见第 9 节）

## 16. Long-term Architecture Contracts

```text
relation not known != relation none

knowledge coverage insufficient
!=
declared industry inconsistent

unavailable != absent

business activity strong
!=
declared industry consistency strong

payment rail != business substance

industry relevance
!=
business trace

Local Precision First
!=
Minimize AI Call Rate
```

- Business Semantic 与 Risk Investigation 必须长期分离。
- 允许同一交易：`industry relation = none`、`business trace = none`，同时 `large amount follow-up = true`、`rapid in/out = true`、`sensitive / risk follow-up = true`。
- 即：`business semantic none != no risk significance`；Risk 不得反向污染 Business Semantic。
- F4 评分已遵守该契约，未使用“大额/快进快出”否定 semantic Gold。

## 17. Current Architecture Review Decision

- Candidate v2.1：`evaluated_not_promoted`，不能进入 Production。
- Production 继续：`legacy_v11`；Schema 继续：`1.17`。
- Runtime v2.1 暂不修改。
- F4 Holdout 已 consumed：今后仅可用于 error analysis / architecture diagnosis / regression reference，**不能再作为新的 Blind Holdout 宣称泛化通过**。
- 下一次正式 Blind Evaluation 必须使用全新 Holdout。
- 设计方向（仅记录，不执行）：
  - Evidence-first：单笔 Transaction 不应承担过多最终经营判断；候选流水线为 Raw Transaction → Transaction Facts → Semantic Atoms → Evidence Candidate → Evidence Family/Context Aggregation → Business Evidence → Business Activity Presence → Declared Industry Consistency。
  - Local 未来职责方向：`Local Evidence Extractor`（deterministic facts、normalization、counterparty、direction、amount、recurrence、frequency、grouping、monthly distribution、evidence refs、time relationships、location facts、semantic concept high-confidence resolution），而非直接整笔输出 relation/role/trace。
  - Shared Evidence Foundation：Business / Risk / Lifestyle / Trajectory Evidence 可共享 Facts / Evidence（如 transaction_id、datetime、amount、direction、counterparty、counterparty_type、payment rail、semantic concept、recurrence、amount distribution、unique counterparties、in/out pairing、time gap、location、evidence refs），但结论层必须独立；禁止 `risk_high → business_trace_high`、`high_consumption → business_strong`。

## 18. DO NOT MODIFY

- production Candidate（含 24 个 prediction-affecting repo files）
- Schema / KB / prompt / Local rules / threshold / runtime
- Human Gold（含 v1.1 amended 与 Case Gold）
- F4 frozen artifacts（第 14 节全部文件，保持只读）
- 外部 runtime config（`%LOCALAPPDATA%\BankFlowReview\ai_runtime.json`）
- `CD-bankflow-refactor.bundle` 与 `docs/续接_2026-08-08_Gate_F1.1b后.md`（保持 untracked）
- 禁止：prediction rerun、case rerun、重新评分、second Blind Run、promotion、push、reset、checkout 其他 branch、clean、删除 untracked 文件、删除 outputs

## 19. Current Next Gate

- 下一 Gate：**Gate F5-A — Root Cause Decomposition**（Analysis Only，尚未批准实施）
- 计划新增：**Gate F5-A.2 — Decision Dependency Audit**
  - 审计 Facts / Concept / Role / Trace / Relation / Case 之间真实依赖
  - 重点检查：business_trace 是否读取 declared industry；role 是否被 relation 反向影响；company counterparty 是否自动增强 trace；KB miss 是否自动产生 relation=none；Case presence 是否直接依赖错误 Transaction trace；Local 是否因单个字段确定就整笔 over-resolve
- 计划评估：`Evidence-first Candidate v3`、`Shared Evidence Architecture`
- 以上均不得在当前阶段实施。

## 20. Handoff Verification Commands

```powershell
git -C "D:\Investigator PDF\CD-bankflow-refactor" rev-parse --show-toplevel
git -C "D:\Investigator PDF\CD-bankflow-refactor" branch --show-current
git -C "D:\Investigator PDF\CD-bankflow-refactor" rev-parse HEAD
git -C "D:\Investigator PDF\CD-bankflow-refactor" rev-parse origin/work/deepseek-12b2-followup
git -C "D:\Investigator PDF\CD-bankflow-refactor" status --short
git -C "D:\Investigator PDF\CD-bankflow-refactor" status
git -C "D:\Investigator PDF\CD-bankflow-refactor" log --oneline -10
git -C "D:\Investigator PDF\CD-bankflow-refactor" remote -v
```

Checksum 复核（PowerShell）：

```powershell
Get-FileHash "D:\Investigator PDF\outputs\knowledge-v1\production-candidate-v2.1-blind-run-20260809\production_candidate_v2_1_blind_transaction_predictions.jsonl" -Algorithm SHA256
Get-FileHash "D:\Investigator PDF\outputs\knowledge-v1\production-candidate-v2.1-blind-run-20260809\production_candidate_v2_1_blind_case_predictions.json" -Algorithm SHA256
Get-FileHash "D:\Investigator PDF\outputs\knowledge-v1\production-candidate-v2.1-blind-run-20260809\production_candidate_v2_1_blind_prediction_checksums.json" -Algorithm SHA256
Get-FileHash "$env:LOCALAPPDATA\BankFlowReview\ai_runtime.json" -Algorithm SHA256
```

预期：

- HEAD = origin = `47c4d0b0fbd43fe8e41e8cb702befdff186e0b83`
- Semantic `4e80dfdf…`、Runtime `d5a65e0f…`、Gold aggregate `bfa5a0c1…`、Prediction Freeze aggregate `5bd61e49…`
- External runtime SHA256 `dee20b06…`、batch_size=20

---

*Handoff 完成；未 commit、未 push。*
