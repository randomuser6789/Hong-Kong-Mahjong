"""Tests for the shanten calculator (RULES.md section 2).

# shanten = tiles away from 叫糊 (ready); -1 = 食糊 (won), 0 = 叫糊 (ready/聽牌)

Target API (not yet implemented):
    mahjong.shanten.shanten(tiles: list[int]) -> int

`tiles` is a 13-tile hand (or 14 tiles = 13 + the tile just drawn, in which
case a complete hand naturally resolves to -1 through the same formula).
Tile encoding matches RULES.md section 1 (see test_winning_hand.py for the
full table); reused here via the same man()/pin()/sou() helpers.

Standard-form shanten formula (applied per candidate decomposition):
    shanten = (4 - melds) * 2 - min(partials, 4 - melds) - has_pair
  - melds: complete sets (pung or chow) found in the decomposition.
  - partials: partial sets (a pair used as a proto-triplet, or a two-tile
    proto-run) found in what's left after the pair/eye is set aside.
    Capped at (4 - melds) because a partial can't help once all 4 meld
    slots are already spoken for.
  - has_pair: 1 if a pair was set aside as the eye (眼), else 0.
  The true shanten is the minimum of this value over every way to choose
  the eye and decompose the rest (melds vs. partials vs. floaters).

Thirteen-orphans shanten formula:
    shanten = 13 - (unique required tiles present) - (1 if any of them is
    paired, else 0)

Overall shanten = min(standard shanten, thirteen-orphans shanten), since
seven pairs (七對子) is not a valid structure in this ruleset.
"""

from mahjong.shanten import shanten


def man(n):
    return n - 1


def pin(n):
    return 9 + n - 1


def sou(n):
    return 18 + n - 1


EAST, SOUTH, WEST, NORTH = 27, 28, 29, 30
RED_DRAGON, GREEN_DRAGON, WHITE_DRAGON = 31, 32, 33

ORPHAN_TILES = [
    man(1), man(9), pin(1), pin(9), sou(1), sou(9),
    EAST, SOUTH, WEST, NORTH,
    RED_DRAGON, GREEN_DRAGON, WHITE_DRAGON,
]


class TestCompleteHand:
    def test_complete_standard_hand_is_won(self):
        # 123m 456m 789m 123p, pair 55s -- a full 4 melds + pair using all
        # 14 tiles. melds=4, has_pair=1, partials=0 (nothing left over):
        # shanten = (4-4)*2 - min(0,0) - 1 = -1 (食糊).
        hand = [man(1), man(2), man(3),
                man(4), man(5), man(6),
                man(7), man(8), man(9),
                pin(1), pin(2), pin(3),
                sou(5), sou(5)]
        assert shanten(hand) == -1

    def test_complete_thirteen_orphans_is_won(self):
        # All 13 required tiles plus a duplicate of one -- unique=13,
        # has_pair=1: kokushi shanten = 13 - 13 - 1 = -1 (食糊).
        hand = ORPHAN_TILES + [man(1)]
        assert shanten(hand) == -1


class TestTenpai:
    def test_tanki_wait_is_ready(self):
        # 123m 456m 789m 123p + lone 5p (13 tiles): 4 complete melds
        # already, no pair yet -- one more 5p completes the eye.
        # melds=4, partials=0, has_pair=0: shanten = 0*2 - 0 - 0 = 0.
        hand = [man(1), man(2), man(3),
                man(4), man(5), man(6),
                man(7), man(8), man(9),
                pin(1), pin(2), pin(3),
                pin(5)]
        assert shanten(hand) == 0

    def test_thirteen_orphans_one_type_missing_is_ready(self):
        # 12 of the 13 required types plus a duplicate of one of them
        # (13 tiles): unique=12, has_pair=1.
        # kokushi shanten = 13 - 12 - 1 = 0 (waiting on the missing type).
        hand = ORPHAN_TILES[:-1] + [man(1)]
        assert len(hand) == 13
        assert shanten(hand) == 0

    def test_thirteen_orphans_all_types_no_pair_is_ready(self):
        # All 13 required types, no duplicate yet (13 tiles): unique=13,
        # has_pair=0. kokushi shanten = 13 - 13 - 0 = 0
        # (the famous 13-sided wait -- any of the 13 types completes it).
        hand = list(ORPHAN_TILES)
        assert len(hand) == 13
        assert shanten(hand) == 0


class TestOneAway:
    def test_one_shanten_needs_a_pair_to_form(self):
        # 123m 456m 789m + pair 11p + lone 5p + lone 8s (13 tiles): 3
        # complete melds + the eye are already set, but the two leftover
        # singles (5p, 8s) share no suit/adjacency, so there's no partial
        # for the 4th meld yet -- one useful draw (e.g. 4p/6p) creates a
        # partial and reaches tenpai.
        # melds=3, has_pair=1, partials=0: shanten=(4-3)*2 - 0 - 1 = 1.
        hand = [man(1), man(2), man(3),
                man(4), man(5), man(6),
                man(7), man(8), man(9),
                pin(1), pin(1),
                pin(5), sou(8)]
        assert shanten(hand) == 1


class TestKnownValues:
    def test_two_shanten_with_kanchan_pair_and_isolated_honors(self):
        # 123m 456m (2 melds) + 13p kanchan (partial) + pair 99s (eye) +
        # East South West as isolated singles (honors never form runs, and
        # there's no second East/South/West to pair with, so they're pure
        # floaters contributing nothing).
        # melds=2, has_pair=1, partials=1 (13p kanchan, capped at 4-2=2):
        # shanten = (4-2)*2 - min(1,2) - 1 = 4 - 1 - 1 = 2.
        hand = [man(1), man(2), man(3),
                man(4), man(5), man(6),
                pin(1), pin(3),
                sou(9), sou(9),
                EAST, SOUTH, WEST]
        assert shanten(hand) == 2

    def test_worst_case_all_isolated_gapped_tiles(self):
        # man/pin/sou 2,5,8 (gaps of 3 -- no run/kanchan possible, no
        # pairs) plus all 4 winds as singles.
        # Standard: melds=0, partials=0, has_pair=0:
        #   shanten = (4-0)*2 - 0 - 0 = 8.
        # Kokushi: only the 4 winds count as required-type tiles present,
        # none paired: shanten = 13 - 4 - 0 = 9.
        # Overall shanten = min(8, 9) = 8.
        hand = [man(2), man(5), man(8),
                pin(2), pin(5), pin(8),
                sou(2), sou(5), sou(8),
                EAST, SOUTH, WEST, NORTH]
        assert len(hand) == 13
        assert shanten(hand) == 8
