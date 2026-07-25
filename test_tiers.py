"""
Assertion-based tests for seatsense.data.predict(). Run with:
    python3 test_tiers.py
"""

from seatsense.data import (
    load_data,
    predict,
    ROUND_CLEARED,
    ROUND_FAILED,
    ROUND_NO_DATA,
    SEAT_TYPE_FOR_HK,
)

RANK = 5121
BRANCH = "ELECTRONICS AND COMMUNICATION ENGG"
CATEGORY = "2AH"
IS_HK = True

TIER_OWN_ROUND = {"Strong Chance": 1, "Possible": 2, "Unlikely": 3}
TIER_PRIOR_ROUND = {"Strong Chance": None, "Possible": 1, "Unlikely": 2}


def raw_pool(df, year, category, branch, seat_type):
    """Independently-computed ground truth: college_code -> {round: cutoff},
    built straight from the dataframe rather than reusing any of predict()'s
    internal grouping, so tests that compare against this aren't just
    checking predict() against itself."""
    subset = df[
        (df["year"] == year)
        & (df["category"] == category)
        & (df["branch_name"] == branch)
        & (df["seat_type"] == seat_type)
    ].drop_duplicates(subset=["college_code", "round"])
    pool = {}
    for _, row in subset.iterrows():
        pool.setdefault(row["college_code"], {})[int(row["round"])] = float(row["cutoff_rank"])
    return pool


def eligible_count(pool, rank, tier_name):
    """How many colleges in the raw pool genuinely qualify for tier_name,
    independent of the RESULTS_PER_TIER cap - used to check tiers aren't
    padded with ineligible colleges when fewer than 2 real matches exist."""
    count = 0
    for rounds in pool.values():
        r1, r2, r3 = rounds.get(1), rounds.get(2), rounds.get(3)
        r1_cleared = r1 is not None and rank <= r1
        r2_cleared = r2 is not None and rank <= r2
        r3_cleared = r3 is not None and rank <= r3
        if tier_name == "Strong Chance" and r1_cleared:
            count += 1
        elif tier_name == "Possible" and not r1_cleared and r2_cleared:
            count += 1
        elif tier_name == "Unlikely" and not r1_cleared and not r2_cleared and r3_cleared:
            count += 1
    return count


def tier_correctness(tiers, pool, rank):
    """R1: every shown college clears its OWN round for its tier, and fails
    its OWN prior round (FAILED or NO_DATA - never CLEARED).
    R2: no college_code appears in more than one tier.
    R3: each tier shows min(genuinely-eligible-count, RESULTS_PER_TIER) -
    never padded with ineligible colleges.
    Returns (r1_ok, r2_ok, r3_ok, detail)."""
    r1_ok = True
    r1_detail = []
    seen_codes = []

    for tier_name, results in tiers.items():
        own_round = TIER_OWN_ROUND[tier_name]
        prior = TIER_PRIOR_ROUND[tier_name]
        for c in results:
            code = c["college_code"]
            seen_codes.append(code)
            rounds = pool.get(code, {})
            own_cutoff = rounds.get(own_round)
            if own_cutoff is None or rank > own_cutoff:
                r1_ok = False
                r1_detail.append(f"{code} fails own-round check in {tier_name}")
            if prior is not None:
                prior_cutoff = rounds.get(prior)
                if prior_cutoff is not None and rank <= prior_cutoff:
                    r1_ok = False
                    r1_detail.append(f"{code} actually CLEARED prior round {prior} but shown in {tier_name}")

    r2_ok = len(seen_codes) == len(set(seen_codes))

    r3_ok = True
    r3_detail = []
    for tier_name, results in tiers.items():
        expected = min(eligible_count(pool, rank, tier_name), 2)
        actual = len(results)
        if actual != expected:
            r3_ok = False
            r3_detail.append(f"{tier_name}: expected {expected} shown, got {actual}")

    return r1_ok, r2_ok, r3_ok, "; ".join(r1_detail + r3_detail)


def log_within_college_ordering(pool, label):
    """R4 (soft check, log only): for colleges with data for 2+ rounds,
    note if R1 <= R2 <= R3 doesn't hold. Not a code bug if violated - a
    college's own cutoff can legitimately tighten then loosen across
    rounds depending on how many candidates accept/withdraw each round."""
    violations = []
    for code, rounds in pool.items():
        present = sorted(rounds.keys())
        values = [rounds[r] for r in present]
        if len(values) >= 2 and values != sorted(values):
            violations.append((code, dict(rounds)))
    if violations:
        print(f"[R4 LOG] {label}: {len(violations)} college(s) with non-monotonic own-round "
              f"cutoffs (data-quality note, not a failure): {violations[:3]}"
              + (" ..." if len(violations) > 3 else ""))


def run():
    df = load_data()
    failures = []

    def check(name, condition, detail=""):
        status = "PASS" if condition else "FAIL"
        print(f"[{status}] {name}" + (f" - {detail}" if detail and not condition else ""))
        if not condition:
            failures.append(name)

    # ------------------------------------------------------------------
    # T1 / T2: rank 5121, ECE, 2AH - every shown cutoff must be >= rank
    # ------------------------------------------------------------------
    tiers, year = predict(df, RANK, CATEGORY, BRANCH, IS_HK)

    check(
        "T1: every Strong Chance cutoff >= rank",
        all(c["cutoff_rank"] >= RANK for c in tiers["Strong Chance"]),
        detail=str([c["cutoff_rank"] for c in tiers["Strong Chance"]]),
    )
    check(
        "T2: every Possible cutoff >= rank",
        all(c["cutoff_rank"] >= RANK for c in tiers["Possible"]),
        detail=str([c["cutoff_rank"] for c in tiers["Possible"]]),
    )

    # ------------------------------------------------------------------
    # T3 (renamed from "monotonicity" to "tier correctness"): cross-tier
    # monotonicity (max(Strong)<=min(Possible)<=min(Unlikely)) is DELETED -
    # confirmed not a real property of this data (each tier's "2 closest"
    # colleges are independent colleges with independent round-to-round
    # cutoff trajectories). Replaced with R1-R3, which ARE guaranteed.
    # ------------------------------------------------------------------
    seat_type = SEAT_TYPE_FOR_HK[IS_HK]
    primary_pool = raw_pool(df, year, CATEGORY, BRANCH, seat_type)
    r1_ok, r2_ok, r3_ok, detail = tier_correctness(tiers, primary_pool, RANK)
    check("T3: R1 tier-own-round correctness for rank 5121 ECE", r1_ok, detail)
    check("T3: R2 no double-counting across tiers for rank 5121 ECE", r2_ok)
    check("T3: R3 tier population honesty (no padding) for rank 5121 ECE", r3_ok, detail)
    log_within_college_ordering(primary_pool, "rank=5121 ECE 2AH")

    # ------------------------------------------------------------------
    # T4 (fixed): Vidya Vikas (cutoff 103781) must not appear if a
    # genuinely CLOSER, Possible-ELIGIBLE college was missed. Eligible
    # means Round 1 = FAILED or NO_DATA (Strong Chance colleges are
    # correctly excluded - they aren't competing for the Possible slot;
    # the old version of this test wrongly compared against the whole
    # pool, including Strong Chance rows).
    # ------------------------------------------------------------------
    def possible_eligible_candidates(pool, rank):
        out = []
        for code, rounds in pool.items():
            r1 = rounds.get(1)
            r1_cleared = r1 is not None and rank <= r1
            r2 = rounds.get(2)
            if not r1_cleared and r2 is not None and rank <= r2:
                out.append((code, r2))
        return out

    eligible = possible_eligible_candidates(primary_pool, RANK)
    closer_missed = [
        (code, cutoff) for code, cutoff in eligible
        if code != "E077" and abs(cutoff - RANK) < abs(103781.0 - RANK)
    ]
    vv_shown = any(c["college_code"] == "E077" for c in tiers["Possible"])
    check(
        "T4: Vidya Vikas excluded if a closer Possible-eligible college was missed",
        not closer_missed or not vv_shown,
        detail=str(closer_missed),
    )
    check(
        "T4: Vidya Vikas is shown (it is the closest, or only, Possible-eligible candidate)",
        vv_shown,
        detail=str(eligible),
    )

    # ------------------------------------------------------------------
    # T5: R1-R3 tier correctness across 5 ranks x 3 categories (replaces
    # the old cross-tier-monotonicity sweep, which asserted a property
    # this data does not actually have - see T3 above).
    # ------------------------------------------------------------------
    print()
    test_categories = ["GM", "2AH", "SCG"]
    test_ranks = [1000, 5000, 20000, 60000, 150000]
    branches = df[(df["year"] == year) & (df["round"] == 1)]["branch_name"].dropna().unique().tolist()
    t5_branch = "COMPUTER SCIENCE AND ENGINEERING" if "COMPUTER SCIENCE AND ENGINEERING" in branches else branches[0]

    for cat in test_categories:
        is_hk_t5 = cat.endswith("H")
        seat_type_t5 = SEAT_TYPE_FOR_HK[is_hk_t5]
        pool_t5 = raw_pool(df, year, cat, t5_branch, seat_type_t5)
        for r in test_ranks:
            t, _ = predict(df, r, cat, t5_branch, is_hk_t5)
            ok1 = all(c["cutoff_rank"] >= r for c in t["Strong Chance"])
            ok2 = all(c["cutoff_rank"] >= r for c in t["Possible"])
            r1_ok, r2_ok, r3_ok, d = tier_correctness(t, pool_t5, r)
            check(
                f"T5: rank={r} category={cat} branch={t5_branch!r} (T1+T2+R1+R2+R3)",
                ok1 and ok2 and r1_ok and r2_ok and r3_ok,
                detail=d,
            )
        log_within_college_ordering(pool_t5, f"category={cat} branch={t5_branch!r}")

    # ------------------------------------------------------------------
    # T6: synthetic college, Round 1 = NO_DATA, Round 2 clears far above rank
    # ------------------------------------------------------------------
    print()
    from seatsense.data import _round_status

    synth_rank = 1000
    synth_rounds_no_data = {2: 50000.0}  # no key 1 at all
    r1_status, r1_cutoff = _round_status(synth_rounds_no_data, 1, synth_rank)
    r2_status, r2_cutoff = _round_status(synth_rounds_no_data, 2, synth_rank)
    tier = "Strong Chance" if r1_status == ROUND_CLEARED else ("Possible" if r2_status == ROUND_CLEARED else None)
    check("T6: synthetic NO_DATA college classified Possible (not Strong Chance, not dropped)", tier == "Possible")
    check("T6: synthetic NO_DATA college's round-1 status flagged as NO_DATA", r1_status == ROUND_NO_DATA)

    # ------------------------------------------------------------------
    # T7: synthetic college, Round 1 = FAILED (real cutoff, rank exceeds it),
    # Round 2 = CLEARED
    # ------------------------------------------------------------------
    synth_rounds_failed = {1: 500.0, 2: 50000.0}  # rank 1000 > 500 -> failed R1
    r1_status2, r1_cutoff2 = _round_status(synth_rounds_failed, 1, synth_rank)
    r2_status2, r2_cutoff2 = _round_status(synth_rounds_failed, 2, synth_rank)
    tier2 = "Strong Chance" if r1_status2 == ROUND_CLEARED else ("Possible" if r2_status2 == ROUND_CLEARED else None)
    check("T7: synthetic FAILED college classified Possible", tier2 == "Possible")
    check("T7: synthetic FAILED college's round-1 status flagged as FAILED (not NO_DATA)", r1_status2 == ROUND_FAILED)

    # ------------------------------------------------------------------
    # T8: exact Vidya Vikas case - round-1 status must be NO_DATA, not FAILED
    # ------------------------------------------------------------------
    print()
    vv_result = next((c for c in tiers["Possible"] if c["college_code"] == "E077"), None)
    check("T8: Vidya Vikas appears in Possible tier", vv_result is not None)
    if vv_result:
        check(
            "T8: Vidya Vikas prior_round_status is NO_DATA (E077 has no Round 1 row)",
            vv_result["prior_round_status"] == ROUND_NO_DATA,
            detail=str(vv_result["prior_round_status"]),
        )
        check("T8: Vidya Vikas prior_round is 1", vv_result["prior_round"] == 1)
        check("T8: Vidya Vikas prior_round_cutoff is None (no data, not a real cutoff)",
              vv_result["prior_round_cutoff"] is None)

    # ------------------------------------------------------------------
    # T9: R1-R3 tier correctness re-confirmed for the primary test case
    # (restates T3's checks explicitly, as the old T9 restated monotonicity)
    # ------------------------------------------------------------------
    print()
    r1_ok2, r2_ok2, r3_ok2, detail2 = tier_correctness(tiers, primary_pool, RANK)
    check("T9: R1-R3 tier correctness re-confirmed for the primary test case", r1_ok2 and r2_ok2 and r3_ok2, detail2)

    print()
    print("=" * 70)
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
    else:
        print("ALL TESTS PASSED")
    print("=" * 70)
    return len(failures) == 0


if __name__ == "__main__":
    import sys
    sys.exit(0 if run() else 1)
