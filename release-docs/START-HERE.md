# TuneMeter · 元舵用量计

本包是 TuneMeter CLI 3.3.5 本地交付候选。Python 3.10+，无第三方运行依赖。只采集本机已知格式中的用量，不把 token 换算成订阅账单或实际消费；价格核算交给元舵。

## 1. 解压与启动

解压整个 ZIP，在该目录打开终端。Windows 若命令名是 python，可直接运行；只有 py 时用 py -3 替代 python。先确认：

```text
python --version
python tunemeter.pyz --version
python tunemeter.pyz --help
```

不需要安装 Skill、pip 包或后台服务。没有 Python 时由你自行从可信来源安装；本包不自动安装、不登录账户、不请求密码或 API key。测试环境为 Windows 11/Python 3.12.14；其他平台／Python 版本尚未直接验证。

## 2. 选择来源和日期

先针对自己使用的底座发现目录：

```text
python tunemeter.pyz discover --source codex
python tunemeter.pyz doctor --source codex
python tunemeter.pyz collect --source codex --start 2026-10-01 --end 2026-10-07 --timezone +08:00
```

请替换为实际需要的日期；start/end 都包含当天，今天只统计至运行快照。需要多个来源时：

```text
python tunemeter.pyz collect --source codex,pi,workbuddy --start 2026-10-01 --end 2026-10-07 --timezone +08:00
python tunemeter.pyz collect --source pi --source-root pi="D:/selected/pi-agent" --start 2026-10-01 --end 2026-10-07
```

根覆盖含义见 harnesses.md。不要将不相关磁盘或文件夹作为根。all 只指九个已登记适配器，不代表全盘软件识别；它会访问这些来源的已知默认用量根，仅在你希望采集它们时使用。

## 3. 读结果并提交

默认每次写入用户目录 TuneMeter/reports 的新批次。终端 stdout 是 JSON：

- 先读 completion_note；再看 delivery、coverage_gaps、warnings。
- delivery.status=ready_for_customer_review：可审阅；不等于数据完整或费用已确认。
- delivery.status=blocked：没有正式提交 ZIP，仅保留诊断；不要发送这些合计充当可靠账单。
- artifacts.submission_package 是唯一需要交给元舵的“元舵提交包.zip”。先读包内 ts-ai-cost-intake.md 和脱敏说明，再通过你自己的渠道上传。本工具不会上传。
- 不要发送整个本地报告文件夹：它包含仅供本机诊断的事件／时间明细。

## 4. 退出码

| code | 含义 |
| --- | --- |
| 0 | 该命令成功，所需证据按命令语义可用；不证明历史完整 |
| 4 | 有缺口的结果，检查 JSON，通常仍有可审阅材料；不等于程序崩溃 |
| 3 | collect 无可计量记录，或发现／来源选择不可用；不能解释为零消费 |
| 2 | 参数／schema／快照一致性问题，或 export 因身份关系要求重采而被拒绝；看 status/error_kind/delivery |
| 1 | 文件／I/O 处理错误；看安全错误类别 |

脚本调用应读取 JSON 和实际退出码，不要把所有非零码当作同一故障。discover/doctor 的状态与 collect 不同，必须结合 status 判断。

## 5. 已有批次不重复扫描

```text
python tunemeter.pyz report --input "D:/selected/batch" --format json
python tunemeter.pyz report --input "D:/selected/batch" --format html
python tunemeter.pyz export --input "D:/selected/batch" --profile ts
```

JSON report 不写 HTML。明细与声明冲突时返回 SnapshotConsistencyError 和安全 error_details；不要手改数字绕过检查。Pi 3.3.0 及更早用量快照需重采；当前父链未解决也阻止正式 ZIP。省略明细时来源合计未知，不填零。

支持范围见 SUPPORT.md；隐私见 PRIVACY.md；实际验证范围见 VERIFICATION.md 和 verification-receipt.json。MIT 许可见 LICENSE。提交包是用量材料，不是厂商发票或付款凭证。
