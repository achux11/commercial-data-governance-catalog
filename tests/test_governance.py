import pandas as pd
import pytest

from govern.data import PLANTED, build, load_sqlite
from govern import governance as G


@pytest.fixture(scope="module")
def env():
    raw = build()
    con = load_sqlite(raw)
    G.run_sql_file(con)
    rules = G.run_rules(con).set_index("rule_id")
    cat = G.build_catalog(con)
    return raw, con, rules, cat


def test_rules_catch_every_planted_issue(env):
    _, _, r, _ = env
    expect = {"raw-ACC-1": PLANTED["accounts_missing_territory"], "raw-ACC-2": PLANTED["duplicate_accounts"],
              "raw-ORD-1": PLANTED["orphan_orders"], "raw-ORD-2": PLANTED["unknown_sku"],
              "raw-ORD-3": PLANTED["negative_quantity"], "raw-ORD-4": PLANTED["future_order_date"],
              "raw-PRD-1": PLANTED["inconsistent_category"], "raw-REP-1": PLANTED["missing_rep_email"]}
    for rid, n in expect.items():
        assert r.loc[rid, "failing_rows"] == n, rid
    # copies of bad accounts carry the bad country code too, so >= planted
    assert r.loc["raw-ACC-3", "failing_rows"] >= PLANTED["invalid_country_code"]


def test_mart_passes_every_rule_and_reconciles(env):
    _, _, r, _ = env
    mart = r[r.layer == "mart"]
    assert (mart.failing_rows == 0).all()
    assert "mart-REC-1" in mart.index


def test_catalog_mart_fully_documented_and_pii_tagged(env):
    _, _, _, cat = env
    mart = cat[cat.layer == "mart"]
    assert mart.documented.all() and mart.classified.all()
    pii = set(cat.loc[cat.sensitivity == "PII", "column"])
    assert {"rep_name", "rep_email"} <= pii


def test_net_sales_metric_matches_independent_pandas_calc(env):
    raw, con, _, _ = env
    o, a, p = raw["raw_orders"], raw["raw_accounts"], raw["raw_products"]
    a = a.assign(survivor=a.groupby(["account_name", "postal_code"]).account_id.transform("min"))
    ok_acc = set(a.loc[(a.account_id == a.survivor) & a.territory_id.notna(), "account_id"])
    o = o.merge(a[["account_id", "survivor"]], on="account_id")
    o = o[o.survivor.isin(ok_acc) & o.sku.isin(p.sku) & (o.quantity > 0) & (o.order_date <= "2025-12-31")]
    m = G.compute_metrics(con).set_index("name").value
    assert m["net_sales_usd"] == pytest.approx(o.net_amount_usd.sum())
    assert m["active_accounts"] == o.survivor.nunique()


def test_every_metric_traces_to_a_raw_source(env):
    sources, edges = G.lineage()
    for m in G.read_yaml("metrics.yaml"):
        assert "raw_orders" in G.upstream_sources(f"metric:{m['name']}", edges, sources)


def test_ai_readiness_certifies_mart_not_raw(env):
    _, con, r, cat = env
    ready = G.ai_readiness(con, cat, r.reset_index()).set_index("table")
    for t in ("dim_account", "dim_product", "fct_orders"):
        assert ready.loc[t, "tier"] == "AI-ready (certified)"
    for t in ("raw_accounts", "raw_orders"):
        assert ready.loc[t, "tier"] != "AI-ready (certified)"
