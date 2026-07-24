"""
Rerun extraction over everything currently in data/raw/ and rebuild
data/processed/master_cutoffs.csv.

Usage: drop new KCET cutoff PDFs into data/raw/ (same filename convention
as the existing ones: <year>_<first|second|third>_round_<kalyana_karnataka|
rest_of_karnataka>.pdf) and run:

    python3 update_data.py

Design note: this rebuilds master_cutoffs.csv from the FULL set of PDFs in
data/raw/ every time, rather than appending row-by-row to the existing
CSV. That's what makes it safe to rerun - re-running extraction on files
that were already processed always reproduces the same rows, so there's
nothing to de-duplicate against. Dropping in new files just means the
rebuilt CSV additionally contains whatever those new files contain. A
de-dup pass still runs afterwards as a safety net, in case a future
extraction run ever produces an overlapping row some other way (e.g. the
same round released twice under different filenames).
"""

import csv
import os
import subprocess
import sys

RAW_DIR = "data/raw"
MASTER_CSV = "data/processed/master_cutoffs.csv"
EXTRACTION_LOG = "data/processed/update_data_last_run.log"


def count_rows(path):
    if not os.path.exists(path):
        return 0
    with open(path, newline="", encoding="utf-8") as f:
        return sum(1 for _ in f) - 1  # minus header


def dedupe(path):
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return 0

    def key(r):
        return (r["college_code"], r["branch_code"], r["branch_name"],
                 r["category"], r["round"], r["year"], r["source_file"])

    seen = {}
    for r in rows:
        seen[key(r)] = r  # keep the last occurrence
    deduped = list(seen.values())

    removed = len(rows) - len(deduped)
    if removed:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(deduped)
    return removed


def main():
    pdfs = sorted(f for f in os.listdir(RAW_DIR) if f.lower().endswith(".pdf"))
    print(f"Found {len(pdfs)} PDF(s) in {RAW_DIR}/:")
    for f in pdfs:
        print(f"  - {f}")

    before = count_rows(MASTER_CSV)

    print(f"\nRunning extract_cutoffs.py over all files "
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

    removed = dedupe(MASTER_CSV)
    after = count_rows(MASTER_CSV)

    print(f"\nmaster_cutoffs.csv: {before} rows -> {after} rows ({after - before:+d})")
    if removed:
        print(f"Removed {removed} duplicate row(s) during the safety-net de-dup pass.")

    with open(MASTER_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    years = sorted(set(r["year"] for r in rows))
    print(f"Years covered: {', '.join(years)}")
    print("Done. The app reads this file fresh on next load - no rebuild needed.")


if __name__ == "__main__":
    main()
