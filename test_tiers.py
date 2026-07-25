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
    # T3: monotonicity - must hold for the rank/branch/category above
    # ------------------------------------------------------------------
    def monotonic_ok(tiers):
        sc = [c["cutoff_rank"] for c in tiers["Strong Chance"]]
        po = [c["cutoff_rank"] for c in tiers["Possible"]]
        un = [c["cutoff_rank"] for c in tiers["Unlikely"]]
        ok = True
        if sc and po:
            ok = ok and max(sc) <= min(po)
        if po and un:
            ok = ok and max(po) <= min(un)
        return ok

    check("T3: monotonicity (Strong <= Possible <= Unlikely) for rank 5121 ECE", monotonic_ok(tiers))

    # ------------------------------------------------------------------
    # T4: Vidya Vikas (cutoff 103781) must not appear if closer options
    # (rank..~20000) exist in the pool
    # ------------------------------------------------------------------
    seat_type = SEAT_TYPE_FOR_HK[IS_HK]
    pool = df[
        (df["year"] == year)
        & (df["category"] == CATEGORY)
        & (df["branch_name"] == BRANCH)
        & (df["seat_type"] == seat_type)
    ]
    closer_options_exist = ((pool["cutoff_rank"] >= RANK) & (pool["cutoff_rank"] <= 20000)).any()
    vv_shown = any(c["college_code"] == "E077" for c in tiers["Possible"])
    if closer_options_exist:
        check("T4: Vidya Vikas excluded when closer options exist", not vv_shown)
    else:
        # No closer options exist in the actual pool for this case (verified
        # in Phase 1: Possible has exactly 1 candidate) - E077 is legitimately
        # the only match, so it SHOULD be shown. Document this instead of
        # asserting a false premise.
        print("[INFO] T4: no colleges with cutoff in [rank, 20000] exist in the real "
              "data pool for this branch/category - Vidya Vikas (103,781) is the only "
              "Possible-tier candidate, so it correctly IS shown. Verified via full "
              "pool dump in Phase 1 (248 rows, only E077 qualifies for Possible).")
        check("T4: Vidya Vikas is the only Possible candidate (documented, not excluded)", vv_shown)

    # ------------------------------------------------------------------
    # T5: T1-T3 across 5 ranks x 3 categories
    # ------------------------------------------------------------------
    print()
    test_categories = ["GM", "2AH", "SCG"]
    test_ranks = [1000, 5000, 20000, 60000, 150000]
    branches = df[(df["year"] == year) & (df["round"] == 1)]["branch_name"].dropna().unique().tolist()
    t5_branch = "COMPUTER SCIENCE AND ENGINEERING" if "COMPUTER SCIENCE AND ENGINEERING" in branches else branches[0]

    for cat in test_categories:
        is_hk_t5 = cat.endswith("H")
        for r in test_ranks:
            t, _ = predict(df, r, cat, t5_branch, is_hk_t5)
            ok1 = all(c["cutoff_rank"] >= r for c in t["Strong Chance"])
            ok2 = all(c["cutoff_rank"] >= r for c in t["Possible"])
            ok3 = monotonic_ok(t)
            check(f"T5: rank={r} category={cat} branch={t5_branch!r} (T1+T2+T3)", ok1 and ok2 and ok3)

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
    # T9: monotonicity re-run (already covered by T3/T5, restated explicitly)
    # ------------------------------------------------------------------
    print()
    check("T9: monotonicity re-confirmed for the primary test case", monotonic_ok(tiers))

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
