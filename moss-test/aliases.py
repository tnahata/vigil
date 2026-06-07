"""Drug alias normalization for Vigil Tier-1 retrieval.

Maps spoken synonyms, brand names, and abbreviations to the canonical drug
strings stored in the Moss index metadata `drug` field.  Without this step,
exact-keyword queries miss on pronunciation variants ("epi" vs "epinephrine")
and the Tier-1 100%-accuracy gate fails on phrasing, not retrieval.

Usage:
    canonical = normalize_drug("epi")          # "EPINEPHRINE (1:1,000)"
    canonical = extract_drug_from_query(query) # first canonical match or None
"""

from __future__ import annotations

import re

# Canonical drug names must match the `drug` field in chunks.json exactly.
# Keys are lowercased synonyms; values are the canonical name.
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
    # EPINEPHRINE (1:10,000) — cardiac arrest dose
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

# Sorted longest-first so multi-word aliases match before single words.
_SORTED_ALIASES = sorted(DRUG_ALIASES.keys(), key=len, reverse=True)


def normalize_drug(term: str) -> str | None:
    """Return the canonical drug name for a synonym, or None if unknown."""
    return DRUG_ALIASES.get(term.lower().strip())


def find_drug_span(query: str) -> tuple[str, int] | None:
    """Return (canonical_name, match_start_index) for the first drug alias found.

    Aliases are tried longest-first so multi-word names win over their single
    words. The start index lets the caller resolve population by proximity to
    the actual drug mention. Returns None if no alias is present.
    """
    q = query.lower()
    for alias in _SORTED_ALIASES:
        m = re.search(r"\b" + re.escape(alias) + r"\b", q)
        if m:
            return DRUG_ALIASES[alias], m.start()
    return None


def extract_drug_from_query(query: str) -> str | None:
    """Scan a query string for any known drug alias and return its canonical name."""
    span = find_drug_span(query)
    return span[0] if span else None
