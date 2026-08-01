"""Winning-hand checker per RULES.md section 2."""

from collections import Counter

NUM_HAND_TILES = 14
MAX_TILE_CODE = 33  # honors end at 33; 34+ are bonus/flower tiles

THIRTEEN_ORPHAN_TILES = frozenset({
    0, 8,       # man 1, man 9
    9, 17,      # pin 1, pin 9
    18, 26,     # sou 1, sou 9
    27, 28, 29, 30,   # winds
    31, 32, 33,       # dragons
})


def is_winning_hand(tiles):
    if not _is_valid_tile_multiset(tiles):
        return False
    if _is_thirteen_orphans(tiles):
        return True
    return _is_standard_winning_hand(tiles)


def _is_valid_tile_multiset(tiles):
    if len(tiles) != NUM_HAND_TILES:
        return False
    if any(not (0 <= t <= MAX_TILE_CODE) for t in tiles):
        return False
    counts = Counter(tiles)
    if any(count > 4 for count in counts.values()):
        return False
    return True


def _is_thirteen_orphans(tiles):
    if set(tiles) != THIRTEEN_ORPHAN_TILES:
        return False
    counts = Counter(tiles)
    return sorted(counts.values()) == [1] * 12 + [2]


def _is_standard_winning_hand(tiles):
    counts = Counter(tiles)
    for pair_tile in list(counts):
        if counts[pair_tile] < 2:
            continue
        counts[pair_tile] -= 2
        if _can_decompose_into_melds(counts):
            counts[pair_tile] += 2
            return True
        counts[pair_tile] += 2
    return False


def _can_decompose_into_melds(counts):
    tile = next((t for t in sorted(counts) if counts[t] > 0), None)
    if tile is None:
        return True

    if counts[tile] >= 3:
        counts[tile] -= 3
        if _can_decompose_into_melds(counts):
            counts[tile] += 3
            return True
        counts[tile] += 3

    is_honor = tile >= 27
    position_in_suit = tile % 9
    if not is_honor and position_in_suit <= 6:
        second, third = tile + 1, tile + 2
        if counts.get(second, 0) > 0 and counts.get(third, 0) > 0:
            counts[tile] -= 1
            counts[second] -= 1
            counts[third] -= 1
            if _can_decompose_into_melds(counts):
                counts[tile] += 1
                counts[second] += 1
                counts[third] += 1
                return True
            counts[tile] += 1
            counts[second] += 1
            counts[third] += 1

    return False
