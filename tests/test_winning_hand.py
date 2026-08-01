"""Tests for the winning-hand checker (RULES.md section 2).

Target API (not yet implemented):
    mahjong.winning_hand.is_winning_hand(tiles: list[int]) -> bool

`tiles` is a flat list of 14 tile codes using the encoding from RULES.md
section 1:
    0-8   man (萬) 1-9
    9-17  pin (筒) 1-9
    18-26 sou (索) 1-9
    27-30 winds 東南西北
    31-33 dragons 中發白
    34-41 flowers/seasons (bonus tiles -- never part of the 14-tile hand)

A hand is winning iff it decomposes into 4 melds + 1 pair (chows/pungs only,
honors cannot form chows) OR matches the thirteen orphans special hand.
Seven pairs is explicitly NOT a valid structure in this ruleset.
"""

import pytest

from mahjong.winning_hand import is_winning_hand

# --- tile helpers, matching RULES.md section 1 encoding -------------------

def man(n):
    return n - 1

def pin(n):
    return 9 + n - 1

def sou(n):
    return 18 + n - 1

EAST, SOUTH, WEST, NORTH = 27, 28, 29, 30
RED_DRAGON, GREEN_DRAGON, WHITE_DRAGON = 31, 32, 33
FLOWER_PLUM = 34  # any bonus tile code; not part of a 14-tile hand

ORPHAN_TILES = [
    man(1), man(9), pin(1), pin(9), sou(1), sou(9),
    EAST, SOUTH, WEST, NORTH,
    RED_DRAGON, GREEN_DRAGON, WHITE_DRAGON,
]


# --- standard 4 melds + 1 pair ---------------------------------------------

class TestStandardHands:
    def test_all_chows_with_number_pair(self):
        # 123m 456m 789m 123p, pair 55s
        hand = [man(1), man(2), man(3),
                man(4), man(5), man(6),
                man(7), man(8), man(9),
                pin(1), pin(2), pin(3),
                sou(5), sou(5)]
        assert is_winning_hand(hand) is True

    def test_all_pungs_with_number_pair(self):
        # 111m 222m 333p 444s, pair 55p (對對糊 shape)
        hand = [man(1), man(1), man(1),
                man(2), man(2), man(2),
                pin(3), pin(3), pin(3),
                sou(4), sou(4), sou(4),
                pin(5), pin(5)]
        assert is_winning_hand(hand) is True

    def test_honor_pungs_with_chows_and_number_pair(self):
        # 中中中 東東東 123m 456p, pair 99s
        hand = [RED_DRAGON, RED_DRAGON, RED_DRAGON,
                EAST, EAST, EAST,
                man(1), man(2), man(3),
                pin(4), pin(5), pin(6),
                sou(9), sou(9)]
        assert is_winning_hand(hand) is True

    def test_all_chows_with_honor_pair(self):
        # pair 發發, chows 123p 123s 456s 789s
        hand = [GREEN_DRAGON, GREEN_DRAGON,
                pin(1), pin(2), pin(3),
                sou(1), sou(2), sou(3),
                sou(4), sou(5), sou(6),
                sou(7), sou(8), sou(9)]
        assert is_winning_hand(hand) is True

    def test_mixed_pungs_and_chows(self):
        # 111m 234p 567s 999s, pair 88m
        hand = [man(1), man(1), man(1),
                pin(2), pin(3), pin(4),
                sou(5), sou(6), sou(7),
                sou(9), sou(9), sou(9),
                man(8), man(8)]
        assert is_winning_hand(hand) is True

    def test_ambiguous_pung_or_chow_block_is_winning(self):
        # 111222333m reads as three pungs (111,222,333) OR three identical
        # chows (123,123,123) -- either reading is valid, so with 456m and
        # pair 44m this must be recognized as winning regardless of which
        # decomposition the checker happens to find first.
        hand = [man(1), man(1), man(1),
                man(2), man(2), man(2),
                man(3), man(3), man(3),
                man(4), man(5), man(6),
                man(4), man(4)]
        assert is_winning_hand(hand) is True


# --- thirteen orphans (十三么) ----------------------------------------------

class TestThirteenOrphans:
    @pytest.mark.parametrize("dup_tile", ORPHAN_TILES)
    def test_valid_orphans_with_any_duplicate(self, dup_tile):
        hand = ORPHAN_TILES + [dup_tile]
        assert len(hand) == 14
        assert is_winning_hand(hand) is True

    def test_orphans_missing_one_required_tile_is_not_winning(self):
        # White dragon swapped out for an unrelated simple tile (man2).
        hand = ORPHAN_TILES[:-1] + [man(2), man(1)]
        assert len(hand) == 14
        assert is_winning_hand(hand) is False

    def test_orphans_shape_but_duplicate_outside_the_set_is_not_winning(self):
        # 12 of the 13 required orphan tiles (white dragon dropped) plus an
        # unrelated simple tile as the 14th -- not orphans, not standard.
        hand = [t for t in ORPHAN_TILES if t != WHITE_DRAGON] + [man(5)]
        assert len(hand) == 13
        hand.append(man(5))
        assert len(hand) == 14
        assert is_winning_hand(hand) is False


# --- clear non-winning hands ------------------------------------------------

class TestNonWinningHands:
    def test_random_scattered_tiles(self):
        hand = [man(1), man(4), man(7),
                pin(2), pin(5), pin(8),
                sou(1), sou(4), sou(9),
                EAST, SOUTH, WEST, NORTH,
                RED_DRAGON]
        assert len(hand) == 14
        assert is_winning_hand(hand) is False

    def test_wrong_tile_count_thirteen(self):
        hand = [man(1), man(2), man(3),
                man(4), man(5), man(6),
                man(7), man(8), man(9),
                pin(1), pin(2), pin(3),
                sou(5)]
        assert len(hand) == 13
        assert is_winning_hand(hand) is False

    def test_wrong_tile_count_fifteen(self):
        hand = [man(1), man(2), man(3),
                man(4), man(5), man(6),
                man(7), man(8), man(9),
                pin(1), pin(2), pin(3),
                sou(5), sou(5), sou(6)]
        assert len(hand) == 15
        assert is_winning_hand(hand) is False

    def test_honor_tiles_cannot_form_a_sequence(self):
        # East-South-West "run" is not a legal meld (honors can't sequence),
        # even though the rest of the hand is a clean 3 chows + pair.
        hand = [EAST, SOUTH, WEST,
                man(1), man(2), man(3),
                man(4), man(5), man(6),
                man(7), man(8), man(9),
                pin(1), pin(1)]
        assert len(hand) == 14
        assert is_winning_hand(hand) is False

    def test_five_of_a_kind_violates_tile_count_invariant(self):
        # Arithmetically "5 = pung + pair" of the same tile, but a real hand
        # can never hold 5 copies of one tile (section 8 invariant).
        hand = [man(1), man(1), man(1), man(1), man(1),
                man(2), man(2), man(2),
                man(3), man(3), man(3),
                man(4), man(4), man(4)]
        assert len(hand) == 14
        assert is_winning_hand(hand) is False

    def test_flower_tile_in_hand_breaks_structure(self):
        # Flowers/seasons are bonus tiles set aside, not part of the 14-tile
        # structure -- one leaking into the hand should never count as a win.
        hand = [man(1), man(2), man(3),
                man(4), man(5), man(6),
                man(7), man(8), man(9),
                pin(1), pin(2), pin(3),
                sou(5), FLOWER_PLUM]
        assert len(hand) == 14
        assert is_winning_hand(hand) is False

    def test_seven_pairs_is_explicitly_not_valid(self):
        # RULES.md section 2: 七對子 (seven pairs) is excluded in this
        # ruleset. Pairs are non-consecutive/non-triplet-able so there is no
        # alternate 4-melds+pair or orphans reading either.
        hand = [man(1), man(1), man(3), man(3), man(5), man(5),
                man(7), man(7), man(9), man(9),
                RED_DRAGON, RED_DRAGON, GREEN_DRAGON, GREEN_DRAGON]
        assert len(hand) == 14
        assert is_winning_hand(hand) is False

    def test_one_tile_away_is_not_winning(self):
        # 3 complete chows + pair + a broken two-tile shape (12p, missing
        # the 3p) plus an unrelated filler tile -- classic tenpai, not a win.
        hand = [man(1), man(2), man(3),
                man(4), man(5), man(6),
                man(7), man(8), man(9),
                pin(1), pin(2),
                sou(5), sou(5),
                sou(9)]
        assert len(hand) == 14
        assert is_winning_hand(hand) is False
