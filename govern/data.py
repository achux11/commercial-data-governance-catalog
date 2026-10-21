"""Simulated CRM-style commercial sales data (accounts, sales reps, territories,
products, orders) with realistic data-quality problems planted on purpose.

Generic medical-device company; not real company data. Every planted issue is
recorded in PLANTED so the validation rules can be checked against known truth.
"""
import sqlite3

import numpy as np
import pandas as pd

SEED = 11
N_ACCOUNTS = 2_000
N_ORDERS = 60_000
REGIONS = {"US": ["US-East", "US-Central", "US-West"], "CA": ["Canada"],
           "LATAM": ["Brazil", "Mexico", "Andean"]}
COUNTRIES = {"US-East": "US", "US-Central": "US", "US-West": "US", "Canada": "CA",
             "Brazil": "BR", "Mexico": "MX", "Andean": "CO"}
ACCOUNT_TYPES = ["Hospital", "Ambulatory Surgery Center", "Private Practice", "Optical Retailer"]
PRODUCTS = [  # sku, name, category, list price (USD)
    ("SKU-1001", "Monofocal Lens", "Surgical", 220.0),
    ("SKU-1002", "Toric Lens", "Surgical", 480.0),
    ("SKU-1003", "Multifocal Lens", "Surgical", 950.0),
    ("SKU-2001", "Daily Contact Lens 90pk", "Vision Care", 38.0),
    ("SKU-2002", "Monthly Contact Lens 6pk", "Vision Care", 29.0),
    ("SKU-3001", "Lubricant Eye Drops", "Vision Care", 9.5),
    ("SKU-4001", "Surgical Pack", "Surgical", 310.0),
    ("SKU-4002", "Viscoelastic", "Surgical", 65.0),
]

# planted problems (counts)
PLANTED = {
    "duplicate_accounts": 40,          # same name + postal code, new id
    "accounts_missing_territory": 25,
    "invalid_country_code": 15,        # country not matching territory
    "orphan_orders": 120,              # account_id not in accounts
    "negative_quantity": 80,
    "future_order_date": 30,
    "unknown_sku": 50,
    "inconsistent_category": 1,        # "surgical" vs "Surgical" in products
    "missing_rep_email": 6,
}


def build(seed=SEED):
    rng = np.random.default_rng(seed)

    pairs = [(r, t) for r, ts in REGIONS.items() for t in ts]
    territories = pd.DataFrame(
        [(f"T{i + 1:02d}", t, r, COUNTRIES[t]) for i, (r, t) in enumerate(pairs)],
        columns=["territory_id", "territory_name", "region", "country_code"])

    reps = []
    for i in range(42):
        t = territories.sample(1, random_state=i).iloc[0]
        reps.append((f"R{i + 1:03d}", f"Rep {i + 1:03d}", f"rep{i + 1:03d}@example.com", t.territory_id))
    reps = pd.DataFrame(reps, columns=["rep_id", "rep_name", "rep_email", "territory_id"])
    reps.loc[rng.choice(len(reps), PLANTED["missing_rep_email"], replace=False), "rep_email"] = None

    t_idx = rng.integers(0, len(territories), N_ACCOUNTS)
    acc = pd.DataFrame({
        "account_id": [f"A{i + 1:05d}" for i in range(N_ACCOUNTS)],
        "account_name": [f"Eye Care Center {i + 1:05d}" for i in range(N_ACCOUNTS)],
        "account_type": rng.choice(ACCOUNT_TYPES, N_ACCOUNTS, p=[0.15, 0.25, 0.45, 0.15]),
        "territory_id": territories.territory_id.to_numpy()[t_idx],
        "country_code": territories.country_code.to_numpy()[t_idx],
        "postal_code": [f"{rng.integers(10000, 99999)}" for _ in range(N_ACCOUNTS)],
        "created_date": pd.to_datetime("2020-01-01") + pd.to_timedelta(rng.integers(0, 1800, N_ACCOUNTS), "D"),
    })
    rep_by_t = reps.groupby("territory_id").rep_id.first()
    acc["owner_rep_id"] = acc.territory_id.map(rep_by_t)
    acc["owner_rep_id"] = acc.owner_rep_id.fillna(reps.rep_id.iloc[0])

    i = rng.choice(N_ACCOUNTS, PLANTED["accounts_missing_territory"], replace=False)
    acc.loc[i, "territory_id"] = None
    rest = np.setdiff1d(np.arange(N_ACCOUNTS), i)
    j = rng.choice(rest, PLANTED["invalid_country_code"], replace=False)
    acc.loc[j, "country_code"] = acc.loc[j, "country_code"].map(
        lambda c: "XX" if c == "US" else "US")
    dup_src = rng.choice(rest, PLANTED["duplicate_accounts"], replace=False)
    dups = acc.loc[dup_src].copy()
    dups["account_id"] = [f"A{N_ACCOUNTS + k + 1:05d}" for k in range(len(dups))]
    acc = pd.concat([acc, dups], ignore_index=True)

    prods = pd.DataFrame(PRODUCTS, columns=["sku", "product_name", "category", "list_price_usd"])
    prods.loc[prods.sku == "SKU-4002", "category"] = "surgical"          # inconsistent label

    o_acc = rng.choice(acc.account_id.iloc[:N_ACCOUNTS], N_ORDERS)
    sku_p = np.array([0.18, 0.10, 0.05, 0.22, 0.18, 0.15, 0.06, 0.06])
    o = pd.DataFrame({
        "order_id": [f"O{i + 1:06d}" for i in range(N_ORDERS)],
        "account_id": o_acc,
        "order_date": pd.to_datetime("2024-01-01") + pd.to_timedelta(rng.integers(0, 731, N_ORDERS), "D"),
        "sku": rng.choice(prods.sku, N_ORDERS, p=sku_p),
        "quantity": rng.integers(1, 40, N_ORDERS),
    })
    price = o.sku.map(prods.set_index("sku").list_price_usd)
    o["net_amount_usd"] = (o.quantity * price * rng.uniform(0.85, 1.0, N_ORDERS)).round(2)
    o["rep_id"] = o.account_id.map(acc.drop_duplicates("account_id").set_index("account_id").owner_rep_id)

    k = rng.permutation(N_ORDERS)
    cut = np.cumsum([0, PLANTED["orphan_orders"], PLANTED["negative_quantity"],
                     PLANTED["future_order_date"], PLANTED["unknown_sku"]])
    orph, neg, fut, unk = (k[cut[i]:cut[i + 1]] for i in range(4))
    o.loc[orph, "account_id"] = [f"A9{x:04d}" for x in range(len(orph))]
    o.loc[neg, "quantity"] *= -1
    o.loc[neg, "net_amount_usd"] *= -1
    o.loc[fut, "order_date"] = pd.to_datetime("2027-03-01")
    o.loc[unk, "sku"] = "SKU-9999"

    acc["created_date"] = acc.created_date.dt.strftime("%Y-%m-%d")
    o["order_date"] = o.order_date.dt.strftime("%Y-%m-%d")
    return {"raw_territories": territories, "raw_sales_reps": reps, "raw_accounts": acc,
            "raw_products": prods, "raw_orders": o}


def load_sqlite(tables, path=":memory:"):
    con = sqlite3.connect(path)
    for name, df in tables.items():
        df.to_sql(name, con, index=False, if_exists="replace")
    return con
