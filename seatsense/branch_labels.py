"""
Display-only expansion of KEA's abbreviated branch names.

master_cutoffs.csv is a faithful, literal transcription of each source
PDF - it is NOT the problem here. KEA's own 2023/2024 cutoff PDFs print a
2-letter code plus a terse abbreviation (e.g. "CS Computers", "AI
Artificial Intelligence"), while the 2025 PDFs spell branch names out in
full. Because the round-wise tier comparison needs a single year with a
complete Round 1-3 dataset (see seatsense.data.reference_year), the
branch dropdown is currently sourced from 2024 - which means it shows
KEA's own short-form text.

This module expands the SAFELY-expandable subset of that text for
display only - it never invents a subject name for a private
university's own cryptic course code (e.g. "B Tech in AD" has
branch_code "BG", completely unrelated to any known "AD" meaning, so it
is left untouched rather than guessed). Only unambiguous dictionary-word
abbreviations are unpacked (e.g. "Engg." -> "Engineering", "Sc." ->
"Science"). Anything that would still contain an unresolved cryptic
fragment after expansion is returned completely unchanged.

The actual value used for filtering/matching predictions is always the
literal branch_name from master_cutoffs.csv - this module only affects
what the dropdown displays.
"""

import re

# Explicit, user-confirmed display labels for raw names the general token
# expansion below deliberately leaves alone (usually because a literal
# word-for-word expansion would collide with a different, distinct
# branch already in the data - e.g. "Computers" -> "Computer Engineering"
# would collide with the separate, existing "Computer Engineering" entry).
# Checked for collisions against the rest of the label set the same way
# as the automatic expansions.
_EXPLICIT_OVERRIDES = {
    "Computers": "Computer Science and Engineering",
}

# (abbreviation, full word) - unambiguous, standard dictionary-word
# expansions only. Sorted longest-first so e.g. "Sc." is preferred over
# "Sc" when both could match at the same position.
_TOKENS = [
    ("Aeronaut.", "Aeronautical"), ("Telecommn.", "Telecommunication"),
    ("Engg.", "Engineering"), ("Engg", "Engineering"),
    ("Mgmt.", "Management"), ("Prodn.", "Production"),
    ("Const.", "Construction"), ("Comm.", "Communication"),
    ("Info.", "Information"), ("Manf.", "Manufacturing"),
    ("Agri.", "Agriculture"), ("Instr.", "Instrumentation"),
    ("Robot.", "Robotics"), ("Elec.", "Electronics"),
    ("Inst.", "Instrumentation"), ("Sc.", "Science"), ("Sc", "Science"),
    ("Ind.", "Industrial"), ("Tech.", "Technology"),
    ("Comp.", "Computer"), ("Med.", "Medical"), ("Elect.", "Electronics"),
    ("Bus", "Business"), ("Sys.", "Systems"),
]
_TOKENS.sort(key=lambda t: -len(t[0]))

# The entire "B Tech in .../B.TECH IN ..." family is private-university
# course-code text (branch_code cross-checked and found unrelated to the
# 2-4 letter fragment in the name itself), so it's excluded wholesale
# rather than partially expanded into a confusing hybrid.
_BTECH_PREFIX_RE = re.compile(r'^B[.\s]*TECH\.?[.\s]+IN[.\s]+', re.IGNORECASE)

# "IoT" is a deliberate mixed-case stylization (Internet of Things), not
# two glued words - protect it from the word-boundary cleanup below.
_IOT_GUARD = re.compile(r'(?<![A-Za-z])IoT(?![A-Za-z])')

# Standard, universally-recognized bare acronyms that are fine to leave
# un-expanded even inside an otherwise fully spelled-out name.
_SAFE_BARE_ACRONYMS = {"VLSI", "AIML", "IOT", "AI"}
_RESIDUE_RE = re.compile(r'(?<![A-Za-z])([A-Z]{3,})\.?(?![A-Za-z])')


def _protect(text, guard_re, placeholder):
    spans = [m.span() for m in guard_re.finditer(text)]
    out = list(text)
    for s, e in spans:
        for i in range(s, e):
            out[i] = placeholder
    return "".join(out)


def _build_pattern():
    parts = []
    for tok, _ in _TOKENS:
        if tok.endswith("."):
            parts.append(r"(?<![A-Za-z])" + re.escape(tok))
        else:
            parts.append(r"(?<![A-Za-z])" + re.escape(tok) + r"(?![A-Za-z])")
    return re.compile("|".join(parts), re.IGNORECASE)


_COMBINED = _build_pattern()
_LOOKUP = {tok.lower(): full for tok, full in _TOKENS}


def _has_unresolved_residue(text):
    """True if `text` still contains a short ALL-CAPS fragment that isn't
    a recognized standard acronym - a sign the expansion is incomplete
    and would ship a confusing half-translated label."""
    for m in _RESIDUE_RE.finditer(text):
        if m.group(1).upper() not in _SAFE_BARE_ACRONYMS:
            return True
    return False


def expand_branch_label(name):
    """Best-effort expansion of one branch name for display. Returns the
    original, unchanged string whenever a safe, complete expansion isn't
    possible - never a half-translated or guessed result."""
    if not isinstance(name, str):
        return name
    if name in _EXPLICIT_OVERRIDES:
        return _EXPLICIT_OVERRIDES[name]
    if _BTECH_PREFIX_RE.match(name.strip()):
        return name

    masked = _protect(name, _IOT_GUARD, "\1")
    out = _COMBINED.sub(lambda m: _LOOKUP[m.group(0).lower()], masked)
    restored = "".join(name[i] if c == "\1" else c for i, c in enumerate(out))

    if restored == name:
        return name

    # Two expanded words sometimes end up glued with no separator (KEA's
    # own PDF text often has none either, e.g. "Info.Science") - a
    # lower-to-upper letter transition is a safe universal signal to
    # insert a space, since no legitimate English word does that.
    restored = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", restored)
    restored = re.sub(r"\s+", " ", restored).strip()

    if _has_unresolved_residue(restored):
        return name

    return restored


def branch_display_labels(branch_names):
    """Map each raw branch_name to a display label. Guaranteed
    collision-free: if two different raw names would ever expand to the
    identical label, BOTH fall back to their raw text, so two distinct
    branches can never look identical in the dropdown."""
    labels = {n: expand_branch_label(n) for n in branch_names}
    seen = {}
    collided = set()
    for raw, label in labels.items():
        if label in seen and seen[label] != raw:
            collided.add(label)
        seen[label] = raw
    if collided:
        for raw in list(labels):
            if labels[raw] in collided:
                labels[raw] = raw
    return labels
