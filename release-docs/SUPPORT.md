# 支持范围：实现、合成验证与真实客户端分开

本版本登记九个格式适配器。Windows 11/Python 3.12.14 上已直接运行固定虚构格式回归；这不是客户端版本全面兼容或官方格式认证。公开说明只承诺下列已实现路径，未知来源不探测、不补零。

| 来源 | 已实现读取 | 直接合成验证 | 主要限制 |
| --- | --- | --- | --- |
| codex | sessions/archived_sessions JSONL | 累计差分、复制去重、reset、缺字段、结束轮次 | 完整 fork 历史与所有版本未验证；时间包含工具与等待 |
| claude | projects assistant JSONL | 映射、缺缓存、metadata-only、损坏源隔离 | 不含 Desktop/Cowork、WSL 或所有 profile |
| pi | sessions JSONL | 原路径／归档父链、同名歧义、循环、导入拦截 | 父链未知保守拦截；不全局按短 ID 去重 |
| omp | sessions JSONL message/model_usage | 两类型身份区分及基础字段场景 | 不推断 Pi 的全部 fork 兼容性 |
| gemini | 已知 chats JSON/JSONL | chat JSON/messages 基础场景 | 所有 JSONL/流式变体未验证 |
| openclaw | agents sessions JSONL | 基础映射；数据库缺口显式报告 | SQLite／压缩内容未支持 |
| opencode | message JSON、选定 message/session_message SQLite | 两种 SQLite 布局、只读、sidecar/未知表跳过 | 不含 part-only/raw-usage；不读活动 sidecar |
| qwen | chats usageMetadata JSONL | 基础映射、缺缓存、空／损坏源 | 其他客户端布局未确认 |
| workbuddy | projects 主会话与已知 subagents JSONL | 字段／类型映射、导入、混合汇总 | 格式参考 2.137.1；跨版本、恢复／镜像语义未全面验证 |

外部 Agent 曾报告 Codex/Pi/WorkBuddy 的特定本机真实日志回归通过，本项目未独立复跑该客户数据；不把这些数字作为公开测试样例或全面版本认证。

所有来源的事件单位是“用量观察”，不是已确认计费请求。来源间镜像尚未去重。时间仅测得 Codex 已结束区间，其他来源为未知。缺字段、not_collected 与计费不适用不同。Tunenomics 承担下游价格换算，本工具不生成 API 等价费用或订阅费分摊。

实际验证环境和状态以 verification-receipt.json 为准。跨平台、Python 3.10/3.11、性能、大文件与全部真实版本均未由本轮验证。
