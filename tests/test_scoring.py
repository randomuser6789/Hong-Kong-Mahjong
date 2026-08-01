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

import random

from mahjong.scoring import score_hand


def man(n):
    return n - 1


def pin(n):
    return 9 + n - 1


def sou(n):
    return 18 + n - 1


EAST, SOUTH, WEST, NORTH = 27, 28, 29, 30
RED_DRAGON, GREEN_DRAGON, WHITE_DRAGON = 31, 32, 33

FAN_CAP = 13
MINIMUM_FAN = 3

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


def assert_exact_components(result, expected):
    key = lambda c: (c[0], c[1])
    assert sorted(result["components"], key=key) == sorted(expected, key=key)


# --- random legal-hand generator, for the property test --------------------

def _random_meld(rng, counts):
    """Pick one random legal meld (pung or chow) given tile counts already
    committed elsewhere in the hand, and commit it into `counts`. Retries
    with fresh random choices until one fits within the 4-copies cap."""
    for _ in range(200):
        if rng.random() < 0.5:
            tile = rng.randrange(34)
            if counts[tile] <= 1:  # room for 3 more, cap 4
                counts[tile] += 3
                return [tile, tile, tile]
        else:
            suit_start = rng.choice([0, 9, 18])
            tile = suit_start + rng.randrange(7)  # rank 1-7 so tile+2 stays in suit
            if counts[tile] <= 3 and counts[tile + 1] <= 3 and counts[tile + 2] <= 3:
                counts[tile] += 1
                counts[tile + 1] += 1
                counts[tile + 2] += 1
                return [tile, tile + 1, tile + 2]
    raise RuntimeError("could not place a random meld after many attempts")


def _random_pair(rng, counts):
    for _ in range(200):
        tile = rng.randrange(34)
        if counts[tile] <= 2:
            counts[tile] += 2
            return [tile, tile]
    raise RuntimeError("could not place a random pair after many attempts")


def _random_winning_hand(rng):
    counts = [0] * 34
    hand = []
    for _ in range(4):
        hand.extend(_random_meld(rng, counts))
    hand.extend(_random_pair(rng, counts))
    return hand


def _random_context(rng):
    wind = rng.choice([EAST, SOUTH, WEST, NORTH])
    return ctx(
        seat_wind=rng.choice([EAST, SOUTH, WEST, NORTH]),
        round_wind=wind,
        self_draw=rng.choice([True, False]),
        concealed=rng.choice([True, False]),
        own_flower_count=rng.randrange(5),
        other_flower_count=rng.randrange(5),
        total_flower_type_count=rng.choice([0, 0, 0, 4]),
        total_season_type_count=rng.choice([0, 0, 0, 4]),
        won_by_kong_replacement=rng.choice([True, False]),
        robbed_kong=rng.choice([True, False]),
        won_on_last_tile=rng.choice([True, False]),
    )


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


# --- property test over random legal hands ----------------------------------

class TestRandomHandInvariants:
    def test_invariants_hold_over_random_legal_hands(self):
        # 2000 hands built from 4 genuinely random melds + a random pair
        # (never hand-picked), each with a random context. This can't
        # check specific fan values, but it exercises decomposition paths
        # and context combinations no hand-picked test would think to try,
        # catching crashes and invariant violations across the board.
        rng = random.Random(2026)
        failures = []
        for _ in range(2000):
            hand = _random_winning_hand(rng)
            context = _random_context(rng)
            result = score_hand(hand, context)

            fan = result["fan"]
            ok = (
                0 <= fan <= FAN_CAP
                and (not result["is_limit"] or fan == FAN_CAP)
                and result["valid"] == (fan >= MINIMUM_FAN)
            )
            if not ok:
                failures.append((sorted(hand), context, result))

        if failures:
            print(f"{len(failures)} invariant violation(s) out of 2000 random hands:")
            for hand, context, result in failures[:10]:
                print(f"  hand={hand} context={context} result={result}")
        assert failures == []


# --- exact component lists (not just totals) --------------------------------
#
# A hand can reach the right total fan through the wrong reasoning -- e.g.
# 6 fan from 混一色(3)+對對糊(3), or just as easily from 混一色(3)+
# 2x箭刻(1 each)+自摸(1). Checking only `fan` can't tell these apart; these
# tests assert the full (name, fan) multiset for hands specifically chosen
# where an absorption bug, a missed/duplicated suit-flush bonus, or a
# forgotten context flag would still land on a total that looks plausible.

class TestExactComponentLists:
    def test_all_chow_three_suits_no_flush_bonus(self):
        hand = [man(1), man(2), man(3),
                man(4), man(5), man(6),
                man(7), man(8), man(9),
                pin(1), pin(2), pin(3),
                sou(5), sou(5)]
        result = score_hand(hand, ctx())
        assert_exact_components(result, [
            ("平糊 All Chows", 1),
            ("無花 No Flowers", 1),
        ])
        assert result["fan"] == 2

    def test_half_flush_and_all_pungs_exact_set(self):
        # Guards against a bug that fires 混一色 or 對對糊 alone, or that
        # also (wrongly) fires a wind/dragon component off the East pung.
        hand = [man(1), man(1), man(1),
                man(2), man(2), man(2),
                man(3), man(3), man(3),
                EAST, EAST, EAST,
                man(4), man(4)]
        result = score_hand(hand, ctx())
        assert_exact_components(result, [
            ("對對糊 All Pungs", 3),
            ("混一色 Half Flush", 3),
            ("無花 No Flowers", 1),
        ])
        assert result["fan"] == 7

    def test_full_flush_and_all_pungs_exact_set(self):
        # Guards against 混一色 firing instead of/alongside 清一色.
        hand = [man(1), man(1), man(1),
                man(2), man(2), man(2),
                man(3), man(3), man(3),
                man(4), man(4), man(4),
                man(5), man(5)]
        result = score_hand(hand, ctx())
        assert_exact_components(result, [
            ("對對糊 All Pungs", 3),
            ("清一色 Full Flush", 7),
            ("無花 No Flowers", 1),
        ])
        assert result["fan"] == 11

    def test_pure_great_three_dragons_two_suits_present(self):
        # man + pin both present (2 suits) -> no suit-flush bonus at all,
        # isolating 大三元's absorption: must be 8, not 8 + 3x箭刻 = 11.
        hand = [RED_DRAGON, RED_DRAGON, RED_DRAGON,
                GREEN_DRAGON, GREEN_DRAGON, GREEN_DRAGON,
                WHITE_DRAGON, WHITE_DRAGON, WHITE_DRAGON,
                man(1), man(2), man(3),
                pin(5), pin(5)]
        result = score_hand(hand, ctx())
        assert_exact_components(result, [
            ("大三元 Great Three Dragons", 8),
            ("無花 No Flowers", 1),
        ])
        assert result["fan"] == 9

    def test_two_dragon_pungs_reach_six_via_individual_fan_not_stacking_bug(self):
        # 混一色(3) + 2x箭刻(1 each) + 自摸(1) = 6 -- the same total as
        # 混一色+對對糊 elsewhere in this file, but via a completely
        # different component set. Exact-list assertion is the only way
        # to tell these apart.
        hand = [RED_DRAGON, RED_DRAGON, RED_DRAGON,
                GREEN_DRAGON, GREEN_DRAGON, GREEN_DRAGON,
                man(1), man(2), man(3),
                man(4), man(5), man(6),
                man(9), man(9)]
        result = score_hand(hand, ctx(self_draw=True, other_flower_count=1))
        assert_exact_components(result, [
            ("混一色 Half Flush", 3),
            ("箭刻 Dragon Pung", 1),
            ("箭刻 Dragon Pung", 1),
            ("自摸 Self-Draw", 1),
        ])
        assert result["fan"] == 6

    def test_small_three_dragons_stacks_with_half_flush_exact_set(self):
        hand = [RED_DRAGON, RED_DRAGON, RED_DRAGON,
                GREEN_DRAGON, GREEN_DRAGON, GREEN_DRAGON,
                man(1), man(2), man(3),
                man(4), man(5), man(6),
                WHITE_DRAGON, WHITE_DRAGON]
        result = score_hand(hand, ctx(other_flower_count=1))
        assert_exact_components(result, [
            ("小三元 Small Three Dragons", 5),
            ("混一色 Half Flush", 3),
        ])
        assert result["fan"] == 8

    def test_small_four_winds_stacks_with_half_flush_exact_set(self):
        hand = [EAST, EAST, EAST,
                SOUTH, SOUTH, SOUTH,
                WEST, WEST, WEST,
                man(1), man(2), man(3),
                NORTH, NORTH]
        result = score_hand(hand, ctx(seat_wind=EAST, round_wind=EAST, other_flower_count=1))
        assert_exact_components(result, [
            ("小四喜 Small Four Winds", 8),
            ("混一色 Half Flush", 3),
        ])
        assert result["fan"] == 11

    def test_great_four_winds_all_pungs_half_flush_uncapped_components_capped_total(self):
        # Uncapped this is 混一色(3)+對對糊(3)+大四喜(10)+無花(1) = 17.
        # `components` must list all four (not silently drop any to fit
        # under the cap); only `fan` gets capped, to 13.
        hand = [EAST, EAST, EAST,
                SOUTH, SOUTH, SOUTH,
                WEST, WEST, WEST,
                NORTH, NORTH, NORTH,
                man(9), man(9)]
        result = score_hand(hand, ctx(seat_wind=EAST, round_wind=EAST))
        assert_exact_components(result, [
            ("大四喜 Great Four Winds", 10),
            ("對對糊 All Pungs", 3),
            ("混一色 Half Flush", 3),
            ("無花 No Flowers", 1),
        ])
        assert result["fan"] == 13
        assert result["is_limit"] is False

    def test_all_honors_stacks_all_pungs_small_four_winds_and_lone_dragon_pung(self):
        # Every tile is an honor: 字一色(10) + 對對糊(3, honors can only
        # pung) + 小四喜(8, East/South/West pung + North pair) + 箭刻(1,
        # the lone Red Dragon pung isn't part of a small/great three) +
        # 無花(1) = 23 uncapped, capped to 13. A prior test only checked
        # 字一色/對對糊 in isolation and would have passed even if 小四喜
        # or 箭刻 were missing or double-counted -- this checks the whole set.
        hand = [EAST, EAST, EAST,
                SOUTH, SOUTH, SOUTH,
                WEST, WEST, WEST,
                RED_DRAGON, RED_DRAGON, RED_DRAGON,
                NORTH, NORTH]
        result = score_hand(hand, ctx(seat_wind=SOUTH, round_wind=SOUTH))
        assert_exact_components(result, [
            ("字一色 All Honors", 10),
            ("對對糊 All Pungs", 3),
            ("小四喜 Small Four Winds", 8),
            ("箭刻 Dragon Pung", 1),
            ("無花 No Flowers", 1),
        ])
        assert result["fan"] == 13

    def test_seat_equals_round_wind_double_count_isolated_from_flush_bonus(self):
        # man + pin both present (2 suits) so no flush bonus muddies this:
        # a single East pung, seat_wind == round_wind == East, must
        # contribute exactly 門風(1) + 圈風(1), nothing else.
        hand = [EAST, EAST, EAST,
                man(1), man(2), man(3),
                man(4), man(5), man(6),
                man(7), man(8), man(9),
                pin(9), pin(9)]
        result = score_hand(hand, ctx(seat_wind=EAST, round_wind=EAST, other_flower_count=1))
        assert_exact_components(result, [
            ("門風 Seat Wind", 1),
            ("圈風 Prevailing Wind", 1),
        ])
        assert result["fan"] == 2
        assert result["valid"] is False

    def test_thirteen_orphans_exact_single_component(self):
        hand = ORPHAN_TILES + [man(1)]
        result = score_hand(hand, ctx(self_draw=True))
        assert_exact_components(result, [("十三么 Thirteen Orphans", 13)])
        assert result["fan"] == 13
        assert result["is_limit"] is True

    def test_two_suits_present_all_chow_plus_own_flowers_no_suit_bonus(self):
        # man + pin present (2 suits): no flush bonus should appear at all.
        hand = [man(1), man(2), man(3),
                man(4), man(5), man(6),
                pin(1), pin(2), pin(3),
                pin(4), pin(5), pin(6),
                man(9), man(9)]
        result = score_hand(hand, ctx(own_flower_count=2, self_draw=True))
        assert_exact_components(result, [
            ("平糊 All Chows", 1),
            ("自摸 Self-Draw", 1),
            ("花 Own Flower/Season", 2),
        ])
        assert result["fan"] == 4

