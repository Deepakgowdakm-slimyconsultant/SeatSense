"""
Assertion-based tests for seatsense.data.predict(). Run with:
    python3 test_tiers.py
"""

from seatsense.data import (
    available_bases,
    load_data,
    predict,
    reference_year,
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

    # ------------------------------------------------------------------
    # T10: same-name, different-code colleges (E003 and E048 are both
    # "B M S College of Engineering, Basavanagudi, Bangalore" but are
    # distinct KEA entries with different cutoffs in every branch/category
    # combo checked - 0/38 identical). At rank=30000, CIVIL ENGINEERING,
    # GMH: E003 fails R1 (26404) but clears R2 (32952) -> Possible; E048
    # clears R1 (33471) -> Strong Chance. Both must appear, tagged with
    # their own distinct codes, neither merged nor deduped by name.
    # ------------------------------------------------------------------
    print()
    bms_branch = "CIVIL ENGINEERING"
    bms_category = "GMH"
    bms_rank = 30000
    bms_tiers, bms_year = predict(df, bms_rank, bms_category, bms_branch, True)

    e003 = next((c for c in bms_tiers["Possible"] if c["college_code"] == "E003"), None)
    e048 = next((c for c in bms_tiers["Strong Chance"] if c["college_code"] == "E048"), None)
    check("T10: E003 (BMS) appears in Possible tier with its own code", e003 is not None)
    check("T10: E048 (BMS) appears in Strong Chance tier with its own code", e048 is not None)
    if e003 and e048:
        check(
            "T10: E003 and E048 share the same college_name but are NOT the same college_code",
            e003["college_name"] == e048["college_name"] and e003["college_code"] != e048["college_code"],
            detail=f"E003 name={e003['college_name']!r} E048 name={e048['college_name']!r}",
        )
        check(
            "T10: E003 and E048 carry different cutoff_rank values (not merged/deduped)",
            e003["cutoff_rank"] != e048["cutoff_rank"],
            detail=f"E003={e003['cutoff_rank']} E048={e048['cutoff_rank']}",
        )

    # ------------------------------------------------------------------
    # T11: merging 2026 Round 1 data must be inert for reference_year() -
    # the decision was "keep everyone on 2025 for now" (no 2026 R2/R3
    # exists yet, so no cross-year blend was built). This must hold even
    # though year=2026 rows are present in the dataset.
    # ------------------------------------------------------------------
    print()
    check("T11: reference_year() is still 2025 after merging 2026 Round 1 data", year == 2025, detail=str(year))
    check("T11: year=2026 rows ARE present in the dataset (merge succeeded)", (df["year"] == 2026).any())

    # ------------------------------------------------------------------
    # T12/T13 (redefined from the original spec - see note below): for a
    # NON-SC category, Strong Chance must still come from 2025 Round 1,
    # NOT 2026. The original spec's T13 asserted the opposite (2026 Round 1
    # used for Strong Chance), but that assumed a cross-year fallback
    # mechanism the user explicitly declined to build this pass ("keep
    # everyone on 2025 for now"). Asserting the original T13 literally
    # would contradict the chosen design, so this asserts what's actually
    # true under that decision instead - flagged, not silently swapped.
    # ------------------------------------------------------------------
    print()
    non_sc_tiers, non_sc_year = predict(df, 5000, "GM", "COMPUTER SCIENCE AND ENGINEERING", False)
    check(
        "T12 (was T13 in the original spec - see comment above): non-SC category "
        "Strong Chance uses year=2025, not 2026 (per 'keep everyone on 2025 for now')",
        non_sc_year == 2025,
        detail=str(non_sc_year),
    )

    # ------------------------------------------------------------------
    # T13: S1-S4 (former SC, Option B categories) must NOT appear as
    # selectable dropdown options while reference_year() is 2025 - they
    # have zero rows in 2025, so offering them would be a dead end (see
    # available_bases()'s year-scoping fix). This is the concrete,
    # buildable consequence of "keep everyone on 2025 for now": Option B's
    # card-text behavior (explicitly explaining no Round 2/3 comparison is
    # possible) has nothing to attach to yet, because there is no live path
    # to reach an SC-family category at all until reference_year() itself
    # advances to 2026 - which won't happen until 2026 Round 2/3 exists.
    # ------------------------------------------------------------------
    print()
    bases_rok = dict(available_bases(df, False))
    check("T13: S1 (SCA) is NOT offered in the category dropdown this cycle", "S1" not in bases_rok)
    check("T13: S2 (SCB) is NOT offered in the category dropdown this cycle", "S2" not in bases_rok)
    check("T13: S3 (SCC 80%) is NOT offered in the category dropdown this cycle", "S3" not in bases_rok)
    check("T13: S4 (SCC 20%) is NOT offered in the category dropdown this cycle", "S4" not in bases_rok)
    check("T13: SC (2023-2025 codes) is still offered, unaffected", "SC" in bases_rok)

    # Defensive check only (not reachable via the UI given the check above):
    # predict() must not crash if ever called directly with an S1-S4 code -
    # it should return cleanly empty tiers (no rows in 2025 for that code),
    # not raise. No "situation-explaining" card text exists for this path
    # yet - that part of Option B is genuinely deferred, not implemented,
    # since it was scoped to the cross-year blend that was declined.
    sc_family_tiers, _ = predict(df, 5000, "S2G", "COMPUTER SCIENCE AND ENGINEERING", False)
    check(
        "T13: predict() with an S1-S4 code doesn't crash and returns cleanly empty tiers "
        "(not reachable via the dropdown, but must not break if called directly)",
        all(len(v) == 0 for v in sc_family_tiers.values()),
        detail=str(sc_family_tiers),
    )

    # ------------------------------------------------------------------
    # T14: same as T11-T13, but for the Kalyana Karnataka (HK) side, added
    # once the companion 2026 KK file was merged. The Step 3 decision
    # ("keep everyone on 2025 for now") was explicitly NOT to be
    # re-litigated for H-suffixed codes - this confirms the SAME behavior
    # holds for HK without any separate code path or special-casing.
    # ------------------------------------------------------------------
    print()
    check(
        "T14: reference_year() is still 2025 after merging 2026 Kalyana Karnataka data too",
        reference_year(df) == 2025,
        detail=str(reference_year(df)),
    )

    hk_tiers, hk_year = predict(df, 20000, "2AH", "COMPUTER SCIENCE AND ENGINEERING", True)
    check(
        "T14: normal HK category (2AH, unaffected by the SC split) still returns real "
        "2025 results end-to-end - no regression from adding the second 2026 file",
        hk_year == 2025 and sum(len(v) for v in hk_tiers.values()) > 0,
        detail=f"year={hk_year} total_results={sum(len(v) for v in hk_tiers.values())}",
    )

    bases_hk = dict(available_bases(df, True))
    check("T14: S1H (SCA) is NOT offered in the HK category dropdown this cycle", "S1" not in bases_hk)
    check("T14: S2H (SCB) is NOT offered in the HK category dropdown this cycle", "S2" not in bases_hk)
    check("T14: S3H (SCC 80%) is NOT offered in the HK category dropdown this cycle", "S3" not in bases_hk)
    check("T14: S4H (SCC 20%) is NOT offered in the HK category dropdown this cycle", "S4" not in bases_hk)
    check("T14: SC (2023-2025 HK codes, i.e. SCH/SCKH/SCRH) is still offered, unaffected", "SC" in bases_hk)

    s1h_tiers, _ = predict(df, 20000, "S1H", "COMPUTER SCIENCE AND ENGINEERING", True)
    check(
        "T14: predict() with S1H directly doesn't crash and returns cleanly empty tiers "
        "(same consistent behavior as S1G on the Rest-of-Karnataka side - not re-litigated)",
        all(len(v) == 0 for v in s1h_tiers.values()),
        detail=str(s1h_tiers),
    )

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
