"""Offline, escaped report with financial evidence kept in separate panels."""
import html
import json
from .submission import completion_note


def render(usage, billing):
    esc = lambda value: html.escape(str(value), quote=True)
    summary = usage["summary"]
    context = usage.get("collection_context")
    harnesses = ", ".join(context["harnesses"]) if context else "codex"
    hours = lambda key: "未知" if summary[key] is None else f"{summary[key]/3600:.2f}"
    tokens = f"{summary['total_tokens']:,}" if summary["total_tokens"] is not None else "未知"
    payments = "；".join(f"{r['currency']} {r['known_amount']}（已知部分）" for r in billing["payments_by_currency"] if r["known_amount"] is not None) or "未提供／未知"
    plans = "；".join(f"{p['currency']} {p['amount']}（{p['evidence_status']}）" for p in billing["plans_covering_period"]) or "套餐未提供"
    quota = "；".join(f"{r['scope_alias']} 已用 {r['used_percent']}% · 快照 {r['as_of']}" for r in billing["quota_snapshots"]) or "额度未知"
    cards = [("观测用量 · tokens", tokens), ("已确认付款 · 选定材料", payments),
             ("套餐与额度", plans + "；" + quota),
             ("费用核算", "由元舵处理；本工具不换算价格")]
    cards_html = "".join(f"<section class='card'><h2>{esc(title)}</h2><strong>{esc(value)}</strong></section>" for title, value in cards)
    models = "".join(f"<tr><td>{esc(m['model'])}</td><td>{esc(m['total_tokens'] if m['total_tokens'] is not None else '未知／无事件')}</td><td>{esc(m['usage_events'])}</td></tr>" for m in usage["models"])
    days = "".join(f"<tr><td>{esc(d['date'])}</td><td>{esc(d['total_tokens'] if d['total_tokens'] is not None else '未知')}</td></tr>" for d in usage["daily"])
    issues = esc(json.dumps(usage["issues"], ensure_ascii=False))
    sources = "".join(f"<tr><td>{esc(s['harness'])}</td><td>{esc(s['status'])}</td><td>{esc(s['usage_events'] if s['usage_events'] is not None else '未知')}</td><td>{esc(s['total_tokens'] if s['total_tokens'] is not None else '未知')}</td><td>{esc(s['time_status'])}</td></tr>" for s in usage.get("by_source", []))
    fields = "".join(f"<tr><td>{esc(name)}</td><td>{esc(key)}</td><td>{esc(value['collection'])}</td><td>{esc(value['observation'])}</td><td>{esc(value['zero_value_events'])}</td></tr>"
                     for name, contract in usage.get("provider_contracts", {}).items()
                     for key, value in contract["field_evidence"]["normalized_fields"].items())
    validity = usage.get("aggregation_validity", "unknown")
    caution = "用量合计存在未确认继承关系或旧版 Pi 去重缺陷，需重新采集并核验后对外交付。" if validity in {"limited", "requires_recollection"} else "历史完整度和跨底座镜像重叠仍未知。"
    return f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TuneMeter · 元舵用量计</title><style>
body{{font-family:system-ui,sans-serif;margin:0;background:#f3f5f8;color:#172335}}main{{max-width:1100px;margin:auto;padding:32px 20px}}
header p,.note{{color:#526075;line-height:1.7}}.cards{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}}
.card,article{{background:white;padding:24px;border:1px solid #dde3ec;border-radius:16px;margin-bottom:16px;overflow-wrap:anywhere}}h2{{font-size:18px}}strong{{font-size:25px}}table{{width:100%;border-collapse:collapse}}td,th{{padding:12px;text-align:left;border-bottom:1px solid #eee}}.table{{overflow:auto}}
@media(max-width:650px){{.cards{{grid-template-columns:1fr}}main{{padding:20px 12px}}.card,article{{padding:18px}}strong{{font-size:22px}}.table table{{min-width:560px;overflow-wrap:normal}}}}
</style><main><header><p>TUNENOMICS</p><h1>TuneMeter · 元舵用量计</h1>
<p>期间：{esc(usage.get('selected_start') or '全部可用记录')} 至 {esc(usage.get('selected_end_exclusive') or '快照')}（截止不含）<br>快照：{esc(usage['snapshot_at'])} · {esc(usage['timezone'])}</p>
<p>本机来源：{esc(harnesses)} · 历史完整度未知。今天仅截至快照；金额只来自选定证据，价格换算交由元舵。</p></header><div class="cards">{cards_html}</div>
<article><h2>采集完成度</h2><p>{esc(completion_note(usage))}</p><p>{esc(usage.get('completion', {}).get('collection_status', 'unknown'))} · {esc(validity)}</p><p class="note">{esc(caution)} 进程处理完成与字段／时间采集完整度分别记录。</p></article>
<article><h2>底座采集状态</h2><div class="table"><table><tr><th>Harness</th><th>状态</th><th>观测数</th><th>已知 token</th><th>时间状态</th></tr>{sources}</table></div><p class="note">注册不等于安装或可解析；缺失不是零。跨底座镜像记录未去重，不把合计当作无重叠全量。新适配器为格式实现预览，功能与平台核验待完成。</p></article>
<article><details><summary>字段能力与缺失原因</summary><div class="table"><table><tr><th>Harness</th><th>规范化字段</th><th>采集能力</th><th>观测状态</th><th>已知零值观测</th></tr>{fields}</table></div><p class="note">not_collected 表示该解析器尚未采集，missing 表示本次观测未取得该值，not_verified_for_snapshot 表示旧快照未保留原契约。计费适用性仍未知；这些状态都不自动等于不适用或零。原始累计／单事件口径与求差阶段见 JSON 的 provider_contracts；规范化零值可能由已知组成字段计算。</p></details></article>
<article><h2>配置模型分布</h2><div class="table"><table><tr><th>配置模型</th><th>token</th><th>用量事件</th></tr>{models}</table></div><p class="note">配置模型不等于计费模型，事件不是请求。unknown 有耗时但无事件时，token 未知不代表零消费。</p></article>
<article><h2>逐日用量</h2><div class="table"><table><tr><th>日期</th><th>token</th></tr>{days}</table></div></article>
<article><h2>时间与覆盖</h2><p>结束轮次累计 {hours('turn_seconds')} 小时；并发去重覆盖 {hours('covered_seconds')} 小时；未结束轮次 {esc(summary['unfinished_turns'] if summary['unfinished_turns'] is not None else '未知')}。</p>
<p class="note">时间目前只覆盖 Codex；其他底座尚未采集，未知不是零。包含工具和等待，不是人类工时。空小时不证明零用量。异常／排除计数：{issues}</p></article>
<article><h2>计费与证据</h2><p>本期付款状态：{esc(billing['payment_status'])}。documented 是整理方声明，不是独立核验；金额只代表选定证据覆盖的已知部分。</p>
<p class="note">套餐覆盖本周不代表本周付款。账单与对应付款不能重复相加。本工具只采集，价格换算由元舵处理；不从 token 推算额度、实际扣费或节省。</p></article>
<article><h2>复核后提交</h2><p>默认交付“元舵提交包.zip”，内含汇总、缺口与脱敏说明。正文、凭据、会话／事件／轮次明细不入包；日期、模型与用量模式仍可能具有识别性。</p>
<p class="note">原件不改动；脚本没有上传。Agent 打开报告可能将其内容传给模型服务。本页无外部资源或网络调用。</p></article></main></html>"""
