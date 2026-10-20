"""Evidence-bound summaries. No inference from token counts to payment."""
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import re


def instant(value):
    if not isinstance(value, str):
        raise ValueError("An aware ISO timestamp is required")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timestamp must include its offset")
    return result


def money(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{1,15}(?:\.\d{1,8})?", value):
        raise ValueError("Amounts must be bounded positive decimal strings")
    return Decimal(value)


def allocate(fee, cycle_seconds, overlap_seconds, precision=2):
    if cycle_seconds <= 0 or not 0 <= overlap_seconds <= cycle_seconds or not 0 <= precision <= 8:
        raise ValueError("Invalid allocation interval or precision")
    return (Decimal(fee) * Decimal(str(overlap_seconds)) / Decimal(str(cycle_seconds))).quantize(
        Decimal(1).scaleb(-precision), rounding=ROUND_HALF_UP)


def normalize(records):
    if not isinstance(records, list) or len(records) > 1000:
        raise ValueError("Select at most 1000 structured evidence records")
    output = []
    ids = set()
    for row in records:
        if not isinstance(row, dict):
            raise ValueError("Invalid evidence record")
        kind = row.get("kind")
        if kind not in {"payment", "provider_charge", "subscription_plan", "quota_snapshot", "payment_coverage"}:
            raise ValueError("Unsupported evidence kind")
        required = {"record_id": r"E\d+", "source_alias": r"S\d+", "scope_alias": r"A\d+"}
        for field, pattern in required.items():
            if not isinstance(row.get(field), str) or not re.fullmatch(pattern, row[field]):
                raise ValueError("Use neutral E/S/A aliases")
        if row["record_id"] in ids:
            raise ValueError("Duplicate evidence alias")
        ids.add(row["record_id"])
        status = row.get("evidence_status")
        if status not in {"declared", "documented"}:
            raise ValueError("State declared or documented evidence")
        item = {k: row[k] for k in (*required, "kind", "evidence_status")}
        item["independently_verified"] = False
        if kind != "quota_snapshot":
            currency = row.get("currency")
            if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
                raise ValueError("Currency must be a three-letter code")
            item["currency"] = currency
        if kind in {"payment", "provider_charge", "subscription_plan"}:
            item["amount"] = str(money(row.get("amount")))
        if kind == "payment":
            item["paid_at"] = instant(row.get("paid_at")).isoformat()
            item["refund"] = row.get("refund") is True
        else:
            a, b = instant(row.get("period_start")), instant(row.get("period_end_exclusive"))
            if b <= a:
                raise ValueError("Evidence period is empty")
            item.update(period_start=a.isoformat(), period_end_exclusive=b.isoformat())
        link = row.get("charge_link")
        if link is not None:
            if not isinstance(link, str) or not re.fullmatch(r"E\d+", link):
                raise ValueError("Charge links use neutral E aliases")
            item["charge_link"] = link
        if kind == "payment_coverage":
            item["complete"] = row.get("complete") is True
            item["confirmed_zero"] = row.get("confirmed_zero") is True
        if kind == "quota_snapshot":
            item["as_of"] = instant(row.get("as_of")).isoformat()
            used = money(row.get("used_percent"))
            if used > 100:
                raise ValueError("Quota percentage exceeds 100")
            item["used_percent"] = str(used)
        output.append(item)
    return output


def summarize(records, start, end_exclusive):
    records = normalize(records)
    payments, charges, plans, quotas, unmatched, candidates = [], [], [], [], [], []
    seen = {}
    excluded = set()
    for row in records:
        # Identical selected facts are candidates; never silently count both.
        key = tuple((k, v) for k, v in sorted(row.items()) if k not in {"record_id", "source_alias"})
        if key in seen:
            excluded.update((seen[key], row["record_id"]))
            candidates.append([seen[key], row["record_id"]])
        else:
            seen[key] = row["record_id"]
    for row in records:
        if row["record_id"] in excluded:
            continue
        if row["kind"] == "payment":
            if start <= instant(row["paid_at"]) < end_exclusive:
                if row["evidence_status"] == "documented":
                    payments.append(row)
                else:
                    unmatched.append(row["record_id"])
            continue
        if instant(row["period_start"]) >= end_exclusive or instant(row["period_end_exclusive"]) <= start:
            continue
        if row["kind"] == "subscription_plan":
            plans.append(row)
        elif row["kind"] == "quota_snapshot":
            quotas.append(row)
        elif row["kind"] == "provider_charge":
            # Cross-window totals cannot be split without a declared allocation.
            if row["evidence_status"] == "documented" and start <= instant(row["period_start"]) and instant(row["period_end_exclusive"]) <= end_exclusive:
                charges.append(row)
            else:
                unmatched.append(row["record_id"])
    payment_totals, conflicts = [], []
    currencies = {r["currency"] for r in payments}
    coverage = [r for r in records if r["kind"] == "payment_coverage" and r["record_id"] not in excluded
                and r["evidence_status"] == "documented" and r["complete"]
                and instant(r["period_start"]) <= start and instant(r["period_end_exclusive"]) >= end_exclusive]
    currencies.update(r["currency"] for r in coverage)
    for currency in sorted(currencies):
        rows = [r for r in payments if r["currency"] == currency]
        total = sum((money(r["amount"]) * (-1 if r["refund"] else 1) for r in rows), Decimal(0))
        zero_scopes = sorted({r["scope_alias"] for r in coverage if r["currency"] == currency and r["confirmed_zero"]})
        for scope in list(zero_scopes):
            contradictory = [r["record_id"] for r in rows if r["scope_alias"] == scope and money(r["amount"]) > 0]
            if contradictory:
                zero_scopes.remove(scope)
                conflicts.append({"scope_alias": scope, "currency": currency, "payment_records": contradictory,
                                  "reason": "zero coverage conflicts with selected payments"})
        # Coverage claims are scope-bound, never a claim of all accounts found.
        observed_payments = any(money(r["amount"]) > 0 for r in rows)
        payment_totals.append({"currency": currency, "known_amount": str(total) if observed_payments else None,
                               "status": "documented_partial" if observed_payments else "unknown",
                               "explicit_zero_scopes": zero_scopes,
                               "zero_scope_amount": "0" if zero_scopes else None,
                               "global_completeness": "unknown"})
    charge_totals = [{"currency": currency, "known_amount": str(sum((money(r["amount"]) for r in charges if r["currency"] == currency), Decimal(0))),
                      "status": "documented_partial", "paid_status": "unconfirmed"}
                     for currency in sorted({r["currency"] for r in charges})]
    return {"schema_version": "tunemeter-billing/1.0.0", "payment_status": "partial" if payments else "unknown",
            "payments_by_currency": payment_totals, "charges_by_currency": charge_totals,
            "plans_covering_period": plans, "quota_snapshots": quotas,
            "unmatched": unmatched, "duplicate_candidates": candidates, "conflicting_evidence": conflicts,
            "reference_estimate": {"status": "not_computed", "amount": None}, "allocation": None,
            "records": records, "limits": ["documented is the organizer's evidence declaration, not independent verification",
            "payments and charges are separate views; never sum them", "coverage is limited to selected sources and scopes",
            "no token-to-subscription or quota conversion", "reference estimates and allocations are not cash payments"]}
