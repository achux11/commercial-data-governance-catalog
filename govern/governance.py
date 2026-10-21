"""Data quality rules, profiling, data catalog, lineage, governed metrics and
AI-readiness scoring on top of a SQLite database."""
from collections import defaultdict
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
CUTOFF = "2025-12-31"
CATEGORIES = ("Surgical", "Vision Care")


def read_yaml(name):
    return yaml.safe_load((ROOT / "config" / name).read_text())


def run_sql_file(con, name="transform.sql"):
    con.executescript((ROOT / "sql" / name).read_text())


def q1(con, sql):
    return con.execute(sql).fetchone()[0]


# ---------- data quality rules ------------------------------------------------
def rules():
    """(id, table, dimension, description, failing-rows SQL). Same checks on raw and mart."""
    cats = ", ".join(f"'{c}'" for c in CATEGORIES)
    out = []
    for layer, acc, terr_join in (("raw", "raw_accounts", "raw_accounts"), ("mart", "dim_account", "dim_account")):
        out += [
            (f"{layer}-ACC-1", acc, "Completeness", "Account has a sales territory",
             f"SELECT COUNT(*) FROM {acc} WHERE territory_id IS NULL"),
            (f"{layer}-ACC-2", acc, "Uniqueness", "No duplicate accounts (same name and postal code)" if layer == "raw"
             else "Account ID is unique",
             "SELECT COUNT(*) - COUNT(DISTINCT account_name || '|' || postal_code) FROM raw_accounts" if layer == "raw"
             else "SELECT COUNT(*) - COUNT(DISTINCT account_id) FROM dim_account"),
            (f"{layer}-ACC-3", acc, "Validity", "Country code matches the territory's country",
             f"SELECT COUNT(*) FROM {acc} a JOIN raw_territories t ON t.territory_id = a.territory_id "
             f"WHERE a.country_code <> t.country_code"),
        ]
    for layer, o, accs, prods in (("raw", "raw_orders", "raw_accounts", "raw_products"),
                                  ("mart", "fct_orders", "dim_account", "dim_product")):
        out += [
            (f"{layer}-ORD-1", o, "Integrity", "Order points to an existing account",
             f"SELECT COUNT(*) FROM {o} WHERE account_id NOT IN (SELECT account_id FROM {accs})"),
            (f"{layer}-ORD-2", o, "Integrity", "Order SKU exists in the product master",
             f"SELECT COUNT(*) FROM {o} WHERE sku NOT IN (SELECT sku FROM {prods})"),
            (f"{layer}-ORD-3", o, "Validity", "Quantity is positive",
             f"SELECT COUNT(*) FROM {o} WHERE quantity <= 0"),
            (f"{layer}-ORD-4", o, "Timeliness", "Order date is not in the future",
             f"SELECT COUNT(*) FROM {o} WHERE order_date > '{CUTOFF}'"),
        ]
    out += [
        ("raw-PRD-1", "raw_products", "Consistency", "Category uses the governed list",
         f"SELECT COUNT(*) FROM raw_products WHERE category NOT IN ({cats})"),
        ("mart-PRD-1", "dim_product", "Consistency", "Category uses the governed list",
         f"SELECT COUNT(*) FROM dim_product WHERE category NOT IN ({cats})"),
        ("raw-REP-1", "raw_sales_reps", "Completeness", "Rep has a work email",
         "SELECT COUNT(*) FROM raw_sales_reps WHERE rep_email IS NULL"),
        ("raw-TER-1", "raw_territories", "Uniqueness", "Territory ID is unique",
         "SELECT COUNT(*) - COUNT(DISTINCT territory_id) FROM raw_territories"),
        ("mart-REC-1", "fct_orders", "Reconciliation",
         "Every raw order line is either certified or in the exceptions queue",
         "SELECT ABS((SELECT COUNT(*) FROM raw_orders) - (SELECT COUNT(*) FROM fct_orders)"
         " - (SELECT COUNT(*) FROM exceptions WHERE source = 'orders'))"),
    ]
    return out


def run_rules(con):
    rows = []
    for rid, table, dim, desc, sql in rules():
        n = q1(con, f"SELECT COUNT(*) FROM {table}")
        fail = q1(con, sql)
        rows.append({"rule_id": rid, "layer": rid.split("-")[0], "table": table, "dimension": dim,
                     "description": desc, "rows": n, "failing_rows": fail,
                     "pass_rate": 1 - fail / n if n else 1.0, "status": "PASS" if fail == 0 else "FAIL"})
    return pd.DataFrame(rows)


# ---------- profiling + catalog ---------------------------------------------
def tables(con, prefixes=("raw_", "dim_", "fct_")):
    names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    return [n for n in names if n.startswith(prefixes)]


def profile(con, table):
    cols = con.execute(f"PRAGMA table_info({table})").fetchall()
    n = q1(con, f"SELECT COUNT(*) FROM {table}")
    out = []
    for _, col, ctype, *_ in cols:
        nulls, distinct, lo, hi = con.execute(
            f"SELECT SUM({col} IS NULL), COUNT(DISTINCT {col}), MIN({col}), MAX({col}) FROM {table}").fetchone()
        out.append({"table": table, "column": col, "data_type": ctype or "TEXT", "rows": n,
                    "null_pct": (nulls or 0) / n if n else 0, "distinct": distinct,
                    "min": lo, "max": hi})
    return pd.DataFrame(out)


def build_catalog(con):
    meta = read_yaml("catalog.yaml")
    prof = pd.concat([profile(con, t) for t in tables(con)], ignore_index=True)
    rows = []
    for r in prof.itertuples(index=False):
        tmeta = meta.get(r.table, {})
        cmeta = (tmeta.get("columns") or {}).get(r.column, {})
        rows.append({**r._asdict(),
                     "layer": "raw" if r.table.startswith("raw_") else "mart",
                     "owner": tmeta.get("owner"), "steward": tmeta.get("steward"),
                     "source": tmeta.get("source"),
                     "is_primary_key": tmeta.get("primary_key") == r.column,
                     "definition": cmeta.get("definition"), "sensitivity": cmeta.get("sensitivity")})
    cat = pd.DataFrame(rows)
    cat["documented"] = cat.definition.notna() & cat.owner.notna()
    cat["classified"] = cat.sensitivity.notna()
    return cat


# ---------- lineage ----------------------------------------------------------
def lineage():
    cfg = read_yaml("lineage.yaml")
    return cfg["sources"], [tuple(e) for e in cfg["edges"]]


def upstream_sources(node, edges, sources):
    parents = defaultdict(list)
    for a, b in edges:
        parents[b].append(a)
    seen, stack, found = set(), [node], set()
    while stack:
        n = stack.pop()
        if n in sources:
            found.add(n)
        for p in parents.get(n, []):
            if p not in seen:
                seen.add(p)
                stack.append(p)
    return found


def lineage_mermaid(edges):
    lines = ["flowchart LR"]
    ident = lambda s: s.replace(":", "_")
    for a, b in edges:
        lines.append(f"  {ident(a)}[{a}] --> {ident(b)}[{b}]")
    return "\n".join(lines)


# ---------- governed metrics -------------------------------------------------
def compute_metrics(con):
    rows = []
    for m in read_yaml("metrics.yaml"):
        rows.append({**{k: m[k] for k in ("name", "label", "definition", "owner", "grain")},
                     "value": q1(con, m["sql"]), "sql": m["sql"]})
    return pd.DataFrame(rows)


# ---------- AI readiness -----------------------------------------------------
def ai_readiness(con, cat, rule_res):
    sources, edges = lineage()
    out = []
    for t, g in cat.groupby("table"):
        pk = g[g.is_primary_key]
        uniq = (pk.distinct.iloc[0] / pk.rows.iloc[0]) if len(pk) and pk.rows.iloc[0] else 0.0
        rr = rule_res[rule_res.table == t]
        checks = {
            "completeness": 1 - g.null_pct.mean(),
            "validity": rr.pass_rate.mean() if len(rr) else 0.0,
            "uniqueness": uniq,
            "documentation": g.documented.mean(),
            "classification": g.classified.mean(),
            "lineage": 1.0 if upstream_sources(t, edges, sources) else 0.0,
        }
        gates = (len(rr) > 0 and (rr.failing_rows == 0).all() and checks["documentation"] == 1
                 and checks["classification"] == 1 and checks["uniqueness"] == 1 and checks["lineage"] == 1)
        score = sum(checks.values()) / len(checks)
        tier = "AI-ready (certified)" if gates else ("Usable with caveats" if score >= 0.90 else "Not ready")
        out.append({"table": t, "layer": g.layer.iloc[0], **checks, "score": score,
                    "rules_failed": int((rr.failing_rows > 0).sum()), "tier": tier})
    return pd.DataFrame(out).sort_values(["layer", "table"])
