"""Fan (番) scorer per RULES.md section 4. Assumes `tiles` already passes
mahjong.winning_hand.is_winning_hand -- this module does not re-validate
hand legality.

context spec (all keys optional, defaulting to "off"/0/False) -- see
tests/test_scoring.py's module docstring for the full field list. Notably,
own_flower_count/other_flower_count are CALLER-RESOLVED: which flower/
season tile (34-41) belongs to which seat is not specified in RULES.md, so
this module never inspects raw flower tile codes.

A hand can decompose into melds multiple ways (e.g. 111222333 as three
pungs or three chows), and different decompositions can score different
fan. score_hand() computes every valid decomposition and returns the
maximum-scoring one.

Absorption: 大三元/小三元 absorb their component 箭刻 fans; 大四喜/小四喜
absorb their component 門風/圈風 fans. They do NOT absorb 對對糊/平糊 --
those are scored independently whenever the hand structurally qualifies.
"""

from collections import Counter

MINIMUM_FAN = 3
FAN_CAP = 13

DRAGONS = frozenset({31, 32, 33})
WINDS = frozenset({27, 28, 29, 30})
THIRTEEN_ORPHAN_TILES = frozenset({
    0, 8, 9, 17, 18, 26,
    27, 28, 29, 30,
    31, 32, 33,
})


def score_hand(tiles, context):
    if context.get("is_heavenly_hand"):
        return _limit_result("天糊 Heavenly Hand")
    if context.get("is_earthly_hand"):
        return _limit_result("地糊 Earthly Hand")

    if _is_thirteen_orphans(tiles):
        return _limit_result("十三么 Thirteen Orphans")

    decompositions = _standard_decompositions(tiles)

    kong_tiles = set(context.get("kong_tiles") or [])
    if len(kong_tiles) == 4:
        for melds, pair_tile in decompositions:
            pung_tiles = {tile for kind, tile in melds if kind == "pung"}
            if len(melds) == 4 and pung_tiles == kong_tiles:
                return _limit_result("十八羅漢 All Kongs")

    constant_components = _context_only_components(tiles, context)
    constant_fan = sum(fan for _, fan in constant_components)

    best_total = None
    best_components = None
    for melds, pair_tile in decompositions:
        variable_components = _decomposition_components(melds, pair_tile, context)
        total = constant_fan + sum(fan for _, fan in variable_components)
        if best_total is None or total > best_total:
            best_total = total
            best_components = constant_components + variable_components

    capped_fan = min(best_total, FAN_CAP)
    return {
        "fan": capped_fan,
        "components": best_components,
        "is_limit": False,
        "valid": capped_fan >= MINIMUM_FAN,
    }


def _limit_result(name):
    return {
        "fan": FAN_CAP,
        "components": [(name, FAN_CAP)],
        "is_limit": True,
        "valid": True,
    }


def _is_thirteen_orphans(tiles):
    if set(tiles) != THIRTEEN_ORPHAN_TILES:
        return False
    counts = Counter(tiles)
    return sorted(counts.values()) == [1] * 12 + [2]


def _standard_decompositions(tiles):
    counts = Counter(tiles)
    results = []
    for pair_tile in [t for t in counts if counts[t] >= 2]:
        counts[pair_tile] -= 2
        for melds in _meld_combinations(counts):
            if len(melds) == 4:
                results.append((melds, pair_tile))
        counts[pair_tile] += 2
    return results


def _meld_combinations(counts):
    tile = next((t for t in sorted(counts) if counts[t] > 0), None)
    if tile is None:
        return [()]

    combos = []

    if counts[tile] >= 3:
        counts[tile] -= 3
        for rest in _meld_combinations(counts):
            combos.append((("pung", tile),) + rest)
        counts[tile] += 3

    if tile < 27:
        pos = tile % 9
        if pos <= 6 and counts.get(tile + 1, 0) > 0 and counts.get(tile + 2, 0) > 0:
            counts[tile] -= 1
            counts[tile + 1] -= 1
            counts[tile + 2] -= 1
            for rest in _meld_combinations(counts):
                combos.append((("chow", tile),) + rest)
            counts[tile] += 1
            counts[tile + 1] += 1
            counts[tile + 2] += 1

    return combos


def _suit_of(tile):
    return tile // 9


def _context_only_components(tiles, context):
    components = []

    suited = [t for t in tiles if t < 27]
    suits_present = {_suit_of(t) for t in suited}
    honors_present = any(t >= 27 for t in tiles)

    if len(suits_present) == 0:
        components.append(("字一色 All Honors", 10))
    elif len(suits_present) == 1:
        if honors_present:
            components.append(("混一色 Half Flush", 3))
        else:
            components.append(("清一色 Full Flush", 7))

    own_flowers = context.get("own_flower_count", 0)
    other_flowers = context.get("other_flower_count", 0)
    if own_flowers:
        components.append(("花 Own Flower/Season", own_flowers))
    if own_flowers + other_flowers == 0:
        components.append(("無花 No Flowers", 1))

    if context.get("total_flower_type_count", 0) == 4:
        components.append(("一台花 Full Set of Flowers", 2))
    if context.get("total_season_type_count", 0) == 4:
        components.append(("一台花 Full Set of Seasons", 2))

    if context.get("self_draw"):
        components.append(("自摸 Self-Draw", 1))
    if context.get("concealed") and not context.get("self_draw"):
        components.append(("門前清 Concealed", 1))
    if context.get("won_by_kong_replacement"):
        components.append(("槓上開花 Kong Replacement", 1))
    if context.get("robbed_kong"):
        components.append(("搶槓 Robbing the Kong", 1))
    if context.get("won_on_last_tile"):
        components.append(("海底撈月 Last Tile", 1))

    return components


def _decomposition_components(melds, pair_tile, context):
    components = []
    kinds = [kind for kind, _ in melds]

    if all(kind == "chow" for kind in kinds):
        components.append(("平糊 All Chows", 1))
    if all(kind == "pung" for kind in kinds):
        components.append(("對對糊 All Pungs", 3))

    pung_tiles = {tile for kind, tile in melds if kind == "pung"}

    dragon_pungs = pung_tiles & DRAGONS
    if len(dragon_pungs) == 3:
        components.append(("大三元 Great Three Dragons", 8))
    elif len(dragon_pungs) == 2 and pair_tile in DRAGONS:
        components.append(("小三元 Small Three Dragons", 5))
    else:
        for _ in dragon_pungs:
            components.append(("箭刻 Dragon Pung", 1))

    wind_pungs = pung_tiles & WINDS
    seat_wind = context.get("seat_wind")
    round_wind = context.get("round_wind")
    if len(wind_pungs) == 4:
        components.append(("大四喜 Great Four Winds", 10))
    elif len(wind_pungs) == 3 and pair_tile in WINDS:
        components.append(("小四喜 Small Four Winds", 8))
    else:
        for wind in wind_pungs:
            if wind == seat_wind:
                components.append(("門風 Seat Wind", 1))
            if wind == round_wind:
                components.append(("圈風 Prevailing Wind", 1))

    return components
