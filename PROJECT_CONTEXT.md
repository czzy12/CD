# PDF银行流水识别项目上下文

## 必读顺序

以后继续本项目时，优先按下面顺序读取：

1. `PROJECT_CONTEXT.md`：项目入口和工作约束。
2. `PROJECT_STATUS.md`：当前最新状态、分支、验证结果和下一步。
3. `INTEGRATION_CONTRACT.md`：与车贷报告自动化总项目的集成契约。
4. `技术变更记录.md`：历史变更、问题原因、解决方式和验证结果。
5. `银行适配手册.md`：当前支持银行、版式和适配说明。

除非需要追溯历史问题，不要每次完整读取长篇历史记录。

## 当前定位

本项目是 PDF / Excel / 微信流水识别与统计工具，后续会作为车贷报告自动化总项目的流水子模块。

当前源码仓库：

```text
D:\Codex data\CD
```

当前资料与样本入口：

```text
D:\Codex data\CD_assets
```

当前 Obsidian 记忆：

```text
D:\OneDrive\应用\remotely-save\Note Data\Vibe Coding\PDF流水
```

## 当前分支

当前开发分支：

```text
work/2026-05-31-flow-adjustment
```

远端分支：

```text
origin/work/2026-05-31-flow-adjustment
```

## 项目目标

优先保证统计字段准确，不追求提取流水中的所有字段。

核心字段：

- 交易时间。
- 收入金额。
- 支出金额。
- 余额。

辅助字段：

- 银行。
- 页码。
- 行号。
- 原始时间文本。
- 原始金额文本。
- 原始余额文本。
- 校验状态。
- 异常原因。

## 核心架构

不要使用大模型一次性从 PDF 生成最终表格。

当前采用：

```text
PDF / Excel / 微信流水
  -> 文本/表格提取
  -> 银行识别
  -> 银行适配器解析候选交易
  -> Transaction 标准模型
  -> Summary 统一统计
  -> Adjustment 可选测算
  -> Excel / 后续 JSON / 后续 Word
```

核心原则：

```text
PDF / Excel / 微信流水 -> Transaction -> Summary / Adjustment -> 标准 JSON -> Word / 总项目读取
```

不要把 Word 填写或车贷总项目逻辑写进银行解析器。

## 关键代码位置

| 文件/目录 | 作用 |
|---|---|
| `bankflow_v2/models.py` | `Transaction` 标准模型 |
| `bankflow_v2/pipeline.py` | 按银行调用解析器 |
| `bankflow_v2/auto_detect.py` | 银行/版式自动识别 |
| `bankflow_v2/summary.py` | 排序、汇总、月度统计、异常收集 |
| `bankflow_v2/adjustment.py` | 微信/个公流水调整测算层 |
| `bankflow_v2/excel_input.py` | Excel 流水导入 |
| `gui_v2.py` | 当前 GUI 和 Excel 导出 |
| `tools/regression.py` | 统一回归入口 |
| `tools/regression_cases.json` | 回归样本清单 |

## 统计口径

期初余额不能直接取第一笔交易记录的余额，因为流水中的余额通常是“该笔交易后余额”。

统一计算：

```text
期初余额 = 第一笔交易后余额 - 第一笔收入 + 第一笔支出
期末余额 = 最后一笔交易后余额
余额变动 = 期末余额 - 期初余额
净额 = 收入合计 - 支出合计
```

校验要求：

```text
余额变动 = 净额
```

## 当前支持范围

当前实际支持范围以 `PROJECT_STATUS.md` 和 `银行适配手册.md` 为准。

总体包括：

- 工商银行个人/对公。
- 建设银行个人/对公。
- 农业银行个人/对公。
- 中国银行对公。
- 交通银行。
- 邮储银行。
- 招商银行。
- 中信银行。
- 民生银行对公。
- 浦发银行个人/对公。
- 微信流水。
- Excel 导入。
- 通用 PDF 兜底识别。

当前不把扫描/图片 PDF 直接 OCR 作为稳定核心；建议先转 Excel 后导入。

## 集成契约

本项目后续会作为车贷报告自动化总项目的流水子模块。

开发时必须参考：

- `INTEGRATION_CONTRACT.md`
- `D:\OneDrive\应用\remotely-save\Note Data\Vibe Coding\PDF流水\项目集成记忆.md`
- `D:\OneDrive\应用\remotely-save\Note Data\车贷\自动化项目\05-子项目与总项目集成规范.md`

本项目负责：

- 流水识别。
- 流水统计。
- 流水调整。
- 流水结构化结果。
- 收入佐证 Word。

本项目不负责：

- 车贷产品路径判断。
- 征信说明。
- 企业信息说明。
- 完整调查报告生成。
- 系统粘贴文本总控。

## 固定验证命令

打包或重要修改前执行：

```powershell
python -m py_compile bankflow_v2\summary.py bankflow_v2\pipeline.py bankflow_v2\adjustment.py gui_v2.py tools\regression.py
python tools\regression.py --all
```

如果回归失败只是因为本机缺少样本文件，需要明确记录为“样本缺失”，不要等同于解析失败。

## 文档维护规则

重要更新后：

1. 更新 `PROJECT_STATUS.md`。
2. 更新 `技术变更记录.md`。
3. 如涉及银行解析，更新 `银行适配手册.md`。
4. 如涉及总项目接口，更新 `INTEGRATION_CONTRACT.md`。
5. 如果是 Obsidian 侧记忆，也同步更新：

```text
D:\OneDrive\应用\remotely-save\Note Data\Vibe Coding\PDF流水
```

## 下一步方向

当前优先方向：

1. 新增标准 JSON 导出。
2. 新增收入佐证 Word 填写。
3. GUI 增加导出收入佐证 Word 的入口。
4. 保持现有银行解析器和 Excel 导出稳定。
5. 为 JSON 和 Word 输出补充测试。
