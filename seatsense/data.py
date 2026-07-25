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

RESULTS_PER_TIER = 2  # fixed 2+2+2 = 6 colleges total, per the round-based design
TIER_ROUNDS = [("Strong Chance", 1), ("Possible", 2), ("Unlikely", 3)]


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


def reference_year(df):
    """The most recent year that has Round 1, 2, AND 3 data.

    The Strong/Possible/Unlikely tiers compare a student's rank against
    Round 1, Round 2 and Round 3 cutoffs for the *same* college and the
    *same* year - mixing rounds from different years would mean comparing
    against cutoffs shaped by a different candidate pool each time, which
    is exactly the kind of fabricated comparison we don't want to show.
    So this picks the newest year where a full 1/2/3 progression actually
    exists. Right now that's 2024 (2025 only has Round 1 uploaded so far);
    once 2025's Round 2 and 3 files are added and update_data.py is rerun,
    this automatically shifts to 2025 - no code change needed.
    """
    complete_years = [
        year for year, group in df.groupby("year")
        if {1, 2, 3}.issubset(set(group["round"].unique()))
    ]
    if not complete_years:
        return int(df["year"].max())
    return int(max(complete_years))


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
    """Branch names as they appear in Round 1 of the reference year (the
    same year predict() compares against). This keeps the dropdown limited
    to branches that actually have a chance of having Round 2/3 data too,
    rather than offering branch names that only exist in the newest year's
    Round 1 file and can never match anything in Round 2/3."""
    year = reference_year(df)
    subset = df[(df["year"] == year) & (df["round"] == 1)]
    return sorted(subset["branch_name"].dropna().unique().tolist())


def predict(df, rank, category_code, branch_name):
    """Compare `rank` against Round 1, 2 and 3 cutoffs (all from the same
    reference year) for every college offering `branch_name` under
    `category_code`. Each college is placed in the single best tier it
    qualifies for:
      - Strong Chance: rank clears the Round 1 cutoff (realistically
        allotted in Round 1 itself)
      - Possible: doesn't clear Round 1, but clears Round 2
      - Unlikely: doesn't clear Round 1 or 2, but clears Round 3
    A college missing a given round's data is simply skipped for that
    round's check - never guessed. Within each tier, the closest match to
    the student's rank is shown first, capped at RESULTS_PER_TIER (2).

    Returns (tiers, year) where tiers is a dict:
        {"Strong Chance": [...], "Possible": [...], "Unlikely": [...]}
    """
    year = reference_year(df)
    subset = df[
        (df["year"] == year)
        & (df["category"] == category_code)
        & (df["branch_name"] == branch_name)
    ]
    subset = subset.drop_duplicates(subset=["college_code", "round"])

    colleges = {}
    for _, row in subset.iterrows():
        code = row["college_code"]
        entry = colleges.setdefault(code, {
            "college_code": code,
            "college_name": row["college_name"],
            "branch_name": row["branch_name"],
            "rounds": {},
        })
        entry["rounds"][int(row["round"])] = float(row["cutoff_rank"])

    tiers = {name: [] for name, _ in TIER_ROUNDS}
    for info in colleges.values():
        rounds = info["rounds"]
        for tier_name, round_n in TIER_ROUNDS:
            cutoff = rounds.get(round_n)
            if cutoff is None:
                continue  # this college has no data for this round - skip, don't guess
            if rank <= cutoff:
                tiers[tier_name].append({
                    "college_code": info["college_code"],
                    "college_name": info["college_name"],
                    "branch_name": info["branch_name"],
                    "tier": tier_name,
                    "round": round_n,
                    "year": year,
                    "cutoff_rank": cutoff,
                })
                break  # only counts toward the earliest (best) tier it clears

    for tier_name in tiers:
        tiers[tier_name].sort(key=lambda c: abs(rank - c["cutoff_rank"]))
        tiers[tier_name] = tiers[tier_name][:RESULTS_PER_TIER]

    return tiers, year
