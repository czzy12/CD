# PDF流水项目当前状态

更新时间：2026-05-31

## 当前仓库

源码仓库：

```text
D:\Codex data\CD
```

当前分支：

```text
work/2026-05-31-flow-adjustment
```

远端跟踪：

```text
origin/work/2026-05-31-flow-adjustment
```

当前基础提交：

```text
44a1d24 Add BOC corporate parser and delivery notes
```

当前本地文档变更：

- `PROJECT_CONTEXT.md` 已轻量整理为项目入口。
- `PROJECT_STATUS.md` 记录当前最新状态。
- `INTEGRATION_CONTRACT.md` 记录与车贷报告自动化总项目的集成契约。

## 当前能力概览

当前项目已经具备：

- PDF 银行流水识别。
- Excel 流水导入。
- 微信流水识别。
- 多银行专用解析器。
- 通用 PDF 兜底识别。
- 余额连续性校验。
- 月度统计。
- 文件汇总。
- 异常提示。
- 流水调整/测算层。
- GUI。
- Excel 导出。
- 统一回归测试。
- PyInstaller 打包。

## 当前关键模块

| 模块 | 文件 |
|---|---|
| 标准交易模型 | `bankflow_v2/models.py` |
| 银行识别 | `bankflow_v2/auto_detect.py` |
| 解析入口 | `bankflow_v2/pipeline.py` |
| 汇总统计 | `bankflow_v2/summary.py` |
| 流水调整 | `bankflow_v2/adjustment.py` |
| Excel 导入 | `bankflow_v2/excel_input.py` |
| GUI | `gui_v2.py` |
| 统一回归 | `tools/regression.py` |
| 回归样本 | `tools/regression_cases.json` |

## 当前支持银行与格式

以 `银行适配手册.md` 为详细准则。

当前主要支持：

- 工商银行个人历史明细。
- 工商银行个人活期/定期混排。
- 工商银行对公旧版 A/B。
- 工商银行企业存款对账单新版 C。
- 建设银行个人。
- 建设银行对公活期存款明细账。
- 农业银行个人。
- 农业银行对公。
- 中国银行对公活期明细。
- 交通银行 6 列日期版。
- 交通银行 11 列时间版。
- 邮储银行历史明细。
- 招商银行个人交易流水。
- 民生银行对公单位账户对账单。
- 中信银行个人账户交易明细。
- 浦发银行个人。
- 浦发银行对公。
- 微信流水。
- Excel 导入。
- 通用 PDF 兜底。

## 最新功能状态

### 流水调整/测算层

已实现：

- `bankflow_v2/adjustment.py`
- GUI 右侧流水调整面板。
- 收入调整（微信）。
- 收支平衡调整（个/公）。
- 固定分配/确定性随机分配。
- 调整后月度统计。
- Excel 导出保留原始和调整后统计。

调整层不修改原始流水明细，不污染银行解析器。

### GUI 现代化

已实现：

- 顶部主次操作栏。
- 日期筛选模块。
- 左主内容区 + 右调整面板。
- 摘要仪表板。
- 调整预览结果卡。
- 下划线风格 tabs。

### 新增对公格式

已实现：

- 建设银行对公活期存款明细账。
- 中国银行对公活期明细文本流水。

## 当前验证结果

最近执行：

```powershell
python -m py_compile bankflow_v2\summary.py bankflow_v2\pipeline.py bankflow_v2\adjustment.py gui_v2.py tools\regression.py
```

结果：

```text
通过
```

最近执行：

```powershell
python tools\regression.py --all
```

结果：

```text
19 PASS / 5 FAIL
```

说明：

5 个 FAIL 均为本机缺少桌面路径样本文件，不是解析逻辑失败。

缺失样本包括：

- `C:\Users\lenovo\Desktop\马培忠\流水\民生对公.pdf`
- `C:\Users\lenovo\Desktop\李翠\新建文件夹\...pdf`

技术记录中同类情况可按：

```powershell
python tools\regression.py --all --allow-missing
```

视为样本缺失跳过，目标结果应为：

```text
19 PASS / 0 FAIL / 5 SKIP
```

## 当前不支持或不作为稳定核心

- 扫描/图片 PDF 直接 OCR。
- 密码/加密 PDF 自动破解。
- 兴业银行 PDF 直解。
- 工资类完整原字段专项导出。
- 完整车贷报告生成。
- 征信说明。
- 企业信息说明。

图片 PDF 当前建议：

```text
先用外部工具转 Excel -> 再导入本项目
```

## 与车贷报告自动化总项目的关系

本项目后续是总项目中的流水子模块。

推荐链路：

```text
PDF / Excel / 微信流水
  -> Transaction
  -> Summary / Adjustment
  -> 标准 JSON
  -> 收入佐证 Word
  -> 车贷报告自动化总项目读取
```

总项目不应重新实现流水识别。

## 下一步优先级

### 第一优先级

新增标准 JSON 导出：

```text
bankflow_v2/result_export.py
```

建议接口：

```python
build_bankflow_result(transactions, adjustment_result, metadata) -> dict
write_bankflow_json(result, path) -> None
```

### 第二优先级

新增收入佐证 Word 填写：

```text
bankflow_v2/word_fill.py
templates/收入佐证模板.docx
```

Word 填写只读取标准结果，不直接解析 PDF。

### 第三优先级

GUI 增加：

```text
导出收入佐证 Word
导出标准 JSON
```

Excel 导出保持不变。

### 第四优先级

为 JSON 和 Word 输出补充测试。

建议测试：

```text
固定输入交易/调整结果 -> 输出 JSON -> 校验关键字段
固定 JSON -> 填写 Word -> 校验关键占位符替换
```

## 更新文档规则

后续任何重要更新：

1. 更新本文件。
2. 更新 `技术变更记录.md`。
3. 涉及银行适配时更新 `银行适配手册.md`。
4. 涉及总项目接口时更新 `INTEGRATION_CONTRACT.md`。
