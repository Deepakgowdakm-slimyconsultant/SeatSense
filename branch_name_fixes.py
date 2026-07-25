"""
Fixes for a specific, confirmed extraction bug: KEA's 2025 cutoff PDFs wrap
long course names across two lines within a narrow table cell, and the wrap
sometimes lands in the MIDDLE of a word rather than between words (e.g.
"TELECOMMUNICAT" / "ION" split across lines). The extraction pipeline
(extract_cutoffs.py) always inserts a space when rejoining two wrapped
lines within one cell - correct for word-boundary wraps ("Artificial" +
"Intelligence"), wrong for mid-word ones.

This is NOT a generic auto-detector (there's no reliable PDF-geometry
signal to tell a mid-word wrap from a word-boundary one - both start at the
same left edge). FIX_MAP below is a manually verified, exact-substring
list built by:
  1. Auditing every branch_name in both the 2025 Round 1 data (extracted
     by this pipeline) and the externally-supplied 2025 Round 2/3 data,
  2. Cross-checking each broken fragment against a correctly-spelled
     sibling that already exists elsewhere in the dataset (e.g.
     "B LOCK CHAIN" only added once "BLOCK CHAIN" was confirmed to exist
     as another college's correctly-wrapped version of the same term),
  3. Never "correcting" a spelling KEA itself got wrong - e.g. "ARTI
     FICAL" (KEA's own typo, missing an I) is glued to "ARTIFICAL",
     preserving the typo, not "fixed" to "ARTIFICIAL".

Extend this list only the same way: a concrete, verified broken/fixed
pair, never a guess.
"""

FIX_MAP = {
    "COMMUNICATIO N": "COMMUNICATION",
    "INSTRUMENTATI ON": "INSTRUMENTATION",
    "INSTRUMENTATIO N": "INSTRUMENTATION",
    "ENVIRONMENTA L": "ENVIRONMENTAL",
    "MANUFACTURIN G": "MANUFACTURING",
    "PHARMACEUTIC AL": "PHARMACEUTICAL",
    "BIOTECHNOLOG Y": "BIOTECHNOLOGY",
    "B LOCK": "BLOCK",
    "BLO CK": "BLOCK",
    "I OT": "IOT",
    "B IG DATA": "BIG DATA",
    "D EV OPS": "DEV OPS",
    "DE V OPS": "DEV OPS",
    "S OFTWARE": "SOFTWARE",
    "SO FTWARE": "SOFTWARE",
    "SOF TWARE": "SOFTWARE",
    "Clou d": "Cloud",
    "ARTI FICIAL": "ARTIFICIAL",
    "ARTI FICAL": "ARTIFICAL",   # preserves KEA's own typo (missing I) - not a spelling fix
    "AR TIFICAL": "ARTIFICAL",   # same typo, different wrap point
    "IND USTRIAL": "INDUSTRIAL",
    "I NDUSTRIAL": "INDUSTRIAL",
    "DAT A": "DATA",
    "CYB ER": "CYBER",
    "TELECOMMUNICAT ION": "TELECOMMUNICATION",
}


def fix_branch_name(name):
    """Apply every known verified glue-fix to one branch name."""
    if not isinstance(name, str):
        return name
    out = name
    for broken, fixed in FIX_MAP.items():
        out = out.replace(broken, fixed)
    return out
