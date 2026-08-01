"""Game engine turn loop (RULES.md sections 1, 7, 8). See
tests/test_game.py's module docstring for the full design writeup.

Scope of this phase: build/shuffle/deal, draw, discard, self-draw win
detection, wall exhaustion (流局). No pung/chow/kong, no scoring/fan gate.
"""

import random
from dataclasses import dataclass

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
    )


def legal_actions(state):
    if state.status != "in_progress":
        return []

    if state.phase == "awaiting_draw":
        return [{"type": "draw"}]

    hand = state.hands[state.current_turn]
    actions = [{"type": "discard", "tile": tile} for tile in sorted(set(hand))]
    if is_winning_hand(hand):
        actions.append({"type": "declare_win"})
    return actions


def _clone_lists(lists_of_lists):
    return [list(inner) for inner in lists_of_lists]


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
            melds=_clone_lists(state.melds),
            discards=_clone_lists(state.discards),
            current_turn=state.current_turn,
            phase="awaiting_discard",
            status=state.status,
            winner=state.winner,
            dealer=state.dealer,
            round_wind=state.round_wind,
            seat_winds=list(state.seat_winds),
        )

    if action_type == "discard":
        tile = action["tile"]
        new_hands = _clone_lists(state.hands)
        new_hands[state.current_turn].remove(tile)
        new_discards = _clone_lists(state.discards)
        new_discards[state.current_turn].append(tile)
        new_wall = list(state.wall)
        next_turn = (state.current_turn + 1) % NUM_SEATS
        status = "wall_exhausted" if len(new_wall) == 0 else "in_progress"
        return GameState(
            wall=new_wall,
            hands=new_hands,
            melds=_clone_lists(state.melds),
            discards=new_discards,
            current_turn=next_turn,
            phase="awaiting_draw",
            status=status,
            winner=state.winner,
            dealer=state.dealer,
            round_wind=state.round_wind,
            seat_winds=list(state.seat_winds),
        )

    if action_type == "declare_win":
        return GameState(
            wall=list(state.wall),
            hands=_clone_lists(state.hands),
            melds=_clone_lists(state.melds),
            discards=_clone_lists(state.discards),
            current_turn=state.current_turn,
            phase=state.phase,
            status="self_draw_win",
            winner=state.current_turn,
            dealer=state.dealer,
            round_wind=state.round_wind,
            seat_winds=list(state.seat_winds),
        )

    raise ValueError(f"unknown action type: {action_type!r}")
