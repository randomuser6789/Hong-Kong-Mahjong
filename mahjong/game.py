"""Game engine turn loop (RULES.md sections 1, 7, 8). See
tests/test_game.py's module docstring for the full design writeup.

Scope of this phase: build/shuffle/deal, draw, discard, discard-win (食糊)
claims, pung (碰) claims, exposed kong (明槓) claims, chow (上) claims,
concealed kong (暗槓), added kong (加槓), robbing the kong (搶槓, added kong
only -- never concealed), self-draw win detection, wall exhaustion (流局).
No fan/scoring gate (a win only needs structural validity via
is_winning_hand, exactly like self-draw).

Claim window shape: a discard always gathers ALL eligible claims across
ALL seats into `pending_claims`, an ordered-by-priority list of entries
(RULES.md section 7: win > pung/kong > chow). Each entry is
{'seat': int, 'type': str}; chow entries add 'tiles': (a, b, c), the
specific run this option would form, since a single seat's hand can
support more than one shape around the same discarded tile.

Entries are grouped by (seat, TIER) -- tier being a priority class (win /
pung-and-kong / chow), derived from type via _TIER, not a stored key. That
pair, not type alone, is the true unit of "one decision," for two
independent reasons:
  (1) one seat can have two DIFFERENT types in the SAME tier -- holding
      >=3 of a discarded tile offers both 'pung' and 'kong' together, as
      parallel choices (konging is never forced just because a 3rd copy
      is available; keeping it concealed via pung is legitimate). These
      must be grouped, or the player would be asked about them one at a
      time instead of choosing directly.
  (2) no claim type can ever span two DIFFERENT seats on one discard
      today (see the per-tier reasoning below), so grouping must still
      key on seat -- otherwise two different seats' same-tier claims
      would wrongly bundle together.
Both matter simultaneously: pung(seatA) and kong(seatA) must group;
chow(seatA) and pung(seatB) must NOT group even though seat differs from
tier in only one case; two chow entries for DIFFERENT seats must NOT
group even though they share both type and tier.
  - win: 一炮多響 (multiple simultaneous winners) is not used in this
    ruleset, so _find_discard_win_seat itself resolves ties by seat order
    -- (discarder+1)%4, (discarder+2)%4, (discarder+3)%4 in turn,
    returning the FIRST seat that can win and never considering the rest,
    even if they'd also qualify.
  - pung/kong: each tile type has only 4 copies total, so two DIFFERENT
    non-discarder seats each holding >=2 would require >=4 copies among
    just the two of them, which is impossible -- so at most one seat ever
    contributes to this tier, though it may contribute both a 'pung' and
    a 'kong' entry (see (1) above).
  - chow: only (discarder+1)%4 may ever chow -- never a different seat.
The engine keys on (seat, tier), not type, so it stays correct even if a
future rule ever lets one type apply to two seats at once.

Resolution asks the front group (current_turn == pending_claims[0]['seat'],
one action per entry sharing that seat and tier) to pick one option or
pass; passing drops the WHOLE front group (e.g. a 3-holder's pung AND kong
entries together, or every chow variant offered to one seat, together) and
offers the next group, and so on, until either someone accepts (the rest
of the queue is void -- one discard can only be claimed once) or the queue
empties (normal turn order resumes from last_discarder).

Melds are {'tiles': list[int], 'concealed': bool} dicts, not bare tile
lists: a 4-tile meld is otherwise ambiguous between exposed and concealed
kong. 'tiles' has 3 entries for pung/chow, 4 for any kong. 'concealed' is
True only for a concealed kong; pung, chow, exposed kong, and added kong
are all False.

Self-draw win detection (declare_win, checked whenever phase ==
'awaiting_discard') combines the concealed hand with 3 REPRESENTATIVE
tiles per existing meld (meld['tiles'][:3]) before calling
is_winning_hand, which itself requires exactly 14 tiles flat. A kong's 4th
tile never counts toward structure -- its replacement draw already
compensates for it, exactly like real mahjong's slot accounting. Without
this combination step, any player who has ever claimed a pung/chow/kong
would have fewer than 14 concealed tiles from then on and would incorrectly
never be able to declare a self-draw win at all, kong-related or not.
"""

import random
from dataclasses import dataclass, field

from mahjong.winning_hand import is_winning_hand

NUM_SEATS = 4
HAND_SIZE = 13

EAST, SOUTH, WEST, NORTH = 27, 28, 29, 30
WINDS_IN_TURN_ORDER = [EAST, SOUTH, WEST, NORTH]

# Priority tier per claim type (RULES.md section 7: win > pung/kong > chow).
# Grouping key for pending_claims -- see the module docstring. 'rob_kong'
# shares the win tier (robbing pre-empts the kong from completing at all),
# though a rob-kong window is always its own isolated single-entry queue in
# practice, so the tier match is conceptual more than mechanically load-
# bearing here.
_TIER = {"discard_win": 0, "pung": 1, "kong": 1, "chow": 2, "rob_kong": 0}


@dataclass
class GameState:
    wall: list
    hands: list
    melds: list
    discards: list
    current_turn: int
    phase: str
    status: str
    winner: object
    dealer: int
    round_wind: int
    seat_winds: list
    last_discard: object = None
    last_discarder: object = None
    pending_claims: list = field(default_factory=list)


def _build_shuffled_deck(rng):
    deck = [tile for tile in range(34) for _ in range(4)]  # 0-33 x4
    deck += list(range(34, 42))  # 34-41 x1 (flowers/seasons)
    rng.shuffle(deck)
    return deck


def new_game(seed=None, dealer=0):
    rng = random.Random(seed)
    deck = _build_shuffled_deck(rng)

    hands = []
    index = 0
    for seat in range(NUM_SEATS):
        count = HAND_SIZE + 1 if seat == dealer else HAND_SIZE
        hands.append(deck[index:index + count])
        index += count
    wall = deck[index:]

    seat_winds = [WINDS_IN_TURN_ORDER[(seat - dealer) % NUM_SEATS] for seat in range(NUM_SEATS)]

    return GameState(
        wall=wall,
        hands=hands,
        melds=[[] for _ in range(NUM_SEATS)],
        discards=[[] for _ in range(NUM_SEATS)],
        current_turn=dealer,
        phase="awaiting_discard",
        status="in_progress",
        winner=None,
        dealer=dealer,
        round_wind=EAST,
        seat_winds=seat_winds,
        last_discard=None,
        last_discarder=None,
        pending_claims=[],
    )


def _tier_of(claim_type):
    # Unrecognized types (e.g. a test double standing in for a future
    # claim kind) fall back to using the type itself as its own tier, so
    # they still group correctly by type alone rather than crashing.
    return _TIER.get(claim_type, claim_type)


def _front_group(pending_claims):
    """Every entry sharing pending_claims[0]'s (seat, tier) -- the group
    that constitutes "the current decision" (see module docstring)."""
    front = pending_claims[0]
    front_tier = _tier_of(front["type"])
    return [
        claim for claim in pending_claims
        if claim["seat"] == front["seat"] and _tier_of(claim["type"]) == front_tier
    ]


def _combined_hand_for_win_check(hand, seat_melds):
    """The concealed hand plus 3 representative tiles per existing meld --
    see the module docstring for why 3 (not len(meld['tiles'])) is always
    correct, including for a 4-tile kong."""
    combined = list(hand)
    for meld in seat_melds:
        combined.extend(meld["tiles"][:3])
    return combined


def _concealed_kong_options(hand):
    """Distinct tiles the hand holds >=4 of -- each a legal 暗槓 target."""
    return sorted({tile for tile in hand if hand.count(tile) >= 4})


def _added_kong_options(hand, seat_melds):
    """Distinct tiles for which the seat has an existing EXPOSED pung
    (never a concealed one -- concealed pungs don't exist in this engine,
    matching real rules: only a concealed KONG is ever self-declared) AND
    holds >=1 more copy of that tile in hand -- each a legal 加槓 target."""
    options = []
    for meld in seat_melds:
        if not meld["concealed"] and len(meld["tiles"]) == 3:
            tile = meld["tiles"][0]
            if hand.count(tile) >= 1:
                options.append(tile)
    return sorted(options)


def legal_actions(state):
    if state.status != "in_progress":
        return []

    if state.phase == "awaiting_draw":
        return [{"type": "draw"}]

    if state.phase == "awaiting_claim_decision":
        actions = []
        for claim in _front_group(state.pending_claims):
            if claim["type"] == "chow":
                actions.append({"type": "chow", "tiles": claim["tiles"]})
            else:
                actions.append({"type": claim["type"]})
        actions.append({"type": "pass"})
        return actions

    # 'awaiting_discard' or 'awaiting_meld_discard'
    hand = state.hands[state.current_turn]
    actions = [{"type": "discard", "tile": tile} for tile in sorted(set(hand))]

    if state.phase == "awaiting_discard":
        # Self-declared kongs are only legal right after drawing on your
        # own turn (or the dealer's opening 14), never in the forced
        # discard following a claim from someone else's discard.
        seat_melds = state.melds[state.current_turn]
        for tile in _concealed_kong_options(hand):
            actions.append({"type": "concealed_kong", "tile": tile})
        for tile in _added_kong_options(hand, seat_melds):
            actions.append({"type": "added_kong", "tile": tile})

        combined = _combined_hand_for_win_check(hand, seat_melds)
        if is_winning_hand(combined):
            # A claimed meld (pung/chow/kong FROM someone else's discard)
            # can never itself complete a win -- that's what
            # 'awaiting_meld_discard' (handled below, no declare_win at
            # all) is for. A SELF-declared kong is different: it's still
            # this player's own turn, so declare_win is checked again
            # right after it, which is what makes 槓上開花 reachable.
            actions.append({"type": "declare_win"})

    return actions


def _clone_lists(lists_of_lists):
    return [list(inner) for inner in lists_of_lists]


def _clone_melds(melds):
    return [
        [{"tiles": list(meld["tiles"]), "concealed": meld["concealed"]} for meld in seat_melds]
        for seat_melds in melds
    ]


def _clone_claims(claims):
    return [dict(claim) for claim in claims]


def _find_discard_win_seat(hands, discarder, tile):
    """The single seat (if any) that wins on this discard. 一炮多響 (multiple
    simultaneous winners) is not used in this ruleset, so ties are broken
    by seat order: check (discarder+1)%4, then +2, then +3 -- the first
    seat able to win takes it, even if a later seat in that rotation could
    also have won."""
    for offset in range(1, NUM_SEATS):
        seat = (discarder + offset) % NUM_SEATS
        if is_winning_hand(hands[seat] + [tile]):
            return seat
    return None


def _find_pung_and_kong_claims(hands, discarder, tile):
    """The pung/kong tier's entries: at most one seat can ever hold >=2
    copies of the discarded tile (4 copies total per tile type, so two
    DIFFERENT non-discarder seats each holding >=2 would need >=8), and
    that seat gets a 'pung' entry whenever it holds >=2, PLUS a 'kong'
    entry whenever it holds >=3 -- both offered together, since holding a
    3rd copy never forces kong; punging and keeping it concealed is a
    legal choice. Kong is offered even when the wall is empty (see
    apply_action's 'kong' for what happens to the replacement draw then)."""
    for seat in range(NUM_SEATS):
        if seat == discarder:
            continue
        count = hands[seat].count(tile)
        if count >= 2:
            claims = [{"seat": seat, "type": "pung"}]
            if count >= 3:
                claims.append({"seat": seat, "type": "kong"})
            return claims
    return []


def _find_chow_options(hands, discarder, tile):
    """All distinct chow shapes the discarder's immediate next seat (the
    only seat ever allowed to chow) could claim on this tile. A suited
    tile T can complete a run as (T,T+1,T+2), (T-1,T,T+1), or
    (T-2,T-1,T); each shape whose other two tiles are both in that seat's
    hand is a separate option. Honors can never chow."""
    if tile >= 27:
        return []

    chow_seat = (discarder + 1) % NUM_SEATS
    hand = hands[chow_seat]
    rank = tile % 9  # 0-8 within the suit

    shapes = []
    if rank <= 6 and hand.count(tile + 1) >= 1 and hand.count(tile + 2) >= 1:
        shapes.append((tile, tile + 1, tile + 2))
    if 1 <= rank <= 7 and hand.count(tile - 1) >= 1 and hand.count(tile + 1) >= 1:
        shapes.append((tile - 1, tile, tile + 1))
    if rank >= 2 and hand.count(tile - 2) >= 1 and hand.count(tile - 1) >= 1:
        shapes.append((tile - 2, tile - 1, tile))

    shapes.sort()
    return [{"seat": chow_seat, "type": "chow", "tiles": shape} for shape in shapes]


def _gather_pending_claims(hands, discarder, tile):
    """All eligible claims on a just-discarded tile, ordered by priority
    (RULES.md section 7: win > pung/kong > chow)."""
    claims = []
    win_seat = _find_discard_win_seat(hands, discarder, tile)
    if win_seat is not None:
        claims.append({"seat": win_seat, "type": "discard_win"})
    claims.extend(_find_pung_and_kong_claims(hands, discarder, tile))
    claims.extend(_find_chow_options(hands, discarder, tile))
    return claims


def _draw_kong_replacement(wall, hand):
    """Shared by 'kong', 'concealed_kong', and 'added_kong': draw ONE
    replacement tile from the back of the wall into `hand`, in place, if
    the wall is non-empty. Konging with an empty wall is legal but gains
    no replacement (RULES.md section 7) -- no crash, just skip the draw
    and let 流局 resolve normally once this claimer's next discard
    settles with no further claims."""
    if wall:
        hand.append(wall.pop())


def _promote_pung_to_kong(melds, seat, tile):
    """Upgrade seat's existing exposed pung of `tile` to a 4-tile kong, IN
    PLACE on the meld dict, rather than removing+re-appending a new entry.

    Deliberately a distinct, separately-named step (not fused into
    apply_action's 'added_kong' branch) so that a future 搶槓 check has an
    obvious, isolated insertion point: it would go BETWEEN the caller
    removing the tile from hand and this promotion being called -- if some
    other seat can rob `tile` for a win, the promotion (and the
    replacement draw that follows it) would never happen at all; the tile
    would go to the robber instead. Nothing about this function's shape
    needs to change to support that later; only the caller gains a branch
    before calling it.
    """
    for meld in melds[seat]:
        if not meld["concealed"] and meld["tiles"] == [tile, tile, tile]:
            meld["tiles"].append(tile)
            return


def _finalize_added_kong(state, hands, discards, seat, tile):
    """Complete an added kong that was NOT robbed: reclaim the tile off
    the (momentary) discard pile, promote the meld, and draw the
    replacement. Shared by 'added_kong' (when nobody can rob) and 'pass'
    (when the rob was declined) -- both routes must land on the identical
    resulting state shape, since either way this is still the declaring
    seat's own turn afterward (declare_win checked again, same as
    'concealed_kong'). `hands`/`discards` are passed explicitly (rather
    than always reading state.*) because the 'added_kong' caller already
    has freshly-computed arrays (tile removed from hand, appended to
    discards) that haven't been stored into a GameState yet."""
    new_hands = _clone_lists(hands)
    new_discards = _clone_lists(discards)
    new_discards[seat].pop()  # reclaim the momentarily-exposed tile

    new_melds = _clone_melds(state.melds)
    _promote_pung_to_kong(new_melds, seat, tile)

    new_wall = list(state.wall)
    _draw_kong_replacement(new_wall, new_hands[seat])

    return GameState(
        wall=new_wall,
        hands=new_hands,
        melds=new_melds,
        discards=new_discards,
        current_turn=seat,
        phase="awaiting_discard",
        status=state.status,
        winner=state.winner,
        dealer=state.dealer,
        round_wind=state.round_wind,
        seat_winds=list(state.seat_winds),
        last_discard=None,
        last_discarder=None,
        pending_claims=[],
    )


def apply_action(state, action):
    action_type = action["type"]

    if action_type == "draw":
        new_wall = list(state.wall)
        drawn_tile = new_wall.pop(0)
        new_hands = _clone_lists(state.hands)
        new_hands[state.current_turn].append(drawn_tile)
        return GameState(
            wall=new_wall,
            hands=new_hands,
            melds=_clone_melds(state.melds),
            discards=_clone_lists(state.discards),
            current_turn=state.current_turn,
            phase="awaiting_discard",
            status=state.status,
            winner=state.winner,
            dealer=state.dealer,
            round_wind=state.round_wind,
            seat_winds=list(state.seat_winds),
            last_discard=state.last_discard,
            last_discarder=state.last_discarder,
            pending_claims=_clone_claims(state.pending_claims),
        )

    if action_type == "discard":
        tile = action["tile"]
        discarder = state.current_turn
        new_hands = _clone_lists(state.hands)
        new_hands[discarder].remove(tile)
        new_discards = _clone_lists(state.discards)
        new_discards[discarder].append(tile)
        new_wall = list(state.wall)
        new_melds = _clone_melds(state.melds)

        claims = _gather_pending_claims(new_hands, discarder, tile)
        if claims:
            return GameState(
                wall=new_wall,
                hands=new_hands,
                melds=new_melds,
                discards=new_discards,
                current_turn=claims[0]["seat"],
                phase="awaiting_claim_decision",
                status=state.status,
                winner=state.winner,
                dealer=state.dealer,
                round_wind=state.round_wind,
                seat_winds=list(state.seat_winds),
                last_discard=tile,
                last_discarder=discarder,
                pending_claims=claims,
            )

        next_turn = (discarder + 1) % NUM_SEATS
        status = "wall_exhausted" if len(new_wall) == 0 else "in_progress"
        return GameState(
            wall=new_wall,
            hands=new_hands,
            melds=new_melds,
            discards=new_discards,
            current_turn=next_turn,
            phase="awaiting_draw",
            status=status,
            winner=state.winner,
            dealer=state.dealer,
            round_wind=state.round_wind,
            seat_winds=list(state.seat_winds),
            last_discard=None,
            last_discarder=None,
            pending_claims=[],
        )

    if action_type == "discard_win":
        claimer = state.current_turn
        tile = state.last_discard
        discarder = state.last_discarder

        new_hands = _clone_lists(state.hands)
        new_hands[claimer].append(tile)  # the winning tile joins their hand (13 -> 14)

        new_discards = _clone_lists(state.discards)
        new_discards[discarder].pop()  # claimed, not left on the discard pile

        return GameState(
            wall=list(state.wall),
            hands=new_hands,
            melds=_clone_melds(state.melds),
            discards=new_discards,
            current_turn=claimer,
            phase=state.phase,
            status="discard_win",
            winner=claimer,
            dealer=state.dealer,
            round_wind=state.round_wind,
            seat_winds=list(state.seat_winds),
            last_discard=None,
            last_discarder=None,
            pending_claims=[],
        )

    if action_type == "pung":
        claimer = state.current_turn
        tile = state.last_discard
        discarder = state.last_discarder

        new_hands = _clone_lists(state.hands)
        new_hands[claimer].remove(tile)
        new_hands[claimer].remove(tile)

        new_discards = _clone_lists(state.discards)
        new_discards[discarder].pop()  # move the pending tile off the discard pile...

        new_melds = _clone_melds(state.melds)
        new_melds[claimer].append({"tiles": [tile, tile, tile], "concealed": False})  # ...and into the exposed meld

        return GameState(
            wall=list(state.wall),
            hands=new_hands,
            melds=new_melds,
            discards=new_discards,
            current_turn=claimer,
            phase="awaiting_meld_discard",
            status=state.status,
            winner=state.winner,
            dealer=state.dealer,
            round_wind=state.round_wind,
            seat_winds=list(state.seat_winds),
            last_discard=None,
            last_discarder=None,
            pending_claims=[],  # accepting voids every other pending claim on this discard
        )

    if action_type == "kong":
        claimer = state.current_turn
        tile = state.last_discard
        discarder = state.last_discarder

        new_hands = _clone_lists(state.hands)
        for _ in range(3):
            new_hands[claimer].remove(tile)

        new_discards = _clone_lists(state.discards)
        new_discards[discarder].pop()  # move the pending tile off the discard pile...

        new_melds = _clone_melds(state.melds)
        new_melds[claimer].append({"tiles": [tile, tile, tile, tile], "concealed": False})  # ...and into the exposed kong

        new_wall = list(state.wall)
        _draw_kong_replacement(new_wall, new_hands[claimer])

        return GameState(
            wall=new_wall,
            hands=new_hands,
            melds=new_melds,
            discards=new_discards,
            current_turn=claimer,
            phase="awaiting_meld_discard",
            status=state.status,
            winner=state.winner,
            dealer=state.dealer,
            round_wind=state.round_wind,
            seat_winds=list(state.seat_winds),
            last_discard=None,
            last_discarder=None,
            pending_claims=[],  # accepting voids every other pending claim on this discard
        )

    if action_type == "chow":
        claimer = state.current_turn
        tile = state.last_discard
        discarder = state.last_discarder
        run = list(action["tiles"])

        new_hands = _clone_lists(state.hands)
        run_remaining = list(run)
        run_remaining.remove(tile)  # the other two tiles come from hand
        for needed_tile in run_remaining:
            new_hands[claimer].remove(needed_tile)

        new_discards = _clone_lists(state.discards)
        new_discards[discarder].pop()  # move the pending tile off the discard pile...

        new_melds = _clone_melds(state.melds)
        new_melds[claimer].append({"tiles": run, "concealed": False})  # ...and into the exposed meld

        return GameState(
            wall=list(state.wall),
            hands=new_hands,
            melds=new_melds,
            discards=new_discards,
            current_turn=claimer,
            phase="awaiting_meld_discard",
            status=state.status,
            winner=state.winner,
            dealer=state.dealer,
            round_wind=state.round_wind,
            seat_winds=list(state.seat_winds),
            last_discard=None,
            last_discarder=None,
            pending_claims=[],  # accepting voids every other pending claim on this discard
        )

    if action_type == "concealed_kong":
        seat = state.current_turn
        tile = action["tile"]

        new_hands = _clone_lists(state.hands)
        for _ in range(4):
            new_hands[seat].remove(tile)

        new_melds = _clone_melds(state.melds)
        new_melds[seat].append({"tiles": [tile, tile, tile, tile], "concealed": True})

        new_wall = list(state.wall)
        _draw_kong_replacement(new_wall, new_hands[seat])

        return GameState(
            wall=new_wall,
            hands=new_hands,
            melds=new_melds,
            discards=_clone_lists(state.discards),
            current_turn=seat,
            phase="awaiting_discard",  # still their own turn -- declare_win checked again
            status=state.status,
            winner=state.winner,
            dealer=state.dealer,
            round_wind=state.round_wind,
            seat_winds=list(state.seat_winds),
            last_discard=state.last_discard,
            last_discarder=state.last_discarder,
            pending_claims=_clone_claims(state.pending_claims),
        )

    if action_type == "added_kong":
        seat = state.current_turn
        tile = action["tile"]

        new_hands = _clone_lists(state.hands)
        new_hands[seat].remove(tile)

        # The tile is momentarily "exposed" on the discard pile -- exactly
        # like a real discard visually, and exactly why it's robbable at
        # all -- so it's accounted for somewhere (not floating outside
        # hands/melds/discards/wall) while the rob decision is pending.
        new_discards = _clone_lists(state.discards)
        new_discards[seat].append(tile)

        # 搶槓 branch point (see _promote_pung_to_kong): before finalizing
        # the promotion, check whether any OTHER seat can rob this exposed
        # tile for a win. Reuses the exact same eligibility/tiebreak logic
        # as a real discard win -- 一炮多響 rules out more than one robber.
        robber = _find_discard_win_seat(new_hands, seat, tile)
        if robber is not None:
            return GameState(
                wall=list(state.wall),
                hands=new_hands,
                melds=_clone_melds(state.melds),  # NOT promoted -- stays a 3-tile pung
                discards=new_discards,
                current_turn=robber,
                phase="awaiting_claim_decision",
                status=state.status,
                winner=state.winner,
                dealer=state.dealer,
                round_wind=state.round_wind,
                seat_winds=list(state.seat_winds),
                last_discard=tile,
                last_discarder=seat,
                pending_claims=[{"seat": robber, "type": "rob_kong"}],
            )

        return _finalize_added_kong(state, new_hands, new_discards, seat, tile)

    if action_type == "rob_kong":
        robber = state.current_turn
        tile = state.last_discard
        declarer = state.last_discarder
        # The promoter's exposed pung simply stays a pung forever -- the
        # kong never happened, so melds are untouched.

        new_discards = _clone_lists(state.discards)
        new_discards[declarer].pop()  # reclaim the momentarily-exposed tile...

        new_hands = _clone_lists(state.hands)
        new_hands[robber].append(tile)  # ...it goes to the robber instead

        return GameState(
            wall=list(state.wall),
            hands=new_hands,
            melds=_clone_melds(state.melds),
            discards=new_discards,
            current_turn=robber,
            phase=state.phase,
            status="kong_robbed",
            winner=robber,
            dealer=state.dealer,
            round_wind=state.round_wind,
            seat_winds=list(state.seat_winds),
            last_discard=None,
            last_discarder=None,
            pending_claims=[],
        )

    if action_type == "pass":
        front = state.pending_claims[0]
        if front["type"] == "rob_kong":
            # Declined the rob -- the added kong completes normally. The
            # tile was already removed from the declaring seat's hand and
            # placed on their discard pile when the kong was declared (see
            # 'added_kong' above), so this is exactly the same
            # finalization that branch's no-robber path
            # uses.
            return _finalize_added_kong(
                state, state.hands, state.discards, state.last_discarder, state.last_discard
            )

        front_tier = _tier_of(front["type"])
        remaining = [
            claim for claim in state.pending_claims
            if not (claim["seat"] == front["seat"] and _tier_of(claim["type"]) == front_tier)
        ]
        if remaining:
            return GameState(
                wall=list(state.wall),
                hands=_clone_lists(state.hands),
                melds=_clone_melds(state.melds),
                discards=_clone_lists(state.discards),
                current_turn=remaining[0]["seat"],
                phase="awaiting_claim_decision",
                status=state.status,
                winner=state.winner,
                dealer=state.dealer,
                round_wind=state.round_wind,
                seat_winds=list(state.seat_winds),
                last_discard=state.last_discard,
                last_discarder=state.last_discarder,
                pending_claims=_clone_claims(remaining),
            )

        new_wall = list(state.wall)
        next_turn = (state.last_discarder + 1) % NUM_SEATS
        status = "wall_exhausted" if len(new_wall) == 0 else "in_progress"
        return GameState(
            wall=new_wall,
            hands=_clone_lists(state.hands),
            melds=_clone_melds(state.melds),
            discards=_clone_lists(state.discards),
            current_turn=next_turn,
            phase="awaiting_draw",
            status=status,
            winner=state.winner,
            dealer=state.dealer,
            round_wind=state.round_wind,
            seat_winds=list(state.seat_winds),
            last_discard=None,
            last_discarder=None,
            pending_claims=[],
        )

    if action_type == "declare_win":
        return GameState(
            wall=list(state.wall),
            hands=_clone_lists(state.hands),
            melds=_clone_melds(state.melds),
            discards=_clone_lists(state.discards),
            current_turn=state.current_turn,
            phase=state.phase,
            status="self_draw_win",
            winner=state.current_turn,
            dealer=state.dealer,
            round_wind=state.round_wind,
            seat_winds=list(state.seat_winds),
            last_discard=state.last_discard,
            last_discarder=state.last_discarder,
            pending_claims=_clone_claims(state.pending_claims),
        )

    raise ValueError(f"unknown action type: {action_type!r}")
