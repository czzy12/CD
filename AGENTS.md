# AGENTS.md

本文件给 coding agent 使用，记录本项目的协作规则和入口。项目状态、历史细节和样本排查不要堆在这里。

## 项目定位

本项目是银行流水 PDF / Excel / 微信流水解析工具，目标是把多银行流水解析为统一交易模型，并提供 GUI、月度统计、异常提示、流水调整、Excel 导出和收入佐证 JSON 输出。

本项目后续作为车贷报告自动化总项目的流水子模块。总项目不应重新实现流水识别。

## 工作原则

- 小范围修改，避免无关重构。
- 不做需求外功能，不做 speculative abstraction。
- 不删除已有银行适配逻辑，除非明确确认无用。
- 遇到不确定的银行格式或业务口径，先说明假设。
- GUI 改动默认只影响展示层，不改变解析结果或导出数据，除非需求明确。
- 可信度只作为 GUI 提示，不写入 Excel，不作为业务硬判断。
- 不把逐文件金额、笔数、客户本地路径等细账长期写入 `PROJECT_STATUS.md`。

## 关键入口

- `gui_v2.py`：当前源码 GUI 入口。
- `bankflow_v2/models.py`：标准交易模型。
- `bankflow_v2/auto_detect.py`：银行类型识别。
- `bankflow_v2/pipeline.py`：解析调度入口。
- `bankflow_v2/summary.py`：汇总和异常校验。
- `bankflow_v2/adjustment.py`：流水调整/测算层。
- `bankflow_v2/income_proof_export.py`：收入佐证 JSON 输出。
- `tools/regression.py`：统一回归入口。
- `tools/regression_cases.json`：回归样本清单。
- `PROJECT_STATUS.md`：当前状态概要。
- `技术变更记录.md`：详细问题、原因、解决方式和验证结果。
- `银行适配手册.md`：银行格式和适配规则。
- `INTEGRATION_CONTRACT.md`：与车贷报告自动化总项目的集成契约。

## 银行适配要求

新增或修复银行格式时，通常需要同步检查：

- `bankflow_v2/auto_detect.py`
- `bankflow_v2/pipeline.py`
- 对应银行解析器
- `tools/regression_cases.json`
- `银行适配手册.md`
- `技术变更记录.md`

解析器应尽量保留原始字段、原始金额、原始余额和问题提示，方便复核。

## 验证要求

常规 GUI 或文档改动至少运行：

```powershell
python -m py_compile gui_v2.py tools\regression.py
```

涉及解析、识别、汇总、调整或导出时运行：

```powershell
python tools\regression.py --all --allow-missing
```

涉及单个银行适配时，优先运行对应 tag：

```powershell
python tools\regression.py --tag xxx --allow-missing
```

## 文档记录要求

重要更新要记录：

- 遇到的问题
- 原因分析
- 做了哪些调整
- 验证命令和结果
- 影响范围

记录位置：

- 当前状态概要：`PROJECT_STATUS.md`
- 详细过程：`技术变更记录.md`
- 银行格式规则：`银行适配手册.md`
- 总项目接口：`INTEGRATION_CONTRACT.md`

## 运行注意

- `启动GUI.bat` 通过 `python gui_v2.py` 启动源码 GUI。
- `dist\BankFlowGUI\BankFlowGUI.exe` 不一定代表最新源码。
- 当前不稳定支持扫描图片 PDF OCR。
