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


SEAT_TYPE_FOR_HK = {True: "Kalyana Karnataka", False: "Rest of Karnataka"}


def load_data(path=MASTER_CSV):
    df = pd.read_csv(
        path,
        dtype={"college_code": str, "college_name": str, "branch_name": str,
               "category": str, "branch_code": str, "source_file": str,
               "seat_type": str},
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
    exists, automatically shifting forward as more data is added - no code
    change needed.
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


def available_bases(df, is_hk):
    """Base categories that actually have data under the given HK-region
    status. Both quota systems happen to use the same 8 bases today, but
    this is still scoped by is_hk rather than hardcoded, so a future data
    update where one quota drops or gains a base is reflected automatically
    instead of silently offering an option with no real data behind it."""
    present = {
        decompose_category(c)[0]
        for c in df["category"].unique()
        if decompose_category(c) and decompose_category(c)[2] == is_hk
    }
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


def predict(df, rank, category_code, branch_name, is_hk):
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

    `is_hk` gates the comparison to the matching seat_type ("Kalyana
    Karnataka" vs "Rest of Karnataka") in addition to the category code -
    the two are perfectly correlated in the data (every H-suffixed code is
    Kalyana Karnataka and vice versa, verified), but filtering on both
    means a row that ever disagreed between the two would be excluded
    entirely rather than silently trusted on one signal.

    Returns (tiers, year) where tiers is a dict:
        {"Strong Chance": [...], "Possible": [...], "Unlikely": [...]}
    """
    year = reference_year(df)
    seat_type = SEAT_TYPE_FOR_HK[is_hk]
    subset = df[
        (df["year"] == year)
        & (df["category"] == category_code)
        & (df["branch_name"] == branch_name)
        & (df["seat_type"] == seat_type)
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

    _warn_on_large_tier_gaps(tiers, rank, category_code, branch_name)

    return tiers, year


def _warn_on_large_tier_gaps(tiers, rank, category_code, branch_name, ratio=5):
    """Console-only sanity check (never blocks or filters results): if
    Possible's or Unlikely's closest cutoff is more than `ratio` times
    farther from the student's rank than Strong Chance's average gap, print
    a warning. This doesn't mean the result is wrong - a college can
    legitimately have zero seats in an earlier round (a confirmed "--" in
    the source PDF, not missing data) and a real, much later cutoff in a
    subsequent round - but it's worth a human glancing at when a branch or
    category genuinely has no close options in a given tier."""
    strong = tiers.get("Strong Chance", [])
    if not strong:
        return
    baseline = sum(c["cutoff_rank"] - rank for c in strong) / len(strong)
    if baseline <= 0:
        return
    for tier_name in ("Possible", "Unlikely"):
        results = tiers.get(tier_name, [])
        if not results:
            continue
        gap = results[0]["cutoff_rank"] - rank
        if gap > ratio * baseline:
            print(
                f"[SANITY CHECK] rank={rank} category={category_code} "
                f"branch={branch_name!r}: {tier_name}'s closest cutoff is "
                f"{gap:,.0f} away from the student's rank, "
                f"{gap / baseline:.1f}x the Strong Chance average gap "
                f"({baseline:,.0f}). Likely means this college had no seats "
                f"in the earlier round (a real '--' in the source data), "
                f"not a selection bug - but worth a look if it seems off."
            )
