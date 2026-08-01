"""Tests for the fan (番) scorer (RULES.md section 4), assuming the hand
already passes mahjong.winning_hand.is_winning_hand.

Target API (not yet implemented):
    mahjong.scoring.score_hand(tiles: list[int], context: dict) -> dict
    -> {'fan': int, 'components': list[(name, fan)], 'is_limit': bool, 'valid': bool}

context spec (all keys optional, defaulting to "off"/0/False):
    seat_wind: int              tile code 27-30, player's seat wind
    round_wind: int             tile code 27-30, prevailing wind
    self_draw: bool             自摸
    concealed: bool             no calls made this hand (for 門前清, gated
                                 on win-by-discard: concealed AND not self_draw)
    own_flower_count: int       flowers/seasons matching the player's seat
    other_flower_count: int     flowers/seasons not matching the seat
    total_flower_type_count: int  0-4, how many of 梅蘭菊竹 are held (for 一台花)
    total_season_type_count: int  0-4, how many of 春夏秋冬 are held (for 一台花)
    won_by_kong_replacement: bool  槓上開花
    robbed_kong: bool              搶槓
    won_on_last_tile: bool         海底撈月
    kong_tiles: list[int]          tile values declared as kongs (for 十八羅漢)
    is_heavenly_hand: bool         天糊
    is_earthly_hand: bool          地糊

    NOTE on own_flower_count/other_flower_count: which flower/season index
    (34-41) belongs to which seat is NOT specified in RULES.md, so
    score_hand() never inspects raw flower tile codes -- the caller
    resolves ownership and passes pre-counted totals. TODO: the game
    engine will own the flower->seat mapping (flower/season 1-4 -> E/S/W/N)
    once it exists; scoring.py intentionally stays agnostic to it.
"""

from mahjong.scoring import score_hand


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

DEFAULT_CONTEXT = {
    "seat_wind": SOUTH,
    "round_wind": SOUTH,
    "self_draw": False,
    "concealed": False,
    "own_flower_count": 0,
    "other_flower_count": 0,
    "total_flower_type_count": 0,
    "total_season_type_count": 0,
    "won_by_kong_replacement": False,
    "robbed_kong": False,
    "won_on_last_tile": False,
    "kong_tiles": [],
    "is_heavenly_hand": False,
    "is_earthly_hand": False,
}


def ctx(**overrides):
    merged = dict(DEFAULT_CONTEXT)
    merged.update(overrides)
    return merged


def component_names(result):
    return [name for name, _ in result["components"]]


def component_fan(result, name_substring):
    return sum(fan for name, fan in result["components"] if name_substring in name)


# --- maximum-over-decompositions -------------------------------------------

class TestMaxOverDecompositions:
    def test_ambiguous_pung_or_chow_block_takes_the_higher_reading(self):
        # 111222333m can read as 3 pungs (-> 對對糊 applies alongside the
        # fixed 東東東 pung, all 4 melds pung) or as 3 identical chows
        # (-> neither all-chow nor all-pung, since East is still a pung).
        # The pung reading must win: 混一色(3) + 無花(1) + 對對糊(3) = 7,
        # vs. the chow reading's 混一色(3) + 無花(1) = 4.
        hand = [man(1), man(1), man(1),
                man(2), man(2), man(2),
                man(3), man(3), man(3),
                EAST, EAST, EAST,
                RED_DRAGON, RED_DRAGON]
        result = score_hand(hand, ctx())
        assert result["fan"] == 7
        assert "對對糊 All Pungs" in component_names(result)
        assert "平糊 All Chows" not in component_names(result)

    def test_all_chow_reading_is_correct_when_it_is_the_only_reading(self):
        # 123m 456m 789m 123p, pair 55s -- no pung reading exists at all
        # (every tile appears exactly once outside the pair), so this
        # must resolve to 平糊(1). Also exercises three suits present
        # (no flush bonus) and the min-fan gate landing False.
        # other_flower_count=1 suppresses 無花 so 平糊 is isolated.
        hand = [man(1), man(2), man(3),
                man(4), man(5), man(6),
                man(7), man(8), man(9),
                pin(1), pin(2), pin(3),
                sou(5), sou(5)]
        result = score_hand(hand, ctx(other_flower_count=1))
        assert result["fan"] == 1
        assert component_names(result) == ["平糊 All Chows"]
        assert result["valid"] is False  # 1 fan < 3-fan minimum


# --- stacking / mutual exclusion constraints --------------------------------

class TestStackingConstraints:
    def test_all_pungs_and_half_flush_stack_to_six(self):
        # 111m 222m 333m 東東東, pair 44m -- single suit (man) + honors
        # (East), all four melds pung.
        hand = [man(1), man(1), man(1),
                man(2), man(2), man(2),
                man(3), man(3), man(3),
                EAST, EAST, EAST,
                man(4), man(4)]
        result = score_hand(hand, ctx(other_flower_count=1))
        assert component_fan(result, "對對糊") == 3
        assert component_fan(result, "混一色") == 3
        assert result["fan"] == 6

    def test_full_flush_and_all_pungs_stack_to_ten(self):
        # 111m 222m 333m 444m, pair 55m -- single suit, no honors, all pungs.
        hand = [man(1), man(1), man(1),
                man(2), man(2), man(2),
                man(3), man(3), man(3),
                man(4), man(4), man(4),
                man(5), man(5)]
        result = score_hand(hand, ctx(other_flower_count=1))
        assert component_fan(result, "對對糊") == 3
        assert component_fan(result, "清一色") == 7
        assert result["fan"] == 10

    def test_full_flush_replaces_half_flush_never_both(self):
        # Single suit, no honors -> only 清一色 should appear, never 混一色.
        hand = [man(1), man(2), man(3),
                man(4), man(5), man(6),
                man(7), man(8), man(9),
                man(1), man(2), man(3),
                man(5), man(5)]
        result = score_hand(hand, ctx())
        names = component_names(result)
        assert "清一色 Full Flush" in names
        assert "混一色 Half Flush" not in names


# --- absorption of component fans by three/four dragons/winds --------------

class TestAbsorption:
    def test_great_three_dragons_absorbs_the_three_dragon_pungs(self):
        # 中中中 發發發 白白白 123m, pair 99s -- must score 大三元(8) only,
        # NOT 大三元(8) + 3x箭刻(1 each) = 11.
        hand = [RED_DRAGON, RED_DRAGON, RED_DRAGON,
                GREEN_DRAGON, GREEN_DRAGON, GREEN_DRAGON,
                WHITE_DRAGON, WHITE_DRAGON, WHITE_DRAGON,
                man(1), man(2), man(3),
                sou(9), sou(9)]
        result = score_hand(hand, ctx(other_flower_count=1))
        assert component_fan(result, "大三元") == 8
        assert component_fan(result, "箭刻") == 0
        assert result["fan"] == 8

    def test_small_three_dragons_absorbs_its_two_dragon_pungs(self):
        # 中中中 發發發 123m 456m, pair 白白 -- 小三元(5) absorbs the would-be
        # 2x箭刻(1 each), but this hand is also single-suit (man) + honors,
        # so 混一色(3) still stacks independently: 3 + 5 = 8.
        hand = [RED_DRAGON, RED_DRAGON, RED_DRAGON,
                GREEN_DRAGON, GREEN_DRAGON, GREEN_DRAGON,
                man(1), man(2), man(3),
                man(4), man(5), man(6),
                WHITE_DRAGON, WHITE_DRAGON]
        result = score_hand(hand, ctx(other_flower_count=1))
        assert component_fan(result, "小三元") == 5
        assert component_fan(result, "混一色") == 3
        assert component_fan(result, "箭刻") == 0
        assert result["fan"] == 8

    def test_dragon_pungs_without_three_or_pair_score_individually(self):
        # Only 2 dragon pungs, pair is NOT the third dragon -- no
        # small/great three dragons, just 2x箭刻(1 each) = 2.
        hand = [RED_DRAGON, RED_DRAGON, RED_DRAGON,
                GREEN_DRAGON, GREEN_DRAGON, GREEN_DRAGON,
                man(1), man(2), man(3),
                man(4), man(5), man(6),
                man(9), man(9)]
        result = score_hand(hand, ctx())
        assert component_fan(result, "箭刻") == 2
        assert component_fan(result, "大三元") == 0
        assert component_fan(result, "小三元") == 0

    def test_great_four_winds_absorbs_wind_fans_but_stacks_with_all_pungs(self):
        # 東東東 南南南 西西西 北北北, pair 99m -- 大四喜(10) absorbs the
        # component 門風/圈風 fans, but the hand is ALSO genuinely all
        # pungs, and 對對糊 is not one of the fans 大四喜 absorbs -- it
        # stacks on top: 10 + 3 = 13.
        hand = [EAST, EAST, EAST,
                SOUTH, SOUTH, SOUTH,
                WEST, WEST, WEST,
                NORTH, NORTH, NORTH,
                man(9), man(9)]
        result = score_hand(hand, ctx(seat_wind=EAST, round_wind=EAST))
        assert component_fan(result, "大四喜") == 10
        assert component_fan(result, "對對糊") == 3
        assert component_fan(result, "門風") == 0
        assert component_fan(result, "圈風") == 0
        assert result["fan"] == 13

    def test_small_four_winds_absorbs_its_three_wind_pungs(self):
        # 東東東 南南南 西西西 123m, pair 北北 -- 小四喜(8) absorbs the
        # would-be 門風/圈風, but this hand is also single-suit (man) +
        # honors, so 混一色(3) still stacks independently: 3 + 8 = 11.
        hand = [EAST, EAST, EAST,
                SOUTH, SOUTH, SOUTH,
                WEST, WEST, WEST,
                man(1), man(2), man(3),
                NORTH, NORTH]
        result = score_hand(hand, ctx(seat_wind=EAST, round_wind=EAST, other_flower_count=1))
        assert component_fan(result, "小四喜") == 8
        assert component_fan(result, "混一色") == 3
        assert component_fan(result, "門風") == 0
        assert component_fan(result, "圈風") == 0
        assert result["fan"] == 11

    def test_seat_wind_equal_to_round_wind_counts_twice(self):
        # A single East pung, with seat_wind == round_wind == East, counts
        # as both 門風(1) and 圈風(1) per RULES.md's explicit note.
        hand = [EAST, EAST, EAST,
                man(1), man(2), man(3),
                man(4), man(5), man(6),
                man(7), man(8), man(9),
                man(9), man(9)]
        result = score_hand(hand, ctx(seat_wind=EAST, round_wind=EAST))
        assert component_fan(result, "門風") == 1
        assert component_fan(result, "圈風") == 1


# --- individual 1-2 fan components ------------------------------------------

class TestIndividualComponents:
    def test_self_draw_adds_one_fan(self):
        hand = [man(1), man(2), man(3),
                man(4), man(5), man(6),
                man(7), man(8), man(9),
                pin(1), pin(2), pin(3),
                sou(5), sou(5)]
        result = score_hand(hand, ctx(self_draw=True))
        assert component_fan(result, "自摸") == 1

    def test_concealed_discard_win_adds_one_fan(self):
        hand = [man(1), man(2), man(3),
                man(4), man(5), man(6),
                man(7), man(8), man(9),
                pin(1), pin(2), pin(3),
                sou(5), sou(5)]
        result = score_hand(hand, ctx(self_draw=False, concealed=True))
        assert component_fan(result, "門前清") == 1

    def test_concealed_self_draw_does_not_double_count_menzen(self):
        # 門前清 is explicitly "win by discard, no calls" -- a concealed
        # self-draw gets 自摸 only, not 自摸 + 門前清.
        hand = [man(1), man(2), man(3),
                man(4), man(5), man(6),
                man(7), man(8), man(9),
                pin(1), pin(2), pin(3),
                sou(5), sou(5)]
        result = score_hand(hand, ctx(self_draw=True, concealed=True))
        assert component_fan(result, "自摸") == 1
        assert component_fan(result, "門前清") == 0

    def test_no_flowers_adds_one_fan(self):
        hand = [man(1), man(2), man(3),
                man(4), man(5), man(6),
                man(7), man(8), man(9),
                pin(1), pin(2), pin(3),
                sou(5), sou(5)]
        result = score_hand(hand, ctx(own_flower_count=0, other_flower_count=0))
        assert component_fan(result, "無花") == 1

    def test_own_flowers_score_one_fan_each_and_suppress_no_flowers(self):
        hand = [man(1), man(2), man(3),
                man(4), man(5), man(6),
                man(7), man(8), man(9),
                pin(1), pin(2), pin(3),
                sou(5), sou(5)]
        result = score_hand(hand, ctx(own_flower_count=2, other_flower_count=1))
        assert component_fan(result, "花") == 2
        assert component_fan(result, "無花") == 0

    def test_all_honors_scores_ten_and_stacks_with_all_pungs(self):
        # Every tile is an honor -- 字一色(10) plus 對對糊(3) (honors can
        # only pung, never chow, so an all-honor hand is automatically
        # all-pungs too); capped at 13.
        hand = [EAST, EAST, EAST,
                SOUTH, SOUTH, SOUTH,
                WEST, WEST, WEST,
                RED_DRAGON, RED_DRAGON, RED_DRAGON,
                NORTH, NORTH]
        result = score_hand(hand, ctx(seat_wind=SOUTH, round_wind=SOUTH))
        assert component_fan(result, "字一色") == 10
        assert component_fan(result, "對對糊") == 3
        assert result["fan"] == 13  # capped from 13 (already exactly at cap)

    def test_full_set_of_four_seasons_adds_two_fan(self):
        hand = [man(1), man(2), man(3),
                man(4), man(5), man(6),
                man(7), man(8), man(9),
                pin(1), pin(2), pin(3),
                sou(5), sou(5)]
        result = score_hand(hand, ctx(total_season_type_count=4))
        assert component_fan(result, "一台花") == 2

    def test_kong_replacement_robbing_kong_last_tile_each_add_one_fan(self):
        hand = [man(1), man(2), man(3),
                man(4), man(5), man(6),
                man(7), man(8), man(9),
                pin(1), pin(2), pin(3),
                sou(5), sou(5)]
        result = score_hand(hand, ctx(won_by_kong_replacement=True))
        assert component_fan(result, "槓上開花") == 1

        result = score_hand(hand, ctx(robbed_kong=True))
        assert component_fan(result, "搶槓") == 1

        result = score_hand(hand, ctx(won_on_last_tile=True))
        assert component_fan(result, "海底撈月") == 1


# --- limit hands -------------------------------------------------------------

class TestLimitHands:
    def test_thirteen_orphans_is_a_limit_hand(self):
        hand = ORPHAN_TILES + [man(1)]
        result = score_hand(hand, ctx(self_draw=True))  # extra context should not matter
        assert result["is_limit"] is True
        assert result["fan"] == 13
        assert result["valid"] is True

    def test_all_kongs_is_a_limit_hand(self):
        # Four declared kongs (man1, man2, man3, East), represented in the
        # 14-tile structure as pung-equivalents, plus a pair.
        hand = [man(1), man(1), man(1),
                man(2), man(2), man(2),
                man(3), man(3), man(3),
                EAST, EAST, EAST,
                sou(9), sou(9)]
        result = score_hand(hand, ctx(kong_tiles=[man(1), man(2), man(3), EAST]))
        assert result["is_limit"] is True
        assert result["fan"] == 13

    def test_heavenly_hand_is_a_limit_hand(self):
        hand = [man(1), man(2), man(3),
                man(4), man(5), man(6),
                man(7), man(8), man(9),
                pin(1), pin(2), pin(3),
                sou(5), sou(5)]
        result = score_hand(hand, ctx(is_heavenly_hand=True))
        assert result["is_limit"] is True
        assert result["fan"] == 13

    def test_earthly_hand_is_a_limit_hand(self):
        hand = [man(1), man(2), man(3),
                man(4), man(5), man(6),
                man(7), man(8), man(9),
                pin(1), pin(2), pin(3),
                sou(5), sou(5)]
        result = score_hand(hand, ctx(is_earthly_hand=True))
        assert result["is_limit"] is True
        assert result["fan"] == 13

    def test_limit_hand_ignores_other_component_fan_in_total(self):
        # A limit hand still caps at 13 even stacked with things that would
        # otherwise push the "normal" total past 13 on their own.
        hand = ORPHAN_TILES + [man(9)]
        result = score_hand(hand, ctx(self_draw=True, own_flower_count=5))
        assert result["fan"] == 13
        assert result["is_limit"] is True


# --- min-fan gate and cap ----------------------------------------------------

class TestMinFanGateAndCap:
    def test_valid_false_below_minimum_but_fan_still_reported_truthfully(self):
        # 平糊 alone is 1 fan -- below the 3-fan minimum. `valid` must be
        # False, but `fan` must still read 1, not be floored to 0.
        hand = [man(1), man(2), man(3),
                man(4), man(5), man(6),
                man(7), man(8), man(9),
                pin(1), pin(2), pin(3),
                sou(5), sou(5)]
        result = score_hand(hand, ctx(other_flower_count=1))
        assert result["fan"] == 1
        assert result["valid"] is False

    def test_valid_true_at_or_above_minimum(self):
        # 混一色(3) alone reaches exactly the 3-fan minimum.
        hand = [man(1), man(2), man(3),
                man(4), man(5), man(6),
                man(7), man(8), man(9),
                EAST, EAST, EAST,
                man(9), man(9)]
        result = score_hand(hand, ctx(other_flower_count=1))
        assert result["fan"] == 3
        assert result["valid"] is True

    def test_total_fan_is_capped_at_thirteen(self):
        # 清一色(7) + 對對糊(3) + 自摸(1) + 3 own flowers(3) + 海底撈月(1)
        # = 15 uncapped -> must report 13.
        hand = [man(1), man(1), man(1),
                man(2), man(2), man(2),
                man(3), man(3), man(3),
                man(4), man(4), man(4),
                man(5), man(5)]
        result = score_hand(hand, ctx(
            self_draw=True, own_flower_count=3, won_on_last_tile=True,
        ))
        assert result["fan"] == 13
        assert result["valid"] is True
