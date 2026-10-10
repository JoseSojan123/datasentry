"""Dataset version and schema comparison, including rename-candidate scoring.

Potential renames are *never* applied automatically. A removed column and an added column of the
same semantic type are scored for similarity; candidates above ``rename_min_confidence`` are
returned for user confirmation. Confirmed renames (passed in ``confirmed_renames``) are then
treated as renames instead of a removal plus an addition.

Rename confidence = 0.35 * name similarity (difflib ratio on normalised names)
                  + 0.50 * profile similarity (distribution/category overlap and missingness)
                  + 0.15 * position proximity
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Any

DEFAULT_POLICY: dict[str, str] = {
    "column_added": "info",
    "column_removed": "critical",
    "column_renamed": "warning",
    "rename_candidate": "warning",
    "type_changed": "critical",
    "null_pct_increase": "warning",
    "null_pct_increase_large": "critical",
    "category_added": "warning",
    "category_removed": "info",
    "row_count_change": "warning",
    "duplicate_increase": "warning",
    "distribution_change": "warning",
}
SEVERITIES = ("info", "warning", "critical")


@dataclass
class DiffConfig:
    null_pct_warning_pp: float = 5.0
    null_pct_critical_pp: float = 20.0
    row_count_change_ratio: float = 0.3
    duplicate_increase_pp: float = 1.0
    rename_min_confidence: float = 0.5
    policy: dict[str, str] = field(default_factory=dict)

    def severity(self, kind: str) -> str:
        return self.policy.get(kind) or DEFAULT_POLICY.get(kind, "warning")


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _profile_similarity(a: dict[str, Any] | None, b: dict[str, Any] | None) -> float:
    if not a or not b:
        return 0.0
    miss = 1 - min(1.0, abs(a.get("missing_pct", 0) - b.get("missing_pct", 0)) / 100)
    if a.get("mean") is not None and b.get("mean") is not None:
        scale = max(abs(a.get("std") or 0), abs(b.get("std") or 0), 1e-9)
        mean_sim = max(0.0, 1 - abs(a["mean"] - b["mean"]) / (3 * scale))
        std_sim = 1 - abs((a.get("std") or 0) - (b.get("std") or 0)) / scale if scale > 1e-9 else 1.0
        return 0.5 * mean_sim + 0.3 * max(0.0, std_sim) + 0.2 * miss
    fa, fb = a.get("frequencies"), b.get("frequencies")
    if fa and fb:
        ta, tb = sum(fa.values()) or 1, sum(fb.values()) or 1
        keys = set(fa) | set(fb)
        overlap = sum(min(fa.get(k, 0) / ta, fb.get(k, 0) / tb) for k in keys)
        return 0.8 * overlap + 0.2 * miss
    if a.get("mean_length") is not None and b.get("mean_length") is not None:
        la, lb = a["mean_length"], b["mean_length"]
        return 0.6 * (1 - abs(la - lb) / max(la, lb, 1)) + 0.4 * miss
    return 0.3 * miss


def rename_candidates(
    removed: list[dict[str, Any]],
    added: list[dict[str, Any]],
    base_profile: dict[str, Any],
    target_profile: dict[str, Any],
    n_cols: int,
    min_conf: float,
) -> list[dict[str, Any]]:
    scored = []
    for r in removed:
        for a in added:
            if r["semantic_type"] != a["semantic_type"]:
                continue
            name_sim = difflib.SequenceMatcher(None, _norm(r["name"]), _norm(a["name"])).ratio()
            prof_sim = _profile_similarity(base_profile.get(r["name"]), target_profile.get(a["name"]))
            pos_sim = 1 - abs(r["position"] - a["position"]) / max(n_cols, 1)
            conf = round(0.35 * name_sim + 0.5 * prof_sim + 0.15 * pos_sim, 4)
            if conf >= min_conf:
                scored.append({
                    "from": r["name"], "to": a["name"], "confidence": conf,
                    "evidence": {"name_similarity": round(name_sim, 4), "profile_similarity": round(prof_sim, 4),
                                 "position_similarity": round(pos_sim, 4)},
                })
    scored.sort(key=lambda s: -s["confidence"])
    used_from: set[str] = set()
    used_to: set[str] = set()
    best = []
    for s in scored:
        if s["from"] in used_from or s["to"] in used_to:
            continue
        used_from.add(s["from"])
        used_to.add(s["to"])
        alternatives = [x for x in scored if x["from"] == s["from"] and x["to"] != s["to"]]
        s["ambiguous"] = bool(alternatives) and alternatives[0]["confidence"] >= s["confidence"] - 0.1
        best.append(s)
    return best


def compare_versions(
    base_schema: list[dict[str, Any]],
    target_schema: list[dict[str, Any]],
    base_profile: dict[str, Any],
    target_profile: dict[str, Any],
    config: DiffConfig | None = None,
    confirmed_renames: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return a list of typed changes with severities plus a summary."""
    cfg = config or DiffConfig()
    confirmed = dict(confirmed_renames or {})
    bcols = {c["name"]: c for c in base_schema}
    tcols = {c["name"]: c for c in target_schema}
    bprof = base_profile.get("columns", {})
    tprof = target_profile.get("columns", {})
    changes: list[dict[str, Any]] = []

    def add(kind: str, column: str | None, message: str, severity: str | None = None, **data: Any) -> None:
        changes.append({"kind": kind, "column": column, "severity": severity or cfg.severity(kind), "message": message, **data})

    confirmed = {f: t for f, t in confirmed.items() if f in bcols and f not in tcols and t in tcols and t not in bcols}
    removed = [c for n, c in bcols.items() if n not in tcols and n not in confirmed]
    added = [c for n, c in tcols.items() if n not in bcols and n not in confirmed.values()]
    candidates = rename_candidates(removed, added, bprof, tprof, max(len(bcols), len(tcols)), cfg.rename_min_confidence)
    for f, t in confirmed.items():
        add("column_renamed", f, f"Column '{f}' was renamed to '{t}' (confirmed by a user).", to=t)
    for c in removed:
        cand = next((x for x in candidates if x["from"] == c["name"]), None)
        hint = f" Possible rename to '{cand['to']}' (confidence {cand['confidence']:.0%}, needs confirmation)." if cand else ""
        add("column_removed", c["name"], f"Column '{c['name']}' ({c['semantic_type']}) was removed.{hint}")
    for c in added:
        add("column_added", c["name"], f"Column '{c['name']}' ({c['semantic_type']}) was added.")
    for cand in candidates:
        add("rename_candidate", cand["from"],
            f"'{cand['from']}' may have been renamed to '{cand['to']}' (confidence {cand['confidence']:.0%}"
            f"{', ambiguous' if cand['ambiguous'] else ''}). Confirm or reject this match.",
            to=cand["to"], confidence=cand["confidence"], evidence=cand["evidence"], ambiguous=cand["ambiguous"])

    pairs = [(n, n) for n in bcols if n in tcols] + list(confirmed.items())
    for bn, tn in pairs:
        b, t = bcols[bn], tcols[tn]
        if b["semantic_type"] != t["semantic_type"]:
            add("type_changed", tn, f"'{tn}' changed type from {b['semantic_type']} to {t['semantic_type']}.",
                before=b["semantic_type"], after=t["semantic_type"])
        bp, tp = bprof.get(bn, {}), tprof.get(tn, {})
        if bp and tp:
            delta = tp.get("missing_pct", 0) - bp.get("missing_pct", 0)
            if delta >= cfg.null_pct_critical_pp:
                add("null_pct_increase_large", tn, f"Nulls in '{tn}' rose from {bp['missing_pct']:.1f}% to {tp['missing_pct']:.1f}%.",
                    before=bp["missing_pct"], after=tp["missing_pct"])
            elif delta >= cfg.null_pct_warning_pp:
                add("null_pct_increase", tn, f"Nulls in '{tn}' rose from {bp['missing_pct']:.1f}% to {tp['missing_pct']:.1f}%.",
                    before=bp["missing_pct"], after=tp["missing_pct"])
            if b["semantic_type"] == t["semantic_type"] == "categorical" and bp.get("frequencies") is not None:
                bset, tset = set(bp.get("frequencies", {})), set(tp.get("frequencies", {}))
                new, gone = sorted(tset - bset), sorted(bset - tset)
                if new and not bp.get("frequencies_truncated"):
                    add("category_added", tn, f"New categories in '{tn}': {', '.join(new[:5])}{'…' if len(new) > 5 else ''}.",
                        values=new[:50])
                if gone and not tp.get("frequencies_truncated"):
                    add("category_removed", tn, f"Categories no longer present in '{tn}': {', '.join(gone[:5])}.",
                        values=gone[:50])

    bd, td = base_profile.get("dataset", {}), target_profile.get("dataset", {})
    if bd.get("row_count"):
        ratio = (td.get("row_count", 0) - bd["row_count"]) / bd["row_count"]
        if abs(ratio) >= cfg.row_count_change_ratio:
            add("row_count_change", None, f"Row count changed from {bd['row_count']:,} to {td.get('row_count', 0):,} ({ratio:+.0%}).",
                before=bd["row_count"], after=td.get("row_count"), relative_change=round(ratio, 4))
    if td.get("duplicate_row_pct", 0) - bd.get("duplicate_row_pct", 0) >= cfg.duplicate_increase_pp:
        add("duplicate_increase", None,
            f"Duplicate rows rose from {bd.get('duplicate_row_pct', 0):.2f}% to {td['duplicate_row_pct']:.2f}%.",
            before=bd.get("duplicate_row_pct"), after=td.get("duplicate_row_pct"))

    order = {"critical": 0, "warning": 1, "info": 2}
    changes.sort(key=lambda c: (order.get(c["severity"], 3), c["kind"]))
    counts = {s: sum(c["severity"] == s for c in changes) for s in SEVERITIES}
    overall = next((s for s in ("critical", "warning", "info") if counts[s]), "none")
    return {
        "summary": {
            "changes": len(changes),
            "by_severity": counts,
            "overall_severity": overall,
            "schema_changed": bool(removed or added or confirmed or any(c["kind"] == "type_changed" for c in changes)),
            "base_fingerprint": bd.get("schema_fingerprint"),
            "target_fingerprint": td.get("schema_fingerprint"),
        },
        "changes": changes,
        "rename_candidates": candidates,
        "policy": {**DEFAULT_POLICY, **cfg.policy},
    }
