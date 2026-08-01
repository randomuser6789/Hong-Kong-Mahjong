"""Shanten calculator per RULES.md section 2.

# shanten = tiles away from 叫糊 (ready); -1 = 食糊 (won), 0 = 叫糊 (ready/聽牌)

`shanten()` accepts a 13-tile hand, or a 14-tile hand (13 + a just-drawn
tile) -- a complete 14-tile hand naturally resolves to -1 through the same
formula used for every other case, so no separate "is it a win" branch is
needed.

Standard-form shanten, for one candidate decomposition:
    shanten = (4 - melds) * 2 - min(partials, 4 - melds) - has_pair
  - melds: complete sets (pung or chow).
  - partials: partial sets (a pair used as a proto-triplet, or a two-tile
    proto-run) found after the eye is set aside. Capped at (4 - melds)
    since a partial is useless once all 4 meld slots are already covered.
  - has_pair: 1 if a pair was reserved as the eye (眼), else 0.
  The reported standard shanten is the minimum of this value over every
  choice of eye and every way to split the rest into melds/partials/floaters.

Thirteen-orphans shanten:
    shanten = 13 - (unique required tiles present) - (1 if any is paired else 0)

Overall shanten = min(standard, thirteen orphans) -- seven pairs (七對子)
is not a valid structure in this ruleset (RULES.md section 2), so it is not
considered here.
"""

from functools import lru_cache

NUM_TILE_TYPES = 34
STANDARD_MELDS_NEEDED = 4

THIRTEEN_ORPHAN_TILES = frozenset({
    0, 8,       # man 1, man 9
    9, 17,      # pin 1, pin 9
    18, 26,     # sou 1, sou 9
    27, 28, 29, 30,   # winds
    31, 32, 33,       # dragons
})


def shanten(tiles):
    if len(tiles) not in (13, 14):
        raise ValueError("shanten() expects 13 tiles, or 14 including a just-drawn tile")
    return min(_standard_shanten(tiles), _thirteen_orphans_shanten(tiles))


def _thirteen_orphans_shanten(tiles):
    counts = _counts_tuple(tiles)
    present = [t for t in THIRTEEN_ORPHAN_TILES if counts[t] > 0]
    has_pair = any(counts[t] >= 2 for t in present)
    return 13 - len(present) - (1 if has_pair else 0)


def _standard_shanten(tiles):
    counts = list(_counts_tuple(tiles))
    tile_types = [t for t in range(NUM_TILE_TYPES) if counts[t] > 0]
    head_candidates = [None] + [t for t in tile_types if counts[t] >= 2]

    best = None
    for head in head_candidates:
        has_pair = 0
        if head is not None:
            counts[head] -= 2
            has_pair = 1
        for melds, partials in _decompose(tuple(counts)):
            blocks_needed = STANDARD_MELDS_NEEDED - melds
            used_partials = min(partials, blocks_needed)
            candidate = blocks_needed * 2 - used_partials - has_pair
            if best is None or candidate < best:
                best = candidate
        if head is not None:
            counts[head] += 2
    return best


@lru_cache(maxsize=None)
def _decompose(counts):
    """All (melds, partials) counts achievable from a tile-count tuple by
    trying, at the lowest remaining tile, every way to consume it: as part
    of a complete meld, as part of a partial meld, or as an unused floater.
    """
    counts = list(counts)
    tile = next((t for t in range(NUM_TILE_TYPES) if counts[t] > 0), None)
    if tile is None:
        return frozenset({(0, 0)})

    is_honor = tile >= 27
    pos = tile % 9  # position within suit, 0-8 (only meaningful if not honor)
    results = set()

    def branch(deltas, meld_delta, partial_delta):
        for i, d in deltas:
            counts[i] -= d
        for m, p in _decompose(tuple(counts)):
            results.add((m + meld_delta, p + partial_delta))
        for i, d in deltas:
            counts[i] += d

    if counts[tile] >= 3:
        branch([(tile, 3)], 1, 0)

    if not is_honor and pos <= 6 and counts[tile + 1] > 0 and counts[tile + 2] > 0:
        branch([(tile, 1), (tile + 1, 1), (tile + 2, 1)], 1, 0)

    if counts[tile] >= 2:
        branch([(tile, 2)], 0, 1)

    if not is_honor:
        if pos <= 7 and counts[tile + 1] > 0:
            branch([(tile, 1), (tile + 1, 1)], 0, 1)
        if pos <= 6 and counts[tile + 2] > 0:
            branch([(tile, 1), (tile + 2, 1)], 0, 1)

    branch([(tile, 1)], 0, 0)  # leave as an unused floater

    return frozenset(results)


def _counts_tuple(tiles):
    counts = [0] * NUM_TILE_TYPES
    for t in tiles:
        counts[t] += 1
    return tuple(counts)
