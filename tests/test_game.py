"""Tests for the game engine turn loop (RULES.md sections 1, 7, 8).

Target API (not yet implemented): mahjong/game.py

    GameState -- plain dataclass, fields:
        wall: list[int]            remaining tiles; wall[0] is drawn next
        hands: list[list[int]]     4 seats' concealed tiles
        melds: list[list[int]]     4 seats' exposed meld tiles (always [],
                                    [], [], [] in this phase -- no calls yet)
        discards: list[list[int]]  4 seats' discard piles, in order
        current_turn: int          seat index (0-3) whose turn it is
        phase: str                 'awaiting_draw' | 'awaiting_discard'
        status: str                'in_progress' | 'self_draw_win' | 'wall_exhausted'
        winner: int | None         seat index that won, else None
        dealer: int                seat index of the dealer
        round_wind: int            tile code 27-30
        seat_winds: list[int]      each seat's wind, tile code 27-30

    new_game(seed=None, dealer=0) -> GameState
        Builds and shuffles the full 144-tile set (RULES.md section 1: each
        of tiles 0-33 x4, each of tiles 34-41 x1). Deals 13 tiles to each
        non-dealer seat and 14 to the dealer (the dealer's traditional
        opening extra tile, dealt directly rather than drawn) -- this is
        what keeps 天糊 (dealer wins on the deal) and 地糊 (non-dealer wins
        on their first drawn tile) reachable at all: 天糊 requires a legal
        win with zero draws having happened yet, so the dealer must
        already hold 14. No dead wall (per design decision): kong/flower
        replacements will draw from the back of this same `wall` list in a
        later phase; normal turns always draw from the front (wall[0]).
        Live wall after dealing = 144 - 13*3 - 14 = 91. Starting phase is
        'awaiting_discard' for the dealer (they open by discarding, not
        drawing); every other seat's turn begins at 'awaiting_draw' as usual.

    legal_actions(state) -> list[dict]
        [] if state.status != 'in_progress'.
        [{'type': 'draw'}] if phase == 'awaiting_draw'.
        Else (phase == 'awaiting_discard'): one {'type': 'discard', 'tile': t}
        per DISTINCT tile value in the current player's hand (sorted), plus
        {'type': 'declare_win'} iff the current 14-tile hand is currently a
        valid winning hand per mahjong.winning_hand.is_winning_hand. Declaring
        is a choice, not forced -- min-fan gating belongs to a later scoring
        pass, not this structural check.

    apply_action(state, action) -> GameState
        Pure function: returns a NEW GameState, does not mutate the input.
        'draw': moves wall[0] into the current player's hand, phase ->
            'awaiting_discard'.
        'discard': removes one copy of the tile from the current player's
            hand, appends it to their discard pile, advances current_turn
            to (current_turn + 1) % 4. If the wall is now empty, status ->
            'wall_exhausted' (this is when 流局 is detected -- there's no
            next draw to attempt). Otherwise phase -> 'awaiting_draw'.
        'declare_win': status -> 'self_draw_win', winner -> current_turn.
"""

import random

from mahjong.game import GameState, apply_action, legal_actions, new_game
from mahjong.winning_hand import is_winning_hand

TOTAL_TILES = 144
HAND_SIZE = 13

EAST, SOUTH, WEST, NORTH = 27, 28, 29, 30
RED_DRAGON, GREEN_DRAGON, WHITE_DRAGON = 31, 32, 33
WINDS_IN_TURN_ORDER = [EAST, SOUTH, WEST, NORTH]


def man(n):
    return n - 1


def pin(n):
    return 9 + n - 1


def sou(n):
    return 18 + n - 1


def total_tiles_in_play(state):
    return (
        sum(len(hand) for hand in state.hands)
        + sum(len(pile) for pile in state.discards)
        + sum(len(meld) for meld in state.melds)
        + len(state.wall)
    )


# --- dealing -----------------------------------------------------------------

class TestDeal:
    def test_wall_size_after_dealing(self):
        state = new_game(seed=1)
        # 3 non-dealer seats x 13, dealer x 14.
        assert len(state.wall) == TOTAL_TILES - (3 * HAND_SIZE + (HAND_SIZE + 1))  # 91

    def test_dealer_has_fourteen_tiles_others_have_thirteen(self):
        state = new_game(seed=1, dealer=0)
        assert len(state.hands) == 4
        assert len(state.hands[0]) == HAND_SIZE + 1
        assert all(len(state.hands[seat]) == HAND_SIZE for seat in (1, 2, 3))

    def test_hand_sizes_follow_the_dealer_seat_not_always_seat_zero(self):
        state = new_game(seed=1, dealer=2)
        assert len(state.hands[2]) == HAND_SIZE + 1
        assert all(len(state.hands[seat]) == HAND_SIZE for seat in (0, 1, 3))

    def test_all_144_tiles_are_accounted_for_with_no_duplication_beyond_the_deck(self):
        state = new_game(seed=1)
        dealt = [tile for hand in state.hands for tile in hand]
        all_tiles = dealt + list(state.wall)
        assert len(all_tiles) == TOTAL_TILES
        # Deck composition per RULES.md section 1: tiles 0-33 x4, 34-41 x1.
        for tile in range(34):
            assert all_tiles.count(tile) == 4
        for tile in range(34, 42):
            assert all_tiles.count(tile) == 1

    def test_discards_and_melds_start_empty(self):
        state = new_game(seed=1)
        assert state.discards == [[], [], [], []]
        assert state.melds == [[], [], [], []]

    def test_initial_turn_state(self):
        state = new_game(seed=1, dealer=0)
        assert state.status == "in_progress"
        assert state.phase == "awaiting_discard"  # dealer already holds 14
        assert state.current_turn == 0
        assert state.dealer == 0
        assert state.winner is None

    def test_seat_winds_assigned_relative_to_dealer(self):
        state = new_game(seed=1, dealer=2)
        # Seat `dealer` is East; winds proceed in turn order from there.
        expected = [WINDS_IN_TURN_ORDER[(seat - 2) % 4] for seat in range(4)]
        assert state.seat_winds == expected
        assert state.seat_winds[2] == EAST

    def test_different_seeds_produce_different_deals(self):
        state_a = new_game(seed=1)
        state_b = new_game(seed=2)
        assert state_a.hands != state_b.hands

    def test_same_seed_is_deterministic(self):
        state_a = new_game(seed=1)
        state_b = new_game(seed=1)
        assert state_a.hands == state_b.hands
        assert state_a.wall == state_b.wall


# --- immutability: apply_action must not share list references ---------------

class TestImmutability:
    def test_mutating_child_state_does_not_affect_the_parent(self):
        state = new_game(seed=1, dealer=0)
        original_hand = list(state.hands[0])
        original_wall = list(state.wall)

        tile = state.hands[0][0]
        child = apply_action(state, {"type": "discard", "tile": tile})

        # Mutate the child's hand and wall in place.
        child.hands[child.current_turn].append(999)
        child.wall.append(999)

        # The parent's hand and wall must be untouched -- if apply_action
        # had just returned the same list objects (or shallow-copied the
        # outer list but not its inner lists), this mutation would leak
        # back into `state`.
        assert state.hands[0] == original_hand
        assert state.wall == original_wall
        assert 999 not in state.hands[0]
        assert 999 not in state.wall


# --- draw / discard step mechanics -------------------------------------------

def _after_dealer_opens(state):
    """Plays the dealer's opening discard (their 14 -> 13, no draw) so
    tests can exercise the ordinary draw-then-discard loop starting from
    the next seat, exactly as it behaves for every turn after the first."""
    tile = state.hands[state.dealer][0]
    return apply_action(state, {"type": "discard", "tile": tile})


class TestDrawStep:
    def test_draw_moves_wall_head_into_current_players_hand(self):
        state = _after_dealer_opens(new_game(seed=1, dealer=0))
        assert state.phase == "awaiting_draw"
        acting_seat = state.current_turn
        next_tile = state.wall[0]
        new_state = apply_action(state, {"type": "draw"})
        assert len(new_state.wall) == len(state.wall) - 1
        assert len(new_state.hands[acting_seat]) == HAND_SIZE + 1
        assert next_tile in new_state.hands[acting_seat]
        assert new_state.phase == "awaiting_discard"
        # apply_action must not mutate the original state
        assert len(state.hands[acting_seat]) == HAND_SIZE

    def test_only_current_players_hand_changes_on_draw(self):
        state = _after_dealer_opens(new_game(seed=1, dealer=0))
        acting_seat = state.current_turn
        new_state = apply_action(state, {"type": "draw"})
        for seat in range(4):
            if seat != acting_seat:
                assert new_state.hands[seat] == state.hands[seat]


class TestDiscardStep:
    def test_dealers_opening_discard_returns_hand_to_thirteen_and_records_it(self):
        state = new_game(seed=1, dealer=0)
        tile_to_discard = state.hands[0][0]
        new_state = apply_action(state, {"type": "discard", "tile": tile_to_discard})
        assert len(new_state.hands[0]) == HAND_SIZE
        assert new_state.discards[0] == [tile_to_discard]

    def test_discard_after_a_draw_returns_hand_to_thirteen_and_records_it(self):
        state = _after_dealer_opens(new_game(seed=1, dealer=0))
        acting_seat = state.current_turn
        state = apply_action(state, {"type": "draw"})
        tile_to_discard = state.hands[acting_seat][0]
        new_state = apply_action(state, {"type": "discard", "tile": tile_to_discard})
        assert len(new_state.hands[acting_seat]) == HAND_SIZE
        assert new_state.discards[acting_seat] == [tile_to_discard]

    def test_discard_advances_turn_to_next_seat(self):
        state = new_game(seed=1, dealer=0)
        tile = state.hands[0][0]
        new_state = apply_action(state, {"type": "discard", "tile": tile})
        assert new_state.current_turn == 1
        assert new_state.phase == "awaiting_draw"

    def test_turn_wraps_around_from_seat_three_to_seat_zero(self):
        state = new_game(seed=1, dealer=3)
        tile = state.hands[3][0]
        new_state = apply_action(state, {"type": "discard", "tile": tile})
        assert new_state.current_turn == 0


# --- legal_actions -------------------------------------------------------------

class TestLegalActions:
    def test_dealer_opening_actions_are_discards_not_a_draw(self):
        state = new_game(seed=1)
        actions = legal_actions(state)
        assert {"type": "draw"} not in actions
        discard_tiles = sorted(a["tile"] for a in actions if a["type"] == "discard")
        assert discard_tiles == sorted(set(state.hands[state.current_turn]))

    def test_draw_is_legal_once_it_is_a_non_dealer_seats_turn(self):
        state = _after_dealer_opens(new_game(seed=1, dealer=0))
        assert legal_actions(state) == [{"type": "draw"}]

    def test_discard_options_are_one_per_distinct_tile_value(self):
        state = new_game(seed=1)
        hand = state.hands[state.current_turn]
        actions = legal_actions(state)
        discard_tiles = sorted(a["tile"] for a in actions if a["type"] == "discard")
        assert discard_tiles == sorted(set(hand))

    def test_no_actions_once_game_has_terminated(self):
        state = new_game(seed=1)
        tile = state.hands[state.current_turn][0]
        state = apply_action(state, {"type": "discard", "tile": tile})
        # Force-terminate for this test by directly constructing a
        # terminal state, since reaching one naturally takes a full game.
        terminal = GameState(
            wall=state.wall, hands=state.hands, melds=state.melds,
            discards=state.discards, current_turn=state.current_turn,
            phase=state.phase, status="wall_exhausted", winner=None,
            dealer=state.dealer, round_wind=state.round_wind,
            seat_winds=state.seat_winds,
        )
        assert legal_actions(terminal) == []


# --- self-draw win detection (constructed scenarios, not left to chance) ----

class TestSelfDrawWin:
    def _tenpai_state(self):
        # A generic mid-game draw-completes-the-hand scenario (NOT the
        # opening deal -- seat 0 here has the ordinary 13 tiles and is in
        # 'awaiting_draw', as any seat would be on a later turn). Holds a
        # 13-tile tanki wait: 123m 456m 789m 123p + lone 5p. Drawing
        # another 5p completes 4 melds + pair -> a win.
        # The other three hands are irrelevant filler (never inspected by
        # is_winning_hand for this seat), so they're just arbitrary tiles
        # not otherwise used, kept under the 4-copy cap.
        winning_wait_hand = [
            man(1), man(2), man(3),
            man(4), man(5), man(6),
            man(7), man(8), man(9),
            pin(1), pin(2), pin(3),
            pin(5),
        ]
        filler = [sou(1), sou(2), sou(4), sou(5), sou(7), sou(8),
                  RED_DRAGON, GREEN_DRAGON, WHITE_DRAGON, NORTH,
                  sou(3), sou(6), sou(9)]
        wall = [pin(5)] + filler  # next draw completes the win
        return GameState(
            wall=wall,
            hands=[winning_wait_hand, list(filler), list(filler), list(filler)],
            melds=[[], [], [], []],
            discards=[[], [], [], []],
            current_turn=0,
            phase="awaiting_draw",
            status="in_progress",
            winner=None,
            dealer=0,
            round_wind=EAST,
            seat_winds=[EAST, SOUTH, WEST, NORTH],
        )

    def test_declare_win_is_legal_after_drawing_the_completing_tile(self):
        state = self._tenpai_state()
        state = apply_action(state, {"type": "draw"})
        assert is_winning_hand(state.hands[0]) is True
        assert {"type": "declare_win"} in legal_actions(state)

    def test_declaring_win_terminates_the_game(self):
        state = self._tenpai_state()
        state = apply_action(state, {"type": "draw"})
        new_state = apply_action(state, {"type": "declare_win"})
        assert new_state.status == "self_draw_win"
        assert new_state.winner == 0
        assert legal_actions(new_state) == []

    def test_discarding_instead_of_declaring_keeps_the_game_going(self):
        # Winning is a choice, not forced: discarding the completing tile
        # (or any tile) must leave the game in progress.
        state = self._tenpai_state()
        state = apply_action(state, {"type": "draw"})
        new_state = apply_action(state, {"type": "discard", "tile": pin(5)})
        assert new_state.status == "in_progress"
        assert new_state.winner is None
        assert new_state.current_turn == 1


# --- heavenly hand reachability (the reason the dealer opens at 14) --------

class TestHeavenlyHandReachability:
    def test_dealer_can_declare_win_on_the_opening_fourteen_with_no_draw(self):
        # 天糊: dealer wins straight off the deal, before anyone -- including
        # themselves -- has drawn a single tile. Only reachable because the
        # dealer opens holding 14 tiles already, at 'awaiting_discard': no
        # 'draw' action happens before 'declare_win' becomes legal here.
        winning_hand = [
            man(1), man(2), man(3),
            man(4), man(5), man(6),
            man(7), man(8), man(9),
            pin(1), pin(2), pin(3),
            sou(5), sou(5),
        ]
        filler = [sou(1), sou(2), sou(3), sou(4), sou(6), sou(7), sou(8), sou(9),
                  RED_DRAGON, GREEN_DRAGON, WHITE_DRAGON, NORTH, WEST]
        state = GameState(
            wall=list(range(20)),  # arbitrary filler; untouched by this test
            hands=[winning_hand, list(filler), list(filler), list(filler)],
            melds=[[], [], [], []],
            discards=[[], [], [], []],
            current_turn=0,
            phase="awaiting_discard",
            status="in_progress",
            winner=None,
            dealer=0,
            round_wind=EAST,
            seat_winds=[EAST, SOUTH, WEST, NORTH],
        )
        assert is_winning_hand(state.hands[0]) is True
        assert {"type": "declare_win"} in legal_actions(state)

        new_state = apply_action(state, {"type": "declare_win"})
        assert new_state.status == "self_draw_win"
        assert new_state.winner == 0


# --- wall exhaustion (流局) ----------------------------------------------------

class TestWallExhaustion:
    def _play_until_terminal_never_declaring_win(self, state, max_steps=1000):
        """Auto-plays by always discarding (never declares a win, even when
        legal) so the game is driven deterministically to wall exhaustion
        regardless of whether a hand accidentally becomes winning along the
        way. Always discards the just-drawn tile, or the first tile in hand
        if not fresh off a draw."""
        for _ in range(max_steps):
            if state.status != "in_progress":
                return state
            if state.phase == "awaiting_draw":
                state = apply_action(state, {"type": "draw"})
            else:
                tile = state.hands[state.current_turn][0]
                state = apply_action(state, {"type": "discard", "tile": tile})
        raise AssertionError("game did not terminate within max_steps")

    def test_game_terminates_via_wall_exhaustion_when_no_win_is_declared(self):
        state = new_game(seed=1)
        final_state = self._play_until_terminal_never_declaring_win(state)
        assert final_state.status == "wall_exhausted"
        assert len(final_state.wall) == 0
        assert final_state.winner is None

    def test_tile_count_is_conserved_throughout_a_full_game(self):
        state = new_game(seed=1)
        assert total_tiles_in_play(state) == TOTAL_TILES
        for _ in range(1000):
            if state.status != "in_progress":
                break
            if state.phase == "awaiting_draw":
                state = apply_action(state, {"type": "draw"})
            else:
                tile = state.hands[state.current_turn][0]
                state = apply_action(state, {"type": "discard", "tile": tile})
            assert total_tiles_in_play(state) == TOTAL_TILES
        assert state.status == "wall_exhausted"

    def test_every_seat_ends_with_thirteen_concealed_tiles_at_wall_exhaustion(self):
        # No calls in this phase, so every hand should be back to exactly
        # 13 concealed tiles once the terminal discard has happened.
        state = new_game(seed=1)
        final_state = self._play_until_terminal_never_declaring_win(state)
        assert all(len(hand) == HAND_SIZE for hand in final_state.hands)
