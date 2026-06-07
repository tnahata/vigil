"""Drug alias normalization -- the make-or-break detail for Tier 1.

Exact keyword retrieval whiffs on synonyms ("adrenaline" vs "epinephrine",
"epi", brand names). We map every spoken variant to ONE canonical name BEFORE
retrieval so a filtered exact lookup can hit.

The canonical names here MUST match the `drug` metadata field in the Moss index
(built from data/chunks.json) byte-for-byte -- they are the UPPERCASE protocol
names (e.g. "EPINEPHRINE (1:1,000)"), because Tier-1 filters with `drug $eq
<canonical>`. A lowercase/abbreviated mismatch makes every dose query miss.

Pure: stdlib only (re). No external imports -- enforced by test_core_purity.
"""
from __future__ import annotations

import re

# Lowercased spoken synonym -> canonical drug name (exactly as stored in the
# index `drug` metadata). Multi-word keys are matched whole, longest-first.
DRUG_ALIASES: dict[str, str] = {
    # ACETAMINOPHEN
    "acetaminophen": "ACETAMINOPHEN (IV)",
    "tylenol": "ACETAMINOPHEN (IV)",
    "apap": "ACETAMINOPHEN (IV)",
    "iv acetaminophen": "ACETAMINOPHEN (IV)",
    "ofirmev": "ACETAMINOPHEN (IV)",
    # ACTIVATED CHARCOAL
    "activated charcoal": "ACTIVATED CHARCOAL",
    "charcoal": "ACTIVATED CHARCOAL",
    "ac": "ACTIVATED CHARCOAL",
    # ADENOSINE
    "adenosine": "ADENOSINE",
    "adenocard": "ADENOSINE",
    # ALBUTEROL / LEVALBUTEROL
    "albuterol": "ALBUTEROL / LEVALBUTEROL",
    "levalbuterol": "ALBUTEROL / LEVALBUTEROL",
    "xopenex": "ALBUTEROL / LEVALBUTEROL",
    "proventil": "ALBUTEROL / LEVALBUTEROL",
    "ventolin": "ALBUTEROL / LEVALBUTEROL",
    "salbutamol": "ALBUTEROL / LEVALBUTEROL",
    # AMIODARONE
    "amiodarone": "AMIODARONE",
    "cordarone": "AMIODARONE",
    "nexterone": "AMIODARONE",
    # ASPIRIN
    "aspirin": "ASPIRIN",
    "asa": "ASPIRIN",
    "bayer": "ASPIRIN",
    "acetylsalicylic acid": "ASPIRIN",
    # ATROPINE
    "atropine": "ATROPINE",
    "atropine sulfate": "ATROPINE",
    # BUPRENORPHINE-NALOXONE
    "buprenorphine": "BUPRENORPHINE-NALOXONE",
    "buprenorphine naloxone": "BUPRENORPHINE-NALOXONE",
    "suboxone": "BUPRENORPHINE-NALOXONE",
    "bupe": "BUPRENORPHINE-NALOXONE",
    # CALCIUM CHLORIDE
    "calcium chloride": "CALCIUM CHLORIDE",
    "calcium": "CALCIUM CHLORIDE",
    "cacl": "CALCIUM CHLORIDE",
    "cacl2": "CALCIUM CHLORIDE",
    # DEXTROSE
    "dextrose": "DEXTROSE",
    "d50": "DEXTROSE",
    "d10": "DEXTROSE",
    "d25": "DEXTROSE",
    "glucose": "DEXTROSE",
    "sugar": "DEXTROSE",
    # DIPHENHYDRAMINE
    "diphenhydramine": "DIPHENHYDRAMINE",
    "benadryl": "DIPHENHYDRAMINE",
    "dph": "DIPHENHYDRAMINE",
    # EPINEPHRINE (1:1,000)
    "epinephrine": "EPINEPHRINE (1:1,000)",
    "epi": "EPINEPHRINE (1:1,000)",
    "adrenaline": "EPINEPHRINE (1:1,000)",
    "epinephrine 1:1000": "EPINEPHRINE (1:1,000)",
    "epi 1:1000": "EPINEPHRINE (1:1,000)",
    "epipen": "EPINEPHRINE (1:1,000)",
    # EPINEPHRINE (1:10,000) -- cardiac arrest dose
    "epinephrine 1:10000": "EPINEPHRINE (1:10,000)",
    "epi 1:10000": "EPINEPHRINE (1:10,000)",
    "epinephrine cardiac": "EPINEPHRINE (1:10,000)",
    # EPINEPHRINE (1:100,000)
    "epinephrine 1:100000": "EPINEPHRINE (1:100,000)",
    "epi 1:100000": "EPINEPHRINE (1:100,000)",
    # FENTANYL
    "fentanyl": "FENTANYL",
    "fent": "FENTANYL",
    "sublimaze": "FENTANYL",
    # GLUCAGON
    "glucagon": "GLUCAGON",
    # IPRATROPIUM BROMIDE
    "ipratropium": "IPRATROPIUM BROMIDE",
    "ipratropium bromide": "IPRATROPIUM BROMIDE",
    "atrovent": "IPRATROPIUM BROMIDE",
    # KETAMINE (in the data, but absent from the original alias map -> unreachable)
    "ketamine": "KETAMINE",
    "ketalar": "KETAMINE",
    "ket": "KETAMINE",
    # LIDOCAINE
    "lidocaine": "LIDOCAINE",
    "lido": "LIDOCAINE",
    "xylocaine": "LIDOCAINE",
    # MIDAZOLAM
    "midazolam": "MIDAZOLAM",
    "versed": "MIDAZOLAM",
    "benzo": "MIDAZOLAM",
    # MORPHINE
    "morphine": "MORPHINE",
    "ms contin": "MORPHINE",
    "morphine sulfate": "MORPHINE",
    # NALOXONE
    "naloxone": "NALOXONE",
    "narcan": "NALOXONE",
    "nalo": "NALOXONE",
    # NITROGLYCERIN
    "nitroglycerin": "NITROGLYCERIN",
    "nitro": "NITROGLYCERIN",
    "ntg": "NITROGLYCERIN",
    "nitrostat": "NITROGLYCERIN",
    "glyceryl trinitrate": "NITROGLYCERIN",
    # ONDANSETRON
    "ondansetron": "ONDANSETRON",
    "zofran": "ONDANSETRON",
    "zofran odt": "ONDANSETRON",
    # SODIUM BICARBONATE
    "sodium bicarbonate": "SODIUM BICARBONATE",
    "bicarb": "SODIUM BICARBONATE",
    "sodium bicarb": "SODIUM BICARBONATE",
    "nahco3": "SODIUM BICARBONATE",
    "baking soda": "SODIUM BICARBONATE",
    # TRANEXAMIC ACID
    "tranexamic acid": "TRANEXAMIC ACID",
    "txa": "TRANEXAMIC ACID",
    "cyklokapron": "TRANEXAMIC ACID",
}

# Back-compat aliases for the previous module's public names.
ALIASES: dict[str, str] = DRUG_ALIASES
CANONICAL_DRUGS: set[str] = set(DRUG_ALIASES.values())

# Try multi-word / longer aliases first so "tranexamic acid" wins over a bare
# word and "epinephrine 1:10000" wins over "epinephrine".
_SORTED_ALIASES = sorted(DRUG_ALIASES, key=len, reverse=True)

# STT often glues a drug name to a following intent word ("epi dose" -> "epidose").
# These compounds whiff on whole-word alias + dose-intent matching, so a real query
# routes to UNKNOWN on phrasing, not retrieval. We split them back apart, but ONLY
# when BOTH halves are recognized -- so "epidural"/"episode" (a drug-alias prefix +
# an UNknown suffix) are never touched. Only single-token aliases can glue.
_DOSE_SUFFIXES = ("dose", "dosage", "dosing", "drip", "bolus", "push")
_SINGLE_TOKEN_ALIASES = [a for a in _SORTED_ALIASES if " " not in a]
_ALIAS_ALT = "|".join(re.escape(a) for a in _SINGLE_TOKEN_ALIASES)
_GLUED_RE = re.compile(
    r"\b(" + _ALIAS_ALT + r")(" + "|".join(_DOSE_SUFFIXES) + r")\b",
    re.IGNORECASE,
)


def split_glued_terms(query: str) -> str:
    """Insert a space in glued <drug-alias><dose-word> compounds from STT.

    Safe by construction: only fires when the prefix is a known alias AND the
    suffix is a known dose-intent word, so non-drug words are left untouched.
    """
    if not query:
        return query
    return _GLUED_RE.sub(lambda m: f"{m.group(1)} {m.group(2)}", query)


def normalize_drug(token: str | None) -> str | None:
    """Map a drug term (single word or known multi-word alias) to its canonical
    name, or None if unknown."""
    if not token:
        return None
    return DRUG_ALIASES.get(token.strip().lower())


def find_drug_span(query: str) -> tuple[str, int] | None:
    """Return (canonical_name, match_start_index) for the first drug alias found.

    Aliases are tried longest-first so multi-word names win over their single
    words. The start index lets a caller resolve population by proximity to the
    actual drug mention. Returns None if no alias is present.
    """
    if not query:
        return None
    q = query.lower()
    for alias in _SORTED_ALIASES:
        m = re.search(r"\b" + re.escape(alias) + r"\b", q)
        if m:
            return DRUG_ALIASES[alias], m.start()
    return None


def extract_drug(query: str) -> str | None:
    """Scan a free-text query for a recognizable drug; canonical name or None.

    Uses longest-alias-first whole-word matching so multi-word names and
    concentration-qualified variants ("epi 1:10000") resolve correctly.
    """
    span = find_drug_span(query)
    return span[0] if span else None
