"""Independent brute-force reference for shanten (RULES.md section 2), used
only to cross-check mahjong.shanten.shanten() in tests.

Written from scratch with no imports from and no helpers shared with
mahjong.shanten: this operates on a sorted tuple of raw tile values (list
semantics: .count()/.remove()/`in`) and recurses on "the smallest tile
still left," rather than mahjong.shanten's fixed-length 34-slot count
array indexed directly by tile code. Its own memo cache, its own
eye/head-selection loop, its own module.

Same two structures apply as in RULES.md section 2 (seven pairs excluded):
  - standard: 4 melds + 1 pair, found by trying every possible pair as the
    eye, then recursively grouping what's left into melds / partial melds
    (a pair used as a proto-triplet, or a two-tile proto-run) / floaters,
    and scoring each split with the standard formula:
        shanten = (4 - melds) * 2 - min(partials, 4 - melds) - has_eye
  - thirteen orphans: shanten = 13 - (unique required tiles present) -
    (1 if any of them is paired else 0)
Overall shanten = min(standard, thirteen orphans). A complete 14-tile hand
falls out of the same standard formula as -1 with no special-casing
(4 melds + eye, nothing left over).
"""

from functools import lru_cache

STANDARD_MELDS_NEEDED = 4

THIRTEEN_ORPHAN_TILES = frozenset({
    0, 8, 9, 17, 18, 26,        # terminals: man1/9, pin1/9, sou1/9
    27, 28, 29, 30,             # winds
    31, 32, 33,                 # dragons
})


def shanten_bruteforce(tiles):
    if len(tiles) not in (13, 14):
        raise ValueError("shanten_bruteforce() expects 13 or 14 tiles")
    return min(_standard_bruteforce(tiles), _orphans_bruteforce(tiles))


def _orphans_bruteforce(tiles):
    present = sorted({t for t in tiles if t in THIRTEEN_ORPHAN_TILES})
    has_pair = any(tiles.count(t) >= 2 for t in present)
    return 13 - len(present) - (1 if has_pair else 0)


def _standard_bruteforce(tiles):
    hand = sorted(tiles)
    distinct_values = sorted(set(hand))
    eye_options = [None] + [v for v in distinct_values if hand.count(v) >= 2]

    best = None
    for eye in eye_options:
        remainder = list(hand)
        has_eye = 0
        if eye is not None:
            remainder.remove(eye)
            remainder.remove(eye)
            has_eye = 1
        for melds, partials in _search(tuple(remainder)):
            blocks_needed = STANDARD_MELDS_NEEDED - melds
            used_partials = partials if partials < blocks_needed else blocks_needed
            value = blocks_needed * 2 - used_partials - has_eye
            if best is None or value < best:
                best = value
    return best


@lru_cache(maxsize=None)
def _search(hand):
    """hand: sorted tuple of tiles remaining (eye already removed). Returns
    the set of (melds, partials) reachable by grouping the smallest tile in
    every possible way, then recursing on whatever's left."""
    if not hand:
        return frozenset({(0, 0)})

    first = hand[0]
    rest = list(hand[1:])
    outcomes = set()
    in_suit = first < 27
    rank_from_edge = first % 9  # 0-8; only meaningful for suited tiles

    def recurse(trimmed, meld_delta, partial_delta):
        for m, p in _search(tuple(trimmed)):
            outcomes.add((m + meld_delta, p + partial_delta))

    # complete triplet
    if rest.count(first) >= 2:
        trimmed = list(rest)
        trimmed.remove(first)
        trimmed.remove(first)
        recurse(trimmed, 1, 0)

    # complete run
    if in_suit and rank_from_edge <= 6 and (first + 1) in rest and (first + 2) in rest:
        trimmed = list(rest)
        trimmed.remove(first + 1)
        trimmed.remove(first + 2)
        recurse(trimmed, 1, 0)

    # partial: pair (proto-triplet)
    if first in rest:
        trimmed = list(rest)
        trimmed.remove(first)
        recurse(trimmed, 0, 1)

    # partial: two-tile proto-run
    if in_suit:
        if rank_from_edge <= 7 and (first + 1) in rest:
            trimmed = list(rest)
            trimmed.remove(first + 1)
            recurse(trimmed, 0, 1)
        if rank_from_edge <= 6 and (first + 2) in rest:
            trimmed = list(rest)
            trimmed.remove(first + 2)
            recurse(trimmed, 0, 1)

    # floater: leave `first` unused
    recurse(rest, 0, 0)

    return frozenset(outcomes)
