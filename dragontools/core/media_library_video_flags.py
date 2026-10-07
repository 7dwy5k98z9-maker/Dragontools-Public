"""Shared evidence policy for SQL filtering and displayed video flags."""
import re

HDR10PLUS_MARKERS = (
    "hdr10+", "hdr10plus", "dynamic metadata", "2094-40", "st2094",
    "2094 app 4", "st 2094 app 4",
)
DV_MARKERS = ("dolby vision", "dovi", "dvhe", "dvh1", "dva1", "dvav", "dav1", "dolbyvision")
HDR_MARKERS = ("hdr", "bt2020", "pq", "hlg", "dolby", "smpte2084", "st2084", *DV_MARKERS)


def positive_dv_profile(value):
    text = str(value or "").strip()
    return bool(re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", text) and float(text) >= 1)


def positive_dv_profile_sql(alias):
    # SQL aliases are internal constants, never user input. Mirror the numeric
    # profile rule without requiring a custom SQLite function in exported DBs.
    value = f"trim(coalesce({alias}.dv_profile, ''))"
    return (
        f"(CAST({value} AS INTEGER)>0 AND {value} NOT GLOB '*[^0-9.]*' "
        f"AND {value} NOT LIKE '.%' AND {value} NOT LIKE '%.' "
        f"AND length({value})-length(replace({value}, '.', ''))<=1)"
    )
