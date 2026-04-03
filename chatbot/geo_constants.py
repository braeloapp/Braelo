"""
Shared US city → state inference for directory / Mongo search.

Used when the user names a city (e.g. Los Angeles) but profile or partial parse
has a different state — Mongo location filters are ANDed, so wrong state drops all rows.
"""

from __future__ import annotations

# When the message names a city but not a state, directory lookup needs a US state;
# infer it for well-known cities so Mongo matches Lista rows (state/city fields).
MAJOR_US_CITY_TO_STATE: dict[str, str] = {
    "los angeles": "California",
    "san francisco": "California",
    "san diego": "California",
    "san jose": "California",
    "sacramento": "California",
    "oakland": "California",
    "fresno": "California",
    "long beach": "California",
    "anaheim": "California",
    "santa ana": "California",
    "riverside": "California",
    "stockton": "California",
    "irvine": "California",
    "chula vista": "California",
    "fremont": "California",
    "san bernardino": "California",
    "modesto": "California",
    "fontana": "California",
    "oxnard": "California",
    "moreno valley": "California",
    "huntington beach": "California",
    "santa clarita": "California",
    "garden grove": "California",
    "oceanside": "California",
    "rancho cucamonga": "California",
    "santa rosa": "California",
    "ontario": "California",
    "elk grove": "California",
    "corona": "California",
    "burbank": "California",
    "pasadena": "California",
    "inglewood": "California",
    "torrance": "California",
    "santa monica": "California",
    "beverly hills": "California",
    "new york": "New York",
    "buffalo": "New York",
    "rochester": "New York",
    "yonkers": "New York",
    "chicago": "Illinois",
    "houston": "Texas",
    "dallas": "Texas",
    "austin": "Texas",
    "san antonio": "Texas",
    "fort worth": "Texas",
    "miami": "Florida",
    "orlando": "Florida",
    "tampa": "Florida",
    "jacksonville": "Florida",
    "phoenix": "Arizona",
    "tucson": "Arizona",
    "philadelphia": "Pennsylvania",
    "pittsburgh": "Pennsylvania",
    "boston": "Massachusetts",
    "atlanta": "Georgia",
    "seattle": "Washington",
    "denver": "Colorado",
    "las vegas": "Nevada",
    "detroit": "Michigan",
    "minneapolis": "Minnesota",
    "portland": "Oregon",
    "nashville": "Tennessee",
    "washington dc": "District of Columbia",
}


def backfill_state_from_major_us_city(state: str | None, city: str | None) -> str | None:
    """
    If the message names a major US city, infer its state when state is missing.
    When profile state conflicts with that city (e.g. user asks for Los Angeles but profile says Texas),
    prefer the state implied by the city so Mongo/geo search matches the user's intent.
    """
    c = (city or "").strip()
    if not c:
        return (state or "").strip() or None
    key = " ".join(c.lower().split())
    inferred = MAJOR_US_CITY_TO_STATE.get(key)
    st = (state or "").strip()
    if not inferred:
        return st or None
    if not st:
        return inferred
    if st.lower().replace(".", "") == inferred.lower().replace(".", ""):
        return state
    return inferred
