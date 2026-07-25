"""
Rebuild data/processed/master_cutoffs.csv from scratch:
  1. Re-run extract_cutoffs.py over every PDF in data/raw/.
  2. Backfill the seat_type column (derived deterministically from each
     category code's H-suffix, not guessed).
  3. Fold in every CSV under data/manual/ - data that didn't come from a
     PDF (e.g. the 2025 Round 2/3 cutoffs, whose 4 source PDFs were never
     uploaded and were supplied pre-extracted instead). Each manual CSV
     must use the same schema as master_cutoffs.csv, minus branch_code.
  4. De-dupe on (college_code, branch_code, branch_name, category, round,
     year, seat_type) - branch_code is included because at least two
     colleges (e.g. G M UNIVERSITY, E303) have two genuinely different
     programs that share identical displayed branch_name text,
     distinguishable only by branch_code; dropping it from the key would
     silently discard one of them.

Usage:
    python3 update_data.py

Safe to rerun any time: dropping new PDFs into data/raw/ and/or new CSVs
into data/manual/ and rerunning always reproduces the same rows for
already-processed sources, so there's nothing to duplicate against.
"""

import os
import subprocess
import sys

import pandas as pd

from branch_name_fixes import fix_branch_name

RAW_DIR = "data/raw"
MANUAL_DIR = "data/manual"
MASTER_CSV = "data/processed/master_cutoffs.csv"
EXTRACTION_LOG = "data/processed/update_data_last_run.log"

KEY_COLS = ["college_code", "branch_code", "branch_name", "category", "round", "year", "seat_type"]


def derive_seat_type(category):
    import re
    m = re.match(r"^(1|2A|2B|3A|3B|GM|SC|ST)(G|K|R)?(H)?$", category)
    if not m:
        return None
    return "Kalyana Karnataka" if m.group(3) == "H" else "Rest of Karnataka"


def main():
    pdfs = sorted(f for f in os.listdir(RAW_DIR) if f.lower().endswith(".pdf"))
    print(f"Found {len(pdfs)} PDF(s) in {RAW_DIR}/:")
    for f in pdfs:
        print(f"  - {f}")

    before = 0
    if os.path.exists(MASTER_CSV):
        before = sum(1 for _ in open(MASTER_CSV, encoding="utf-8")) - 1

    print(f"\nRunning extract_cutoffs.py over all PDFs "
          f"(full log written to {EXTRACTION_LOG}) ...")
    os.makedirs(os.path.dirname(EXTRACTION_LOG), exist_ok=True)
    with open(EXTRACTION_LOG, "w", encoding="utf-8") as logf:
        result = subprocess.run(
            [sys.executable, "extract_cutoffs.py"],
            stdout=logf, stderr=subprocess.STDOUT,
        )
    if result.returncode != 0:
        print(f"extract_cutoffs.py failed (exit {result.returncode}). "
              f"See {EXTRACTION_LOG} for details.")
        sys.exit(result.returncode)

    master = pd.read_csv(MASTER_CSV, dtype={"category": str, "branch_code": str}, low_memory=False)
    master["seat_type"] = master["category"].apply(derive_seat_type)
    unresolved = master["seat_type"].isna().sum()
    if unresolved:
        print(f"WARNING: {unresolved} row(s) have a category code that doesn't "
              f"match the expected KCET pattern - seat_type left blank for those.")

    manual_files = []
    if os.path.isdir(MANUAL_DIR):
        manual_files = sorted(f for f in os.listdir(MANUAL_DIR) if f.lower().endswith(".csv"))

    frames = [master]
    for fname in manual_files:
        path = os.path.join(MANUAL_DIR, fname)
        print(f"Folding in manual data: {path}")
        extra = pd.read_csv(path, dtype={"category": str}, low_memory=False)
        extra["branch_name"] = extra["branch_name"].apply(fix_branch_name)
        if "branch_code" not in extra.columns:
            extra["branch_code"] = ""
        frames.append(extra[master.columns])

    combined = pd.concat(frames, ignore_index=True)
    before_dedup = len(combined)
    combined = combined.drop_duplicates(subset=KEY_COLS, keep="first")
    duplicates_removed = before_dedup - len(combined)

    combined.to_csv(MASTER_CSV, index=False)
    after = len(combined)

    print(f"\nmaster_cutoffs.csv: {before} rows -> {after} rows ({after - before:+d})")
    if duplicates_removed:
        print(f"Removed {duplicates_removed} duplicate row(s) during de-dup.")

    years = sorted(combined["year"].unique())
    print(f"Years covered: {', '.join(str(y) for y in years)}")
    print(f"seat_type breakdown: {combined.groupby('seat_type').size().to_dict()}")
    print("Done. The app reads this file fresh on next load - no rebuild needed.")


if __name__ == "__main__":
    main()
