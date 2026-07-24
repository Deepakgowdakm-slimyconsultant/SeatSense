"""
SeatSense data layer.

Everything here reads data/processed/master_cutoffs.csv as the single
source of truth. Nothing is hardcoded from a specific year's file list -
category codes and branch names are both derived from whatever rows are
actually in the CSV, so adding more source PDFs (via update_data.py) and
rerunning the extractor is all that's needed to pick up more data; the
app and this module don't change.

KCET category codes decompose cleanly into three independent parts, which
is what lets the UI ask three simple questions (category / sub-category /
HK-region) instead of a single cryptic code:

    <BASE><SUBCAT><REGION>

    BASE   : 1, 2A, 2B, 3A, 3B, GM, SC, ST
    SUBCAT : "" or "G" (General), "K" (Kannada Medium), "R" (Rural)
             - GM/SC/ST use a bare base for "General" (e.g. "GM")
             - 1/2A/2B/3A/3B require an explicit "G" for "General"
               (e.g. "1G") because the bare base never appears in the data
    REGION : "" (Rest of Karnataka) or "H" (Hyderabad-Karnataka / 371(j))

e.g. "2AKH" = base 2A + Kannada Medium + Hyderabad-Karnataka.
"""

import re
from functools import lru_cache

import pandas as pd

MASTER_CSV = "data/processed/master_cutoffs.csv"

CATEGORY_RE = re.compile(r"^(1|2A|2B|3A|3B|GM|SC|ST)(G|K|R)?(H)?$")

BASE_LABELS = [
    ("GM", "GM (General Merit)"),
    ("1", "Category 1"),
    ("2A", "Category 2A"),
    ("2B", "Category 2B"),
    ("3A", "Category 3A"),
    ("3B", "Category 3B"),
    ("SC", "SC (Scheduled Caste)"),
    ("ST", "ST (Scheduled Tribe)"),
]

SUBCAT_LABELS = [
    ("", "General (no special reservation)"),
    ("R", "Rural"),
    ("K", "Kannada Medium"),
]

STRONG_BUFFER = 0.10  # rank must be at least 10% better (lower) than cutoff
POSSIBLE_BUFFER = 0.10  # rank within 10% above cutoff still counts as "Possible"


def load_data(path=MASTER_CSV):
    df = pd.read_csv(
        path,
        dtype={"college_code": str, "college_name": str, "branch_name": str,
               "category": str, "branch_code": str, "source_file": str},
    )
    df["year"] = df["year"].astype(int)
    df["round"] = df["round"].astype(int)
    df["cutoff_rank"] = df["cutoff_rank"].astype(float)
    return df


def latest_year_round(df):
    """The single most recent (year, round) present anywhere in the data.
    Predictions are always made against this snapshot, so every college is
    compared on the same, most up-to-date footing."""
    top = df[["year", "round"]].drop_duplicates().sort_values(["year", "round"]).iloc[-1]
    return int(top["year"]), int(top["round"])


def decompose_category(code):
    """'2AKH' -> base='2A', subcat='K', is_hk=True. Returns None if the
    code doesn't match the expected KCET pattern."""
    m = CATEGORY_RE.match(code)
    if not m:
        return None
    base, subcat, region = m.groups()
    subcat_norm = "" if subcat in (None, "G") else subcat
    return base, subcat_norm, region == "H"


def compose_category(df, base, subcat, is_hk):
    """Look up the actual category code for (base, subcat, is_hk) against
    whatever codes really exist in the data, rather than guessing a string.
    Returns None if that combination doesn't exist."""
    for code in df["category"].unique():
        parsed = decompose_category(code)
        if parsed == (base, subcat, is_hk):
            return code
    return None


def available_bases(df):
    present = {decompose_category(c)[0] for c in df["category"].unique() if decompose_category(c)}
    return [(code, label) for code, label in BASE_LABELS if code in present]


def available_subcats(df, base, is_hk):
    present = set()
    for c in df["category"].unique():
        parsed = decompose_category(c)
        if parsed and parsed[0] == base and parsed[2] == is_hk:
            present.add(parsed[1])
    return [(code, label) for code, label in SUBCAT_LABELS if code in present]


def branch_options(df):
    """Branch names as they appear in the latest round only - selecting an
    older-only branch name would always return zero results, since
    predictions compare against the latest round exclusively."""
    year, round_ = latest_year_round(df)
    latest = df[(df["year"] == year) & (df["round"] == round_)]
    return sorted(latest["branch_name"].dropna().unique().tolist())


def classify_tier(rank, cutoff_rank):
    if rank <= cutoff_rank * (1 - STRONG_BUFFER):
        return "Strong Chance"
    if rank <= cutoff_rank * (1 + POSSIBLE_BUFFER):
        return "Possible"
    return "Unlikely"


TIER_ORDER = {"Strong Chance": 0, "Possible": 1, "Unlikely": 2}


def predict(df, rank, category_code, branch_name, top_n):
    """Compare `rank` against the latest round's cutoff for `category_code`
    + `branch_name`, across every college that offers it. Returns
    (results, year, round) where results is a list of dicts sorted best
    (Strong Chance, toughest cutoff first) to worst, truncated to top_n."""
    year, round_ = latest_year_round(df)
    subset = df[
        (df["year"] == year)
        & (df["round"] == round_)
        & (df["category"] == category_code)
        & (df["branch_name"] == branch_name)
    ]
    subset = subset.drop_duplicates(subset=["college_code"])

    results = []
    for _, row in subset.iterrows():
        cutoff = row["cutoff_rank"]
        tier = classify_tier(rank, cutoff)
        results.append({
            "college_code": row["college_code"],
            "college_name": row["college_name"],
            "branch_name": row["branch_name"],
            "cutoff_rank": cutoff,
            "tier": tier,
        })

    results.sort(key=lambda r: (TIER_ORDER[r["tier"]], r["cutoff_rank"]))
    return results[:top_n], year, round_
