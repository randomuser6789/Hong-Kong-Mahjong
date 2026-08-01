"""Cross-checks mahjong.shanten.shanten() against the independent brute
force in mahjong.shanten_bruteforce (see that module's docstring for how
it's implemented differently -- no shared helpers, no shared imports).
"""

import random

from mahjong.shanten import shanten
from mahjong.shanten_bruteforce import shanten_bruteforce

RANDOM_HAND_SEED = 1
RANDOM_HAND_COUNT = 5000

EAST, SOUTH, WEST, NORTH = 27, 28, 29, 30


def man(n):
    return n - 1


def pin(n):
    return 9 + n - 1


def sou(n):
    return 18 + n - 1


def _random_legal_hand(rng):
    counts = [0] * 34
    hand = []
    while len(hand) < 13:
        tile = rng.randrange(34)
        if counts[tile] < 4:
            counts[tile] += 1
            hand.append(tile)
    return hand


def test_shanten_matches_bruteforce_on_random_hands():
    rng = random.Random(RANDOM_HAND_SEED)
    mismatches = []
    for _ in range(RANDOM_HAND_COUNT):
        hand = _random_legal_hand(rng)
        fast = shanten(hand)
        brute = shanten_bruteforce(hand)
        if fast != brute:
            mismatches.append((sorted(hand), fast, brute))

    if mismatches:
        print(f"{len(mismatches)} mismatch(es) out of {RANDOM_HAND_COUNT} random hands:")
        for hand, fast, brute in mismatches:
            print(f"  hand={hand} shanten()={fast} shanten_bruteforce()={brute}")
    assert mismatches == []


# Hand-picked hands with high standard-form shanten (>=5), found by sampling
# random legal hands with a fixed seed and keeping the ones shanten() rated
# >=5 (fast shanten only used here to pick interesting hands to probe;
# the actual pass/fail assertion below is fast vs. brute force, so this
# isn't circular). Each is independently re-verified against the brute
# force with no depth cap.
HIGH_SHANTEN_HANDS = [
    # The adversarial "all gaps of 3, no adjacency, no honors pair"
    # hand from test_shanten.py::test_worst_case_all_isolated_gapped_tiles.
    [man(2), man(5), man(8), pin(2), pin(5), pin(8), sou(2), sou(5), sou(8), EAST, SOUTH, WEST, NORTH],
    [0, 0, 7, 7, 10, 16, 16, 17, 18, 21, 27, 29, 33],
    [8, 10, 12, 13, 16, 19, 23, 25, 27, 28, 30, 33, 33],
    [4, 6, 8, 11, 12, 12, 15, 15, 17, 21, 27, 28, 29],
    [0, 4, 8, 10, 15, 16, 18, 19, 22, 23, 28, 32, 33],
    [0, 2, 3, 5, 8, 10, 16, 16, 17, 21, 27, 31, 32],
    [8, 10, 15, 16, 20, 27, 28, 28, 28, 29, 30, 32, 33],
    [1, 1, 8, 10, 14, 17, 21, 24, 25, 25, 27, 29, 31],
    [1, 5, 11, 15, 15, 17, 20, 21, 24, 28, 29, 31, 31],
    [3, 4, 4, 7, 11, 16, 21, 25, 28, 30, 30, 30, 31],
    [2, 5, 7, 17, 19, 20, 25, 27, 28, 28, 29, 31, 32],
    [3, 3, 8, 12, 13, 17, 18, 23, 26, 28, 28, 31, 33],
    [2, 6, 6, 8, 9, 20, 21, 24, 24, 28, 30, 31, 32],
    [0, 4, 10, 16, 16, 18, 19, 19, 22, 27, 28, 29, 29],
    [4, 7, 9, 10, 14, 16, 17, 18, 21, 23, 25, 29, 30],
    [2, 4, 6, 14, 19, 23, 28, 28, 29, 30, 32, 32, 33],
    [1, 3, 4, 4, 5, 6, 9, 20, 25, 27, 28, 30, 31],
    [3, 6, 9, 13, 14, 18, 19, 22, 22, 26, 27, 30, 32],
    [0, 2, 3, 8, 13, 13, 14, 18, 19, 19, 25, 31, 33],
    [1, 5, 6, 10, 15, 20, 23, 25, 25, 27, 27, 29, 33],
]


def test_high_shanten_hands_are_at_least_five_and_match_bruteforce():
    assert len(HIGH_SHANTEN_HANDS) == 20
    for hand in HIGH_SHANTEN_HANDS:
        assert len(hand) == 13
        fast = shanten(hand)
        brute = shanten_bruteforce(hand)
        assert fast == brute, (
            f"mismatch on {sorted(hand)}: shanten()={fast} shanten_bruteforce()={brute}"
        )
        assert fast >= 5, f"expected shanten >= 5 on {sorted(hand)}, got {fast}"
