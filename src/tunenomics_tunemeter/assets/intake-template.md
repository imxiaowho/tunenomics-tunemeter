# Tunenomics UCO 用量成本材料

## 1. 生成信息

- Skill 版本：3.3.5
- 模板版本：uco-intake/1.2.0
- 生成时间与时区：{{generated_at}}
- 批次状态：{{status}}
- 模型/工具处理路径与客户选择：{{processing_path}}
- 本文件用途：材料清单、字段映射与摘要；原始账单仍为证据。

## 2. 平台、账期与计费形态

| 平台/产品 | 来源/依据 | 账期和时区 | 计费类型 | 币种/单位 | 覆盖限制 |
| --- | --- | --- | --- | --- | --- |
| {{provider_product}} | {{evidence}} | {{period}} | {{billing_type}} | {{currency_unit}} | {{coverage}} |

## 3. 来源清单

| 来源别名 | 格式 | 读取范围/定位 | 状态 | 未处理内容与原因 |
| --- | --- | --- | --- | --- |
| {{source_alias}} | {{format}} | {{location}} | {{source_status}} | {{unprocessed}} |

## 4. 源字段到标准字段

| 来源/位置 | 安全源字段名 | 标准字段 | 原值单位/口径 | 处理规则/确认状态 |
| --- | --- | --- | --- | --- |
| {{source_ref}} | {{source_field}} | {{standard_field}} | {{semantics}} | {{handling}} |

## 5. 观测用量

| 来源/位置 | 模型/产品 | 测量字段 | 值 | 单位 | 增量/累计/周期及重叠口径 |
| --- | --- | --- | --- | --- | --- |
| {{source_ref}} | {{model}} | {{usage_field}} | {{value}} | {{unit}} | {{counting_semantics}} |

汇总及是否计算：{{usage_totals_and_limits}}

## 6. 账单实际金额与平台费用记录

| 来源/位置 | 金额类别 | 来源原值 | 币种 | 账期 | 正式账单/平台费用/付款凭证及限制 |
| --- | --- | --- | --- | --- | --- |
| {{source_ref}} | {{amount_type}} | {{amount}} | {{currency}} | {{period}} | {{record_kind}} |

合计依据与覆盖：{{billed_total_basis}}

## 7. 订阅、席位与额度

| 来源/位置 | 套餐/周期 | 固定费用/币种 | 席位 | 内含/购买/使用/剩余额度及单位 | 到期与限制 |
| --- | --- | --- | --- | --- | --- |
| {{source_ref}} | {{plan_cycle}} | {{plan_fee}} | {{seats}} | {{quotas}} | {{expiry_limits}} |

## 8. 估算口径（如有）

- 是否估算/是否来源自带估算：{{estimate_status}}
- 可复算公式与使用数据来源：{{formula}}
- 费率来源、生效日期、计量单位：{{rates}}
- 假设、舍入与未计价覆盖：{{estimate_limits}}
- 与实际账单的关系：{{estimate_vs_bill}}

## 9. 重复、缺失与异常

| 来源/位置 | 问题 | 处理 | 对结果的影响 |
| --- | --- | --- | --- |
| {{source_ref}} | {{issue}} | {{action}} | {{impact}} |

## 10. 脱敏与数据保留

- 排除/遮蔽的字段类别：{{redacted_categories}}
- 保留的分析字段：{{retained_fields}}
- 文件/工作表别名规则：{{aliases}}
- 原件与中间产物处理：{{source_handling}}
- 客户仍需检查的标识/限制：{{privacy_limits}}

## 11. 待客户补充或确认

{{requested_items}}

## 12. 识别信心与结论限制

- 识别信心与具体依据：{{confidence}}
- 来源记录、客户说明、计算和假设的区别：{{evidence_limits}}
- 未覆盖材料/无法确认事项：{{conclusion_limits}}
- 分享前复核：金额、币种、单位、账期、来源位置和身份信息；本件不构成独立核验或成本诊断。

## 13. 报告输入覆盖与下一采集源

| 报告所需输入 | 状态 | 已有依据与口径 | 缺口／下一可用采集源 |
| --- | --- | --- | --- |
{{report_readiness_rows}}

请求数、用量事件数与对话轮次数分别记录。配置模型不等于已确认的计费模型；按事件时间的小时用量不等于小时账单费用。没有来源时不填金额、项目占比或质量结论。
