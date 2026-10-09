"""Conservative security-type exclusions for the default online equity universe.

Nasdaq's directory has no common-equity flag. Use documented ACT/CQS suffixes
and explicit instrument descriptions, never a Nasdaq ticker's final letter.
https://www.nasdaqtrader.com/trader.aspx?id=CQSsymbolconvention
"""

import re


COMMON_DESCRIPTION = re.compile(
    r"\b(?:common\s+(?:stock|shares?|units)|ordinary\s+shares?|"
    r"(?:american|global)\s+deposit[ao]ry\s+(?:shares?|receipts?)|"
    r"shares?\s+of\s+beneficial\s+interest)\b", re.I,
)
# These contexts describe an instrument, rather than an issuer with an unusual
# name. Bundled units/warrants/rights may mention ordinary shares later on.
BUNDLE_DESCRIPTIONS = (
    ("warrant", re.compile(r"\bwarrants?\s*(?:[,;(]|\s+(?:exercisable|each|to\s+purchase)\b)", re.I)),
    ("unit", re.compile(r"\bunits?\s*(?:[,;(]|\s+(?:each\s+consisting|consisting\s+of)\b)", re.I)),
    ("right", re.compile(r"\brights\s*(?:[,;(]|\s+(?:each|that\s+convert|to\s+(?:receive|purchase|acquire)|expiring)\b)", re.I)),
)
NAME_RULES = (
    ("preferred", re.compile(r"\b(?:preferred|preference)\s+(?:stock|shares?|securities|units|class\s+[a-z]\b)\b", re.I)),
    ("debt", re.compile(
        r"\b(?:notes?|bonds?|debentures?)\s+(?:due|maturing)\b|"
        r"\b(?:senior|subordinated|mortgage|convertible|secured|unsecured)\s+"
        r"(?:(?:senior|junior|subordinated|convertible|secured|unsecured)\s+)*"
        r"(?:notes?|bonds?|debentures?)\b|\bexchange[- ]traded\s+notes?\b", re.I,
    )),
    ("warrant", re.compile(r"\bwarrants?\s*[.]?$|^(?:(?:class\s+[a-z]|redeemable|public)\s+)*warrants?\b", re.I)),
    ("unit", re.compile(r"(?<!common )\bunits?\s*$|^units?\b", re.I)),
    ("right", re.compile(r"\brights?\s*$|^(?:subscription\s+)?rights?\b", re.I)),
)


def non_common_equity_reason(row: dict, directory: str) -> str | None:
    """Return an exclusion reason only when the security type is identifiable.

    Keep equity ADRs, REIT/trust common shares and partnership common units.
    An issuer name containing 'Preferred', 'Bond', 'Rights', etc. is not enough.
    """
    if directory == "otherlisted":
        act = (row.get("ACT Symbol") or "").strip()
        cqs = (row.get("CQS Symbol") or "").strip()
        if "$" in act or re.fullmatch(r"[A-Z0-9]+p[A-Z]?(?:\.(?:CL|CV|WD))?", cqs):
            return "preferred"
        if re.search(r"\.W$", act) or re.search(r"\.WS(?:\.[A-Z])?$", cqs):
            return "warrant"
        if act.endswith(".U") or cqs.endswith(".U"):
            return "unit"
        if act.endswith(".R") or re.fullmatch(r"[A-Z0-9]+r(?:w)?", cqs):
            return "right"

    name = (row.get("Security Name") or "").strip()
    description = name.rsplit(" - ", 1)[-1] if directory == "nasdaqlisted" else name
    common = COMMON_DESCRIPTION.search(description)
    if common and not (directory == "nasdaqlisted" and " - " in name):
        # Strip issuer text before an explicit common-equity description, but
        # first detect bundles whose components include ordinary/common shares.
        prefix = description[:common.start()]
        for reason, pattern in BUNDLE_DESCRIPTIONS:
            if pattern.search(prefix):
                return reason
        description = description[common.start():]
    for reason, pattern in (*BUNDLE_DESCRIPTIONS, *NAME_RULES):
        if pattern.search(description):
            return reason
    return None
