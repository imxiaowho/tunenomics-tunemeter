# TuneMeter · 元舵用量计

**TuneMeter by Tunenomics**：离线采集本机 Agent 用量，生成一个默认脱敏的元舵提交包。CLI 是核心，Agent Skill 是可选入口。

当前补丁 **3.3.6**：提交包内脱敏说明使用 ASCII 文件名 `redaction.md`，减少解压器对中文文件名的识别差异；正文仍是 UTF-8 中文。详见 [兼容性说明](release-docs/ZIP-COMPATIBILITY.md)。既有 3.3.5 回归证据不等同于 3.3.6 已完成完整回归。

## 客户怎么用

下载 CLI ZIP、完整解压，用已有 Python 3.10+ 运行。无需 pip 依赖、账户登录或手动导出账单：

```text
python tunemeter.pyz --version
python tunemeter.pyz collect --source codex --start 2026-10-01 --end 2026-10-07 --timezone +08:00
```

日期仅为示例，请替换。也可选择 pi、workbuddy 或其他已登记来源。stdout 为 JSON；先看 completion_note 和 delivery，exit 4 表示有缺口的结果。只把复核后的“元舵提交包.zip”交给元舵，不上传整个本地报告目录。

**隐私是默认行为**：正文／工具内容、原始路径、会话标识和逐事件明细不入默认提交包；日期、模型和汇总仍保留，因此不是绝对匿名。CLI 不联网、不调用模型、不上传；云端 Agent 阅读报告时可能接收内容。

本工具只采集，不把 token 当作实际扣费，不换算价格、不推算订阅付款；价格核算由元舵处理。

## 能力与证据

九个已实现格式适配器：Codex、Claude Code、Pi、OMP、Gemini、OpenClaw、OpenCode、Qwen、WorkBuddy。它们均有文档限定的虚构格式运行证据，**不等于所有真实客户端版本或平台已适配**。Windows 11/Python 3.12.14 是直接验证环境。

- [完整启动指南](release-docs/START-HERE.md)
- [支持矩阵](release-docs/SUPPORT.md)
- [隐私边界](release-docs/PRIVACY.md)
- [验证说明](release-docs/VERIFICATION.md)与[回执](release-docs/verification-receipt.json)

## 从源码构建与复测

不需要第三方运行依赖。构建会生成 dist/ 下的 app、CLI ZIP、可选 Skill ZIP 和干净源码 ZIP：

```text
python scripts/build_tunemeter.py
python scripts/verify_tunemeter_release.py --package dist/tunenomics-tunemeter-cli-v3.3.6.zip --output <new-directory-outside-repo>
python scripts/verify_tunemeter_harnesses.py --package dist/tunenomics-tunemeter-cli-v3.3.6.zip --output <another-new-directory-outside-repo>
```

测试自动生成虚构目录；不会扫描默认真实用量根。Skill 源在 skills/tunenomics-tunemeter，安装方式依调用平台而异，不保证其他平台安装兼容。

## 许可证与来源

[MIT License](LICENSE)，Copyright (c) 2026 Tunenomics。[来源说明](UPSTREAMS.md)。保留许可证不代表来源代码或数据经过独立审计。项目不包含客户账单、真实使用记录、账户配置或凭据。
