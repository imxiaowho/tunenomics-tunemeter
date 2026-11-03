"""One allowlisted aggregate handoff; no originals or detailed rows."""
from pathlib import Path
import hashlib
import json
from . import __version__, engine
from .contracts import SUBMISSION_SCHEMA


def delivery(data):
    """Gate external bundles; diagnostic reports remain available."""
    validity = data.get("aggregation_validity", "unknown")
    reasons = []
    if validity in {"limited", "requires_recollection"}:
        reasons.append("identity_scope_requires_recollection" if validity == "requires_recollection" else "identity_coverage_unresolved")
    pi_usage = any(row.get("source", row.get("harness")) == "pi" and (row.get("usage_events") or 0) > 0
                   for row in data.get("source_inventory", []) + data.get("by_source", []))
    pi_sources = [row for row in data.get("source_inventory", []) if row.get("source") == "pi"]
    if pi_usage and not reasons and (validity != "source_rules_applied" or not pi_sources
                                    or any(row.get("aggregation_validity") != "declared_lineage_resolved" for row in pi_sources)):
        reasons.append("pi_accounting_validity_unknown")
    return {"status": "blocked" if reasons else "ready_for_customer_review", "reasons": reasons}


def completion_note(data):
    """Explain existing evidence and delivery state without asserting completeness."""
    active = sum((row.get("usage_events") or 0) > 0 for row in data.get("by_source", []))
    parts = [f"{active} 个来源有本期用量记录"] if data.get("by_source") else ["来源统计未知"]
    unknown_sources = sum(row.get("usage_events") is None for row in data.get("by_source", []))
    if unknown_sources:
        parts.append(f"{unknown_sources} 个来源的记录数未知")
    gaps = data.get("coverage_gaps", data.get("completion", {}).get("gaps", []))
    kinds = {gap.get("kind") for gap in gaps}
    absent = sum(len(gap.get("sources", [])) for gap in gaps if gap.get("kind") == "source_roots_not_found")
    if absent:
        parts.append(f"{absent} 个来源的数据根未找到")
    if "source_not_ready" in kinds:
        parts.append("部分来源未就绪，详见来源状态")
    if "turn_time_not_observed" in kinds:
        parts.append("部分来源耗时未采集")
    if "field_missing" in kinds:
        parts.append("部分记录字段缺失，详见字段名与缺失数量")
    if "field_not_collected" in kinds:
        parts.append("部分字段尚未采集，不代表不适用")
    if kinds & {"field_eligibility_unknown", "source_events_unavailable_in_snapshot"}:
        parts.append("原快照的部分字段或事件证据未知")
    if "source_events_unavailable_in_snapshot" in kinds:
        parts.append("仅保留原有汇总，不能据此重建各来源 token 合计")
    if "source_diagnostic" in kinds:
        parts.append("存在数据诊断缺口")
    if delivery(data)["status"] == "blocked":
        parts.append("提交包已拦截，仅供诊断，需重新采集或核验身份关系")
    elif not (data["summary"]["usage_events"] or data["summary"].get("completed_turns")):
        parts.append("未取得可计量数据，不建议提交")
    else:
        parts.append("可生成提交包，需客户复核；历史完整度未知")
    return "；".join(parts) + "。"


def project(usage, billing):
    # The legacy projection is retained as the accounting compatibility boundary.
    local = dict(usage)
    local["billing"] = {"actual_amount": None, "currency": None, "estimate": None}
    result = engine.submission_summary(local)
    result.update(schema_version=SUBMISSION_SCHEMA, product="TuneMeter", packager_version=__version__)
    result["source_collector_version"] = usage.get("source_collector_version", usage["collector_version"])
    result["financials"] = billing
    result["identity_context"] = {"source_kind": "codex_rollout", "harness": "codex",
                                  "model_provider": None, "billing_channel": None, "account_alias": None,
                                  "billed_model": None, "request_count": None}
    if usage.get("collection_context"):
        result["identity_context"] = usage["identity_context"]
        result["collection_context"] = usage["collection_context"]
        result["source_inventory"] = usage["source_inventory"]
        result["by_source"] = usage["by_source"]
        result["provider_contracts"] = usage["provider_contracts"]
        result["completion"] = usage["completion"]
        result["warnings"] = usage.get("warnings", {})
        result["coverage_gaps"] = usage.get("coverage_gaps", usage["completion"]["gaps"])
        result["aggregation_validity"] = usage.get("aggregation_validity", "unknown")
        result["sources"]["scope"] = usage["collection_context"]["harnesses"]
        for key in ("field_observations", "data_semantics", "input_size_distribution"):
            result[key] = usage[key]
        for key in ("not_collected_field_events", "eligibility_unknown_field_events", "unobserved_field_events"):
            if key in usage["summary"]:
                result["summary"][key] = usage["summary"][key]
        for section, keys in (("models", ("model",)), ("daily", ("date",)), ("hourly", ("hour_start",)),
                              ("daily_by_model", ("date", "model")), ("hourly_by_model", ("hour_start", "model"))):
            originals = {tuple(row[k] for k in keys): row for row in usage[section]}
            for row in result[section]:
                original = originals[tuple(row[k] for k in keys)]
                for key in ("missing_field_events", "not_collected_field_events", "eligibility_unknown_field_events", "unobserved_field_events"):
                    if key in original:
                        row[key] = original[key]
        result["limits"] += ["price conversion out of scope; Tunenomics performs downstream pricing",
                             "time covers Codex only; other harness durations are unknown",
                             "cross-harness mirrored records are not deduplicated"]
    tier = usage.get("service_tier", {})
    result["service_tier"] = {k: tier.get(k) for k in (
        "status", "source_availability", "billing_tier_confirmed", "billed_service_tier", "configured_tiers")}
    result["redaction"]["review_status"] = {
        "aggregate_projection_applied": True, "attachment_review_declared": False,
        "customer_review_pending": True}
    result["redaction"]["privacy_level"] = "redacted_aggregates_not_anonymous"
    result["redaction"]["retained_categories"] = ["harness_labels_and_statuses",
        "calendar_dates_and_snapshot", "configured_model_labels", "time_and_model_aggregates",
        "usage_distributions", "configured_service_tiers", "selected_financial_facts_and_neutral_aliases"]
    result["delivery"] = delivery(result)
    result["completion_note"] = completion_note(result)
    return result


def handoff(data):
    text = engine.intake(data, submission=True).replace("Tunenomics UCO", "TuneMeter")
    if delivery(data)["status"] == "blocked":
        text = "**用量可信度：继承关系未确认或旧版 Pi 去重范围存在缺陷；当前合计不用于对外交付，需重新采集并核验。**\n\n" + text
    text = text.replace("处理档位为未采集、源可得性未核验", "处理档位状态以 /service_tier 为准；配置档位不是确认计费档位")
    text = text.replace("处理档位：原记录可得性未核验", "处理档位：按实际记录展示")
    tier_status = data["service_tier"].get("status") or "unknown"
    text = "\n".join(
        f"| 处理档位 | {tier_status} | L1 /service_tier：仅配置档位，实际计费未确认 | 匹配的费用／响应证据 |"
        if line.startswith("| 处理档位 |") else line for line in text.splitlines()) + "\n"
    # Keep the legacy 13 sections. Extend financial evidence without inferring fees.
    fin = data["financials"]
    text = text.replace("本材料没有费用估算或账单金额", "参考价未计算；选定费用证据在附录单独列示")
    if fin["records"]:
        text = text.replace("部分完成：仅本机观测用量；账单输入未提供", "部分完成：本机观测用量与选定费用证据；限制见附录")
        text = text.replace("未提供正式账单、平台费用或付款凭证", "费用证据状态见附录；原始材料未附入")
        text = "\n".join("| 实际金额与账期 | 部分提供 | L1 /financials：选定证据及声明，非全量实付 | 匹配范围与缺少的支付／计费来源 |"
                         if line.startswith("| 实际金额与账期 |") else line for line in text.splitlines()) + "\n"
    rows = ["\n## TuneMeter 费用证据补充", "", f"采集完成度：{data.get('completion', {}).get('collection_status', 'unknown')}；历史完整度未知，处理完成不表示数据齐全。", "",
            "金额仅覆盖选定材料；documented 是整理方声明，非独立核验。",
            "付款、账单、套餐分别列示，不能相加。完整性未知；未提供不是零。", "",
            "| 视图 | 币种 | 已知部分金额 | 状态 |", "| --- | --- | ---: | --- |"]
    for key, label in [("payments_by_currency", "付款"), ("charges_by_currency", "账单费用，付款未确认")]:
        for row in fin[key]:
            rows.append(f"| {label} | {row['currency']} | {row['known_amount'] if row['known_amount'] is not None else '未知'} | {row['status']} |")
    for plan in fin["plans_covering_period"]:
        rows.append(f"\n套餐 {plan['record_id']} / {plan['scope_alias']}：{plan['currency']} {plan['amount']}；{plan['evidence_status']}；周期 {plan['period_start']} 至 {plan['period_end_exclusive']}。覆盖本期不表示本期支付。")
    rows += ["", "价格换算由元舵负责，不属于 TuneMeter 采集范围。费用分摊未启用；额度只来自选定快照，不由 token 推算。",
             f"配置档位状态：{data['service_tier'].get('status') or 'unknown'}；计费档位未确认。",
             f"重复材料候选组：{len(fin['duplicate_candidates'])}；未匹配记录：{len(fin['unmatched'])}。",
             f"冲突证据组：{len(fin['conflicting_evidence'])}；冲突不能当作零费用或全量确认。",
             "仅交付脱敏汇总；没有附入原始支付／会话材料。manifest 校验文件一致性，不证明原始证据真实性。"]
    return completion_note(data) + "\n\n" + text + "\n".join(rows) + "\n"


def entries(data):
    if delivery(data)["status"] == "blocked":
        raise ValueError("Unresolved accounting cannot be packaged for delivery")
    output = {"README.txt": ("TuneMeter · 元舵提交包\n\n先阅读 ts-ai-cost-intake.md 和 redaction.md，复核后自行提交本 ZIP。\n"
        "这是脱敏汇总，不是匿名数据：保留日期、模型、时间分布及选定费用信息，组合后仍可能被识别。\n"
        "付款、账单、套餐和参考价是不同视图，不能相加。未提供金额不等于零；本包没有原始证据。\n"
        "JSON/CSV 是同一批用量的不同视图，不能重复累加。CSV 为 UTF-8 BOM；空值表示未知。\n"
        "脚本没有上传或发送；当前对话后续使用不在快照内。\n").encode(),
        "redaction.md": (engine.redaction_note() + "\n额外保留：Harness 名称、状态及按底座聚合；native_usage 数值只在本机明细中，不进入提交包。\n").encode(),
        "ts-ai-cost-intake.md": handoff(data).encode(),
        "summary.json": json.dumps(data, ensure_ascii=False, indent=2).encode()}
    for name, columns in [("models", ["model", "usage_events", *engine.FIELDS, "turn_seconds", "covered_seconds"]),
                          ("daily", ["date", "usage_events", *engine.FIELDS, "turn_seconds", "covered_seconds"]),
                          ("hourly", ["hour_start", "usage_events", *engine.FIELDS]),
                          ("daily_by_model", ["date", "model", "usage_events", *engine.FIELDS]),
                          ("hourly_by_model", ["hour_start", "model", "usage_events", *engine.FIELDS])]:
        output[name + ".csv"] = engine.csv_bytes(data[name], columns)
    if "by_source" in data:
        output["sources.csv"] = engine.csv_bytes(data["by_source"], ["harness", "status", "time_status", "usage_events", *engine.FIELDS])
    manifest = {"schema": "tunemeter-manifest/1.0.0", "generator_version": __version__,
                "source_collector_version": data["source_collector_version"], "snapshot_at": data["snapshot_at"],
                "files": [{"name": name, "sha256": hashlib.sha256(value).hexdigest()} for name, value in output.items()],
                "limits": "integrity only; not independent verification of source records"}
    output["manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2).encode()
    return output


def write(data, parent):
    return engine.write_bundle(entries(data), Path(parent))
