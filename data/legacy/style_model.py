"""
Deterministic playstyle-radar model for the Grandmaster Almanac.

Why this exists
---------------
The rest of the roster (~2,142 GMs) already carries a `style` object with six
integer axes -- aggressive, defense, endgame, opening, positional, tactical --
labelled on the site as an "Estimated" heuristic. Brand-new GMs added by the
monthly refresh were getting `style: {}` and rendered with a broken/empty
radar. The site treats style as an estimate, so the fix is to *compute* the
same kind of estimate for new GMs at refresh time rather than leave the field
blank.

The model
---------
Reverse-engineered from the shipped dataset. Per-axis OLS across all 1,890
players with (rating, age, style):

    axis_value ≈ intercept + 0.048 × rating + small_age_coef × age
                + hash_noise(id, axis)

Residual standard deviation is ~11.5 per axis, which matches a deterministic
per-player offset in roughly the ±20 range. So the effective formula is:

    v(id, axis) = clamp( base(rating, age, axis) + jitter(id, axis) , 15, 95 )

`jitter` is derived from sha256(id, axis) so the same player gets the same
radar every month -- no drift when refresh runs.

Age coefficients per axis were fit on the current roster; the intercepts are
re-centered so a hypothetical 2500-rated 30-year-old lands near each axis's
observed roster mean.
"""

import hashlib

STYLE_AXES = ("aggressive", "defense", "endgame", "opening", "positional", "tactical")

# Age effects observed in the shipped data (r=... in the fit):
#  - aggressive/tactical fall with age (younger players skew attacking)
#  - endgame/positional rise slightly with age (older players are more classical)
#  - defense/opening are roughly age-neutral
#
# Coefficients here are the fitted OLS slopes with age; intercepts are then
# solved so that the (rating=2500, age=30) point lands at each axis's roster
# mean, giving a mid-tier GM a plausible "average" radar out of the box.
AXIS_MEAN_AT_2500_AGE30 = {
    "aggressive": 52,
    "defense": 56,
    "endgame": 58,
    "opening": 55,
    "positional": 59,
    "tactical": 52,
}
AGE_COEF = {
    "aggressive": -0.19,
    "defense": +0.02,
    "endgame": +0.10,
    "opening": +0.03,
    "positional": +0.17,
    "tactical": -0.13,
}
RATING_COEF = 0.048  # roughly identical across axes in the fit

# Jitter amplitude matches the ~11.5 residual stdev of the fit: ±18 keeps the
# radar shape distinctive per-player without blowing past the [15, 95] clamp.
JITTER_AMPLITUDE = 18
MIN_VAL, MAX_VAL = 15, 95


def _hash_jitter(player_id: str, axis: str) -> float:
    """Deterministic ±JITTER_AMPLITUDE offset for (id, axis).

    Uses sha256 so the offset is stable forever -- a player's radar shape does
    not shift between monthly refreshes.
    """
    h = hashlib.sha256(f"{player_id}|{axis}".encode("utf-8")).digest()
    # Take first 4 bytes as a uint32 in [0, 2**32), map to [-1, 1].
    n = int.from_bytes(h[:4], "big") / (2**32 - 1)  # [0, 1]
    return (n * 2 - 1) * JITTER_AMPLITUDE


def compute_style(player_id, rating, bday=None, now_year=None):
    """
    Compute a six-axis playstyle radar for a player.

    Parameters
    ----------
    player_id : str
        FIDE ID (used as the deterministic jitter seed).
    rating : int or None
        Current FIDE standard rating. Falls back to 2500 (the GM floor) when
        missing so brand-new GMs still get a plausible radar.
    bday : int or None
        Four-digit birth year. Falls back to a mid-career assumption of
        (now_year - 30) when missing.
    now_year : int or None
        Reference year for age; defaults to the current UTC year.

    Returns
    -------
    dict[str, int]
        Integer values in [MIN_VAL, MAX_VAL], one per axis in STYLE_AXES.
    """
    if now_year is None:
        from datetime import datetime, timezone
        now_year = datetime.now(timezone.utc).year

    r = rating if isinstance(rating, (int, float)) and rating else 2500
    age = (now_year - bday) if isinstance(bday, int) and 1900 < bday < now_year else 30

    out = {}
    for axis in STYLE_AXES:
        base_center = AXIS_MEAN_AT_2500_AGE30[axis]
        # Re-express: base(r, age) = center + RATING_COEF*(r-2500) + AGE_COEF*(age-30)
        base = base_center + RATING_COEF * (r - 2500) + AGE_COEF[axis] * (age - 30)
        val = base + _hash_jitter(player_id, axis)
        val = max(MIN_VAL, min(MAX_VAL, round(val)))
        out[axis] = int(val)
    return out
