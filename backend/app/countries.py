"""ISO 3166-1 alpha-2 country codes (docs/offline-global.md section 3).

The list is bundled so validation never depends on the network. Codes are stored uppercase. A missing code
(NULL in the database) is shown as 'ID' in responses, which is the default country of the first deployment.
"""

from __future__ import annotations

from app.errors import AppError

DEFAULT_COUNTRY = "ID"

ISO_3166_1_ALPHA_2: frozenset[str] = frozenset("""
AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ
BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ
CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ
DE DJ DK DM DO DZ
EC EE EG EH ER ES ET
FI FJ FK FM FO FR
GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY
HK HM HN HR HT HU
ID IE IL IM IN IO IQ IR IS IT
JE JM JO JP
KE KG KH KI KM KN KP KR KW KY KZ
LA LB LC LI LK LR LS LT LU LV LY
MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ
NA NC NE NF NG NI NL NO NP NR NU NZ
OM
PA PE PF PG PH PK PL PM PN PR PS PT PW PY
QA
RE RO RS RU RW
SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ
TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ
UA UG UM US UY UZ
VA VC VE VG VI VN VU
WF WS
YE YT
ZA ZM ZW
""".split())


def normalize_country(value: str | None) -> str | None:
    """Trim and uppercase a country code. None or blank means 'not given'. Raises ValueError for unknown codes.

    Used as a pydantic validator, so a bad code becomes a 422 on the request body.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("country_code must be a two-letter ISO 3166-1 code.")
    code = value.strip().upper()
    if not code:
        return None
    if code not in ISO_3166_1_ALPHA_2:
        raise ValueError("Unknown country code.")
    return code


def country_query(value: str | None) -> str | None:
    """Validate a ?country= query value. Unknown codes are a 422, not an empty list."""
    try:
        return normalize_country(value)
    except ValueError:
        raise AppError("VALIDATION_FAILED", "country must be a two-letter ISO 3166-1 code.") from None


def country_or_default(code: str | None) -> str:
    """The country shown in responses. NULL rows are 'ID'."""
    return code if code else DEFAULT_COUNTRY


def country_filter(alias: str, country: str | None) -> tuple[str, list[str]]:
    """SQL fragment for a ?country= filter. Returns ('', []) when no filter is given."""
    if country is None:
        return "", []
    return f"COALESCE({alias}.country_code, '{DEFAULT_COUNTRY}') = ?", [country]
