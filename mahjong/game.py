"""Game engine turn loop (RULES.md sections 1, 7, 8). See
tests/test_game.py's module docstring for the full design writeup.

Scope of this phase: build/shuffle/deal, draw, discard, discard-win (食糊)
claims, pung (碰) claims, chow (上) claims, self-draw win detection, wall
exhaustion (流局). No kong, no fan/scoring gate (a discard win only needs
structural validity via is_winning_hand, exactly like self-draw).

Claim window shape: a discard always gathers ALL eligible claims across
ALL seats into `pending_claims`, an ordered-by-priority list of entries
(RULES.md section 7: win > pung/kong > chow). Each entry is
{'seat': int, 'type': str}; chow entries add 'tiles': (a, b, c), the
specific run this option would form, since a single seat's hand can
support more than one shape around the same discarded tile.

Entries are grouped by (seat, type) -- that pair, not type alone, is the
true unit of "one decision," because it's possible (once chow exists) for
the SAME seat to have entries of two different types on one discard (e.g.
pung AND chow), and those must stay separate decisions with pung offered
first. Grouping happens to coincide with grouping-by-type-alone today,
because no claim type can ever span two DIFFERENT seats on one discard:
  - win: 一炮多響 (multiple simultaneous winners) is not used in this
    ruleset, so _find_discard_win_seat itself resolves ties by seat order
    -- (discarder+1)%4, (discarder+2)%4, (discarder+3)%4 in turn,
    returning the FIRST seat that can win and never considering the rest,
    even if they'd also qualify.
  - pung/kong: each tile type has only 4 copies total, so two DIFFERENT
    non-discarder seats each holding >=2 would require >=4 copies among
    just the two of them, which is impossible.
  - chow: only (discarder+1)%4 may ever chow -- never a different seat.
But the code keys on (seat, type), not type, so it stays correct even if a
future rule ever lets one type apply to two seats at once.

Resolution asks the front group (current_turn == pending_claims[0]['seat'],
one action per entry sharing that seat and type) to pick one option or
pass; passing drops the WHOLE front group (e.g. every chow variant offered
to that seat, together) and offers the next group, and so on, until either
someone accepts (the rest of the queue is void -- one discard can only be
claimed once) or the queue empties (normal turn order resumes from
last_discarder). Adding kong later is just teaching _gather_pending_claims
to also detect it, inserted at the pung priority position -- the queue/
offer/accept/pass mechanics don't change.
"""

import random
from dataclasses import dataclass, field

from mahjong.winning_hand import is_winning_hand

NUM_SEATS = 4
HAND_SIZE = 13

EAST, SOUTH, WEST, NORTH = 27, 28, 29, 30
WINDS_IN_TURN_ORDER = [EAST, SOUTH, WEST, NORTH]


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


def _front_group(pending_claims):
    """Every entry sharing pending_claims[0]'s (seat, type) -- the group
    that constitutes "the current decision" (see module docstring)."""
    front = pending_claims[0]
    return [
        claim for claim in pending_claims
        if claim["seat"] == front["seat"] and claim["type"] == front["type"]
    ]


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
    if state.phase == "awaiting_discard" and is_winning_hand(hand):
        # A claimed meld can never itself complete a win (unlike robbing a
        # kong, which doesn't exist yet), so declare_win is withheld in
        # 'awaiting_meld_discard' even if the hand+meld tiles happen to
        # look structurally complete.
        actions.append({"type": "declare_win"})
    return actions


def _clone_lists(lists_of_lists):
    return [list(inner) for inner in lists_of_lists]


def _clone_melds(melds):
    return [[list(meld) for meld in seat_melds] for seat_melds in melds]


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


def _find_pung_eligible_seat(hands, discarder, tile):
    for seat in range(NUM_SEATS):
        if seat != discarder and hands[seat].count(tile) >= 2:
            return seat
    return None


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
    (RULES.md section 7: win > pung/kong > chow). A kong-eligibility check
    would add its entry here too, at the pung priority position, without
    touching how the resulting queue is offered/resolved."""
    claims = []
    win_seat = _find_discard_win_seat(hands, discarder, tile)
    if win_seat is not None:
        claims.append({"seat": win_seat, "type": "discard_win"})
    pung_seat = _find_pung_eligible_seat(hands, discarder, tile)
    if pung_seat is not None:
        claims.append({"seat": pung_seat, "type": "pung"})
    claims.extend(_find_chow_options(hands, discarder, tile))
    return claims


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
        new_melds[claimer].append([tile, tile, tile])  # ...and into the exposed meld

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
        new_melds[claimer].append(run)  # ...and into the exposed meld

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

    if action_type == "pass":
        front = state.pending_claims[0]
        remaining = [
            claim for claim in state.pending_claims
            if not (claim["seat"] == front["seat"] and claim["type"] == front["type"])
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
