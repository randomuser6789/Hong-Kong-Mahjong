"""Tests for the game engine turn loop (RULES.md sections 1, 7, 8).

Target API (not yet implemented): mahjong/game.py

    GameState -- plain dataclass, fields:
        wall: list[int]            remaining tiles; wall[0] is drawn next
        hands: list[list[int]]     4 seats' concealed tiles
        melds: list[list[list[int]]]  4 seats' exposed melds; each seat's
                                    entry is a list of melds, each meld a
                                    list of exactly 3 tile ints. Only pung
                                    exists so far, so every meld is exposed
                                    (no concealed-kong case yet) -- storing
                                    them here at all is what lets a later
                                    scoring pass tell concealed vs. exposed
                                    apart (e.g. for 門前清 eligibility).
        discards: list[list[int]]  4 seats' discard piles, in order
        current_turn: int          seat index (0-3) currently acting -- the
                                    current player during normal turns, OR
                                    whichever seat is up to decide the front
                                    of pending_claims (see below)
        phase: str                 'awaiting_draw' | 'awaiting_discard' |
                                    'awaiting_claim_decision' |
                                    'awaiting_meld_discard'
        status: str                'in_progress' | 'self_draw_win' |
                                    'discard_win' | 'wall_exhausted'
        winner: int | None         seat index that won, else None
        dealer: int                seat index of the dealer
        round_wind: int            tile code 27-30
        seat_winds: list[int]      each seat's wind, tile code 27-30
        last_discard: int | None   tile under contest by pending_claims, else None
        last_discarder: int | None seat who discarded it, else None
        pending_claims: list[dict] ordered-by-priority queue of entries
                                    still outstanding on last_discard, only
                                    populated when phase ==
                                    'awaiting_claim_decision'. Each entry is
                                    {'seat': int, 'type': 'discard_win' |
                                    'pung' | 'chow'}; chow entries have an
                                    extra 'tiles': (a, b, c) -- the sorted
                                    3-tile run this specific chow option
                                    would form (see below).

                                    Priority order is win > pung/kong > chow
                                    (RULES.md section 7). Entries are
                                    grouped into GROUPS by (seat, type), in
                                    priority order -- that's the true unit
                                    of "one decision": all entries a single
                                    seat is being asked about at once for a
                                    single claim type. "The current
                                    decision" is always the entire front
                                    group, not just entry [0]:
                                    current_turn == pending_claims[0]['seat']
                                    == every other entry in that same
                                    group's seat, and likewise for type.
                                    Grouping by (seat, type) rather than by
                                    type alone matters because no claim type
                                    can ever span two seats on one discard
                                    today (see the per-tier reasoning
                                    below), so type alone happens to
                                    coincide with (seat, type) right now --
                                    but the engine keys on the full pair so
                                    it stays correct even if a future rule
                                    ever let one type apply to two seats at
                                    once (e.g. some house rules' 搶槓 variants
                                    let multiple seats rob the same kong).
                                      - win tier: at most 1 entry. 一炮多響
                                        (multiple simultaneous winners off
                                        one discard) is not used in this
                                        ruleset, so ties are broken by seat
                                        order -- the first seat in
                                        (discarder+1)%4, (discarder+2)%4,
                                        (discarder+3)%4 that can win takes
                                        it, even if a later seat in that
                                        rotation could also have won.
                                      - pung tier: at most 1 entry -- each
                                        tile type has only 4 copies total,
                                        so two DIFFERENT non-discarder seats
                                        each holding >=2 would require >=4
                                        copies among just the two of them,
                                        impossible.
                                      - chow tier: 0 or more entries, ALL
                                        for the SAME seat -- only
                                        (discarder+1)%4 may ever chow, but
                                        that seat's hand can support
                                        multiple distinct run shapes around
                                        the same discarded tile (e.g.
                                        holding 3/5/6 lets a discarded 4
                                        complete either 3-4-5 or 4-5-6),
                                        each its own entry so the player
                                        picks directly among them (like
                                        discard options), not one-at-a-time.

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
        If phase == 'awaiting_claim_decision': one action per entry in the
        front GROUP of pending_claims (every entry sharing BOTH
        pending_claims[0]['seat'] and pending_claims[0]['type']) --
        {'type': 'discard_win'} or {'type': 'pung'} (singletons), or one
        {'type': 'chow', 'tiles': (a, b, c)} per distinct chow entry in
        that group -- plus {'type': 'pass'}. The type/shape is derived
        from the queue, never hardcoded, so kong slots in later without
        changing this function.
        If phase == 'awaiting_discard': one {'type': 'discard', 'tile': t}
        per DISTINCT tile value in the current player's hand (sorted), plus
        {'type': 'declare_win'} iff the current 14-tile hand is currently a
        valid winning hand per mahjong.winning_hand.is_winning_hand. Declaring
        is a choice, not forced -- min-fan gating belongs to a later scoring
        pass, not this structural check.
        If phase == 'awaiting_meld_discard': discard options only, same
        rule as above but WITHOUT declare_win -- a claimed meld (pung or
        chow) can never itself complete a win (unlike robbing a kong,
        which doesn't exist yet), so it would be wrong to offer it here
        even if the 14 hand+meld tiles happen to look structurally complete.

    apply_action(state, action) -> GameState
        Pure function: returns a NEW GameState, does not mutate the input
        (including nested mutable fields -- melds/hands/discards are all
        copied, never aliased).
        'draw': moves wall[0] into the current player's hand, phase ->
            'awaiting_discard'.
        'discard': removes one copy of the tile from the current player's
            hand, appends it to their discard pile. Then gathers ALL
            eligible claims into pending_claims, group by group in
            priority order: discard-win (see the field docs above for the
            seat-order tiebreak), then pung, then chow (only
            (current_turn+1)%4 may chow; a suited
            tile T is chowable as (T,T+1,T+2)/(T-1,T,T+1)/(T-2,T-1,T)
            wherever that seat's hand holds the other two tiles of the
            shape; honors can never chow):
                - if pending_claims is non-empty: phase ->
                  'awaiting_claim_decision', current_turn ->
                  pending_claims[0]['seat'], last_discard/last_discarder ->
                  the tile/discarder.
                - otherwise: current_turn -> (current_turn + 1) % 4; if the
                  wall is now empty, status -> 'wall_exhausted' (this is
                  when 流局 is detected); else phase -> 'awaiting_draw'.
        'discard_win' (only legal when the front group's type is
            'discard_win'): the winning tile moves from the discarder's
            discard pile into the claiming seat's hand (13 -> 14, matching
            self-draw's hand size at a win). status -> 'discard_win',
            winner -> current_turn. last_discard/last_discarder -> None,
            pending_claims -> [].
        'pung' (only legal when the front group's type is 'pung'):
            removes 2 copies of last_discard from the claiming seat's
            hand, moves the pending tile OFF the discarder's discard pile
            and combines all 3 into one exposed meld appended to
            melds[current_turn]. current_turn stays put (the claimer),
            phase -> 'awaiting_meld_discard' (they discard next, no draw).
            last_discard/last_discarder -> None, pending_claims -> []
            (accepting voids every other pending claim on this same
            discard -- it can only be claimed once).
        'chow' (only legal when the front group's type is 'chow'; takes a
            'tiles': (a, b, c) matching one of the offered chow entries):
            removes the two tiles of (a, b, c) OTHER than last_discard
            from the claiming seat's hand, moves the pending tile OFF the
            discarder's discard pile, combines all 3 into one exposed
            meld appended to melds[current_turn]. Same
            current_turn-stays-put / 'awaiting_meld_discard' / cleared
            last_discard-last_discarder-pending_claims behavior as 'pung'.
        'pass' (only legal in 'awaiting_claim_decision'): drops the ENTIRE
            front GROUP -- every entry sharing BOTH pending_claims[0]['seat']
            and pending_claims[0]['type'] -- not just entry [0]. (Grouping
            by (seat, type) rather than type alone is what stays correct if
            a future rule ever let one type apply to two seats at once; see
            the pending_claims field docs above.) E.g. declining a chow
            declines all its variants at once, since they're really one
            decision ("do you want to chow at all") with multiple shapes.
            If claims remain, offers the next group: current_turn -> that
            group's seat, phase stays 'awaiting_claim_decision'. If none
            remain, resolves exactly like the "otherwise" branch of
            'discard' above, using
            last_discarder as the reference seat; last_discard/
            last_discarder -> None.
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
        + sum(len(meld) for seat_melds in state.melds for meld in seat_melds)
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
        legal) and always declining any pung offer, so the game is driven
        deterministically to wall exhaustion regardless of whether a hand
        accidentally becomes winning or pung-eligible along the way.
        Always discards the just-drawn tile, or the first tile in hand if
        not fresh off a draw."""
        for _ in range(max_steps):
            if state.status != "in_progress":
                return state
            if state.phase == "awaiting_draw":
                state = apply_action(state, {"type": "draw"})
            elif state.phase == "awaiting_claim_decision":
                state = apply_action(state, {"type": "pass"})
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
            elif state.phase == "awaiting_claim_decision":
                state = apply_action(state, {"type": "pass"})
            else:
                tile = state.hands[state.current_turn][0]
                state = apply_action(state, {"type": "discard", "tile": tile})
            assert total_tiles_in_play(state) == TOTAL_TILES
        assert state.status == "wall_exhausted"

    def test_every_seat_ends_with_thirteen_concealed_tiles_at_wall_exhaustion(self):
        # This auto-play always declines pungs, so no melds ever form and
        # every hand should be back to exactly 13 concealed tiles once the
        # terminal discard has happened.
        state = new_game(seed=1)
        final_state = self._play_until_terminal_never_declaring_win(state)
        assert all(len(hand) == HAND_SIZE for hand in final_state.hands)


# --- pung (碰) ------------------------------------------------------------

def _pung_scenario():
    """Seat 0 is about to discard T. Seat 2 is the ONLY seat holding two
    copies of T (eligible to pung); seats 1 and 3 hold none. This
    deliberately makes the eligible caller NOT the next-in-turn-order seat
    (seat 1), so claiming vs. declining produce visibly different turn
    destinations (jump to seat 2 vs. normal advance to seat 1)."""
    T = man(5)
    filler = [sou(1), sou(2), sou(3), sou(4), sou(6), sou(7), sou(8), sou(9), EAST, SOUTH, WEST]
    seat0_hand = [T, man(1), man(2), man(3), man(6), man(7), man(8),
                  pin(1), pin(2), pin(3), pin(6), pin(7), pin(8), sou(5)]
    seat1_hand = filler + [NORTH, RED_DRAGON]           # 13, zero copies of T
    seat2_hand = [T, T] + filler                        # 13, two copies of T (eligible)
    seat3_hand = filler + [GREEN_DRAGON, WHITE_DRAGON]  # 13, zero copies of T
    state = GameState(
        wall=[pin(9), sou(9), man(9)],
        hands=[seat0_hand, seat1_hand, seat2_hand, seat3_hand],
        melds=[[], [], [], []],
        discards=[[], [], [], []],
        current_turn=0,
        phase="awaiting_discard",
        status="in_progress",
        winner=None,
        dealer=0,
        round_wind=EAST,
        seat_winds=[EAST, SOUTH, WEST, NORTH],
        last_discard=None,
        last_discarder=None,
    )
    return state, T


class TestPung:
    def test_pung_is_offered_only_to_the_seat_holding_two_copies(self):
        state, T = _pung_scenario()
        after_discard = apply_action(state, {"type": "discard", "tile": T})
        assert after_discard.phase == "awaiting_claim_decision"
        assert after_discard.current_turn == 2  # the only seat with 2 copies
        assert after_discard.last_discard == T
        assert after_discard.last_discarder == 0
        assert after_discard.pending_claims == [{"seat": 2, "type": "pung"}]
        assert legal_actions(after_discard) == [{"type": "pung"}, {"type": "pass"}]

    def test_no_call_window_when_nobody_holds_two_copies(self):
        state, T = _pung_scenario()
        # Take seat 2's pung eligibility away (down to one copy of T) so
        # nobody in the hand qualifies.
        state.hands[2] = list(state.hands[2])
        state.hands[2].remove(T)
        after_discard = apply_action(state, {"type": "discard", "tile": T})
        assert after_discard.phase == "awaiting_draw"
        assert after_discard.current_turn == 1  # ordinary next seat
        assert legal_actions(after_discard) == [{"type": "draw"}]

    def test_claiming_pung_forms_the_meld_and_jumps_turn_to_the_claimer(self):
        state, T = _pung_scenario()
        after_discard = apply_action(state, {"type": "discard", "tile": T})
        claimed = apply_action(after_discard, {"type": "pung"})

        assert claimed.current_turn == 2  # jumped straight to the claimer, skipping seat 1
        assert claimed.phase == "awaiting_meld_discard"
        assert claimed.melds[2] == [[T, T, T]]
        assert claimed.hands[2].count(T) == 0
        assert len(claimed.hands[2]) == 11  # 13 - 2 claimed into the meld
        # the discarded tile moved out of the discard pile and into the meld
        assert claimed.discards[0] == []
        assert claimed.last_discard is None
        assert claimed.last_discarder is None
        assert claimed.pending_claims == []  # accepting voids the rest of the queue
        assert claimed.status == "in_progress"

    def test_claimer_discards_next_without_drawing(self):
        state, T = _pung_scenario()
        after_discard = apply_action(state, {"type": "discard", "tile": T})
        claimed = apply_action(after_discard, {"type": "pung"})

        actions = legal_actions(claimed)
        assert {"type": "draw"} not in actions
        assert all(a["type"] == "discard" for a in actions)  # no declare_win off a pung
        assert len(claimed.wall) == len(after_discard.wall)  # no draw happened

        tile_to_discard = claimed.hands[2][0]
        discarded = apply_action(claimed, {"type": "discard", "tile": tile_to_discard})
        assert len(discarded.hands[2]) == 10
        assert discarded.discards[2] == [tile_to_discard]
        assert len(discarded.wall) == len(after_discard.wall)  # still no draw

    def test_declining_the_pung_lets_normal_play_continue(self):
        state, T = _pung_scenario()
        after_discard = apply_action(state, {"type": "discard", "tile": T})
        passed = apply_action(after_discard, {"type": "pass"})

        assert passed.phase == "awaiting_draw"
        assert passed.current_turn == 1  # ordinary next seat, not the eligible seat
        assert passed.last_discard is None
        assert passed.last_discarder is None
        assert passed.pending_claims == []
        assert legal_actions(passed) == [{"type": "draw"}]
        assert passed.discards[0] == [T]  # nobody claimed it, so it stays put

    def test_tile_conservation_holds_across_a_pung_claim(self):
        state, T = _pung_scenario()
        baseline = total_tiles_in_play(state)
        assert baseline == 14 + 13 + 13 + 13 + 3  # 4 hands + wall; no discards/melds yet
        after_discard = apply_action(state, {"type": "discard", "tile": T})
        assert total_tiles_in_play(after_discard) == baseline
        claimed = apply_action(after_discard, {"type": "pung"})
        assert total_tiles_in_play(claimed) == baseline
        tile_to_discard = claimed.hands[2][0]
        discarded = apply_action(claimed, {"type": "discard", "tile": tile_to_discard})
        assert total_tiles_in_play(discarded) == baseline

    def test_pung_claim_does_not_mutate_the_parent_state(self):
        state, T = _pung_scenario()
        after_discard = apply_action(state, {"type": "discard", "tile": T})
        original_seat2_hand = list(after_discard.hands[2])
        original_discards0 = list(after_discard.discards[0])

        claimed = apply_action(after_discard, {"type": "pung"})
        claimed.hands[2].append(999)
        claimed.melds[2][0].append(999)
        claimed.discards[0].append(999)

        assert after_discard.hands[2] == original_seat2_hand
        assert after_discard.discards[0] == original_discards0
        assert after_discard.melds[2] == []


# --- discard win (食糊) and the within-tier seat-order tiebreak -------------

class TestDiscardWin:
    def _two_winners_scenario(self):
        """Seat 0 discards T. BOTH seat 1 and seat 2 can legally complete a
        winning hand with T (verified independently below) -- seat 1 via a
        tanki pair wait, seat 2 via a ryanmen chow wait, using entirely
        different tile groups so there's no overlap/coincidence between
        the two hands. Since 一炮多響 isn't used, only seat 1 (closer to
        the discarder in seat order) should ever appear as a claimant."""
        T = pin(5)
        seat0_hand = [T, WEST, WEST, WEST, NORTH, NORTH, NORTH,
                      RED_DRAGON, RED_DRAGON, RED_DRAGON,
                      GREEN_DRAGON, GREEN_DRAGON, WHITE_DRAGON, WHITE_DRAGON]
        seat1_hand = [man(1), man(2), man(3), man(4), man(5), man(6),
                      man(7), man(8), man(9), pin(1), pin(2), pin(3), pin(5)]
        seat2_hand = [sou(1), sou(2), sou(3), sou(4), sou(5), sou(6),
                      sou(7), sou(8), sou(9), pin(6), pin(7), EAST, EAST]
        seat3_hand = [pin(2), pin(2), pin(8), pin(8), sou(2), sou(2),
                      man(2), man(2), RED_DRAGON, RED_DRAGON,
                      GREEN_DRAGON, WHITE_DRAGON, NORTH]

        assert is_winning_hand(seat1_hand + [T]) is True
        assert is_winning_hand(seat2_hand + [T]) is True
        assert is_winning_hand(seat3_hand + [T]) is False

        state = GameState(
            wall=[man(9), man(8), man(7)],
            hands=[seat0_hand, seat1_hand, seat2_hand, seat3_hand],
            melds=[[], [], [], []],
            discards=[[], [], [], []],
            current_turn=0,
            phase="awaiting_discard",
            status="in_progress",
            winner=None,
            dealer=0,
            round_wind=EAST,
            seat_winds=[EAST, SOUTH, WEST, NORTH],
            last_discard=None,
            last_discarder=None,
        )
        return state, T

    def test_two_eligible_winners_resolve_to_the_seat_after_the_discarder(self):
        state, T = self._two_winners_scenario()
        after_discard = apply_action(state, {"type": "discard", "tile": T})

        assert after_discard.phase == "awaiting_claim_decision"
        # Only seat 1 -- (discarder + 1) % 4 -- appears, never seat 2, even
        # though seat 2 is also genuinely win-eligible on this same tile.
        assert after_discard.pending_claims == [{"seat": 1, "type": "discard_win"}]
        assert after_discard.current_turn == 1
        assert legal_actions(after_discard) == [{"type": "discard_win"}, {"type": "pass"}]

    def test_accepting_discard_win_moves_the_tile_into_the_winners_hand(self):
        state, T = self._two_winners_scenario()
        after_discard = apply_action(state, {"type": "discard", "tile": T})
        won = apply_action(after_discard, {"type": "discard_win"})

        assert won.status == "discard_win"
        assert won.winner == 1
        assert len(won.hands[1]) == 14
        assert won.hands[1].count(T) == 2  # the original tanki tile + the claimed one
        assert won.discards[0] == []  # claimed, not left on the discard pile
        assert won.pending_claims == []
        assert legal_actions(won) == []


# --- chow (上) ---------------------------------------------------------------

class TestChow:
    def test_chow_offered_only_to_the_seat_immediately_after_discarder(self):
        # Seat 0 discards T. Seat 2 holds tiles (pin6, pin7) that would
        # form a valid run with T, but seat 2 is NOT the discarder's
        # immediate next seat (seat 1 is) -- so no chow claim should ever
        # be generated for seat 2. Seat 1 (the actually-eligible seat)
        # holds nothing relevant, so no chow claim exists at all here.
        T = pin(5)
        seat0_hand = [T, man(1), man(2), man(3), man(6), man(7), man(8),
                      sou(1), sou(2), sou(3), sou(6), sou(7), sou(8), EAST]
        seat1_hand = [man(1), man(2), man(3), man(4), man(5), man(6),
                      man(7), man(8), man(9), sou(1), sou(2), NORTH, NORTH]
        seat2_hand = [pin(6), pin(7), sou(3), sou(4), sou(5), sou(6),
                      sou(7), sou(8), sou(9), RED_DRAGON, RED_DRAGON,
                      GREEN_DRAGON, WHITE_DRAGON]
        seat3_hand = [pin(1), pin(1), pin(2), pin(2), pin(8), pin(8),
                      pin(9), pin(9), sou(1), sou(1), GREEN_DRAGON,
                      GREEN_DRAGON, NORTH]
        state = GameState(
            wall=[man(9), man(8), man(7)],
            hands=[seat0_hand, seat1_hand, seat2_hand, seat3_hand],
            melds=[[], [], [], []],
            discards=[[], [], [], []],
            current_turn=0,
            phase="awaiting_discard",
            status="in_progress",
            winner=None,
            dealer=0,
            round_wind=EAST,
            seat_winds=[EAST, SOUTH, WEST, NORTH],
            last_discard=None,
            last_discarder=None,
        )
        after_discard = apply_action(state, {"type": "discard", "tile": T})

        assert after_discard.pending_claims == []
        assert after_discard.phase == "awaiting_draw"
        assert after_discard.current_turn == 1  # normal play, nobody claimed anything

    def _multiple_chow_shapes_scenario(self):
        # Seat 1 (eligible: discarder+1) holds pin3, pin5, pin6 -- around a
        # discarded pin4 that's exactly two distinct valid runs: 3-4-5 and
        # 4-5-6. It does NOT hold pin2, so 2-3-4 is not offered -- exactly
        # 2 chow options, not 3.
        T = pin(4)
        seat0_hand = [T, WEST, WEST, WEST, NORTH, NORTH, NORTH,
                      RED_DRAGON, RED_DRAGON, RED_DRAGON,
                      GREEN_DRAGON, GREEN_DRAGON, WHITE_DRAGON, WHITE_DRAGON]
        seat1_hand = [pin(3), pin(5), pin(6), man(1), man(2), man(3),
                      man(4), man(5), man(6), man(7), man(8), sou(1), sou(2)]
        seat2_hand = [sou(3), sou(3), sou(4), sou(4), sou(5), sou(5),
                      sou(6), sou(6), sou(7), sou(7), sou(8), sou(8), sou(9)]
        seat3_hand = [man(9), man(9), pin(9), pin(9), sou(1), sou(1),
                      EAST, EAST, SOUTH, SOUTH, GREEN_DRAGON, WHITE_DRAGON, NORTH]
        state = GameState(
            wall=[man(9), man(8), man(7)],
            hands=[seat0_hand, seat1_hand, seat2_hand, seat3_hand],
            melds=[[], [], [], []],
            discards=[[], [], [], []],
            current_turn=0,
            phase="awaiting_discard",
            status="in_progress",
            winner=None,
            dealer=0,
            round_wind=EAST,
            seat_winds=[EAST, SOUTH, WEST, NORTH],
            last_discard=None,
            last_discarder=None,
        )
        return state, T

    def test_all_distinct_chow_shapes_are_enumerated_as_separate_actions(self):
        state, T = self._multiple_chow_shapes_scenario()
        after_discard = apply_action(state, {"type": "discard", "tile": T})

        assert after_discard.phase == "awaiting_claim_decision"
        assert after_discard.current_turn == 1
        assert after_discard.pending_claims == [
            {"seat": 1, "type": "chow", "tiles": (pin(3), pin(4), pin(5))},
            {"seat": 1, "type": "chow", "tiles": (pin(4), pin(5), pin(6))},
        ]
        assert legal_actions(after_discard) == [
            {"type": "chow", "tiles": (pin(3), pin(4), pin(5))},
            {"type": "chow", "tiles": (pin(4), pin(5), pin(6))},
            {"type": "pass"},
        ]

    def test_claiming_one_chow_shape_consumes_only_that_shapes_tiles(self):
        state, T = self._multiple_chow_shapes_scenario()
        after_discard = apply_action(state, {"type": "discard", "tile": T})
        claimed = apply_action(after_discard, {"type": "chow", "tiles": (pin(4), pin(5), pin(6))})

        assert claimed.current_turn == 1
        assert claimed.phase == "awaiting_meld_discard"
        assert claimed.melds[1] == [[pin(4), pin(5), pin(6)]]
        assert sorted(claimed.hands[1]) == sorted(
            [pin(3), man(1), man(2), man(3), man(4), man(5), man(6), man(7), man(8), sou(1), sou(2)]
        )
        assert len(claimed.hands[1]) == 11  # 13 - 2 claimed into the meld
        assert claimed.discards[0] == []  # the discarded tile moved into the meld
        assert claimed.pending_claims == []  # the other shape is moot once one is claimed
        assert claimed.last_discard is None
        assert claimed.last_discarder is None

    def test_pung_beats_chow_priority_on_the_same_discard(self):
        # Seat 1 (the only chow-eligible seat) ALSO holds 2 copies of the
        # discarded tile, so it's eligible for both pung and a chow (using
        # pin5, pin6 for the 4-5-6 run). Pung must be offered alone first.
        T = pin(4)
        seat0_hand = [T, man(1), man(1), man(1), sou(1), sou(1), sou(1),
                      EAST, EAST, EAST, WEST, WEST, NORTH, NORTH]
        seat1_hand = [pin(4), pin(4), pin(5), pin(6), man(2), man(3),
                      man(4), man(5), man(6), man(7), man(8), sou(2), sou(3)]
        seat2_hand = [sou(4), sou(4), sou(5), sou(5), sou(6), sou(6),
                      sou(7), sou(7), sou(8), sou(8), sou(9), sou(9), man(9)]
        seat3_hand = [man(9), pin(9), pin(9), sou(1), sou(1), EAST,
                      SOUTH, SOUTH, GREEN_DRAGON, GREEN_DRAGON,
                      WHITE_DRAGON, WHITE_DRAGON, NORTH]
        state = GameState(
            wall=[man(9), man(8), man(7)],
            hands=[seat0_hand, seat1_hand, seat2_hand, seat3_hand],
            melds=[[], [], [], []],
            discards=[[], [], [], []],
            current_turn=0,
            phase="awaiting_discard",
            status="in_progress",
            winner=None,
            dealer=0,
            round_wind=EAST,
            seat_winds=[EAST, SOUTH, WEST, NORTH],
            last_discard=None,
            last_discarder=None,
        )
        after_discard = apply_action(state, {"type": "discard", "tile": T})

        # Pung tier offered alone first, even though seat 1's chow option
        # is also legitimately available.
        assert after_discard.pending_claims == [
            {"seat": 1, "type": "pung"},
            {"seat": 1, "type": "chow", "tiles": (pin(4), pin(5), pin(6))},
        ]
        assert legal_actions(after_discard) == [{"type": "pung"}, {"type": "pass"}]

        # Declining pung reveals the chow option next.
        after_pass = apply_action(after_discard, {"type": "pass"})
        assert after_pass.phase == "awaiting_claim_decision"
        assert after_pass.current_turn == 1
        assert after_pass.pending_claims == [
            {"seat": 1, "type": "chow", "tiles": (pin(4), pin(5), pin(6))},
        ]
        assert legal_actions(after_pass) == [
            {"type": "chow", "tiles": (pin(4), pin(5), pin(6))},
            {"type": "pass"},
        ]

    def test_tile_conservation_holds_across_a_chow_claim(self):
        state, T = self._multiple_chow_shapes_scenario()
        baseline = total_tiles_in_play(state)
        after_discard = apply_action(state, {"type": "discard", "tile": T})
        assert total_tiles_in_play(after_discard) == baseline
        claimed = apply_action(after_discard, {"type": "chow", "tiles": (pin(3), pin(4), pin(5))})
        assert total_tiles_in_play(claimed) == baseline
        tile_to_discard = claimed.hands[1][0]
        discarded = apply_action(claimed, {"type": "discard", "tile": tile_to_discard})
        assert total_tiles_in_play(discarded) == baseline

    def test_declining_two_chow_variants_clears_both_in_one_pass_without_touching_a_different_seats_pung(self):
        # A manually-built queue (not derived from a real discard, like
        # TestClaimQueueGeneralizes): seat 1 has two chow variants, and
        # seat 2 has an unrelated pung entry sitting right after them in
        # the list. Real _gather_pending_claims would never order pung
        # after chow (pung outranks chow), but this directly pressure-
        # tests the 'pass' filter itself: it must drop the entire front
        # GROUP -- every entry sharing both pending_claims[0]['seat'] AND
        # pending_claims[0]['type'] -- not by position, not by "everything
        # after index 0". Both chow variants here share seat AND type, so
        # this test alone can't distinguish "group by (seat, type)" from
        # "group by type alone"; see
        # test_pass_groups_by_seat_and_type_not_by_type_alone below for
        # that. What THIS test does confirm: both chow variants disappear
        # in a single pass (the seat is never asked about the second
        # variant separately), while the trailing pung entry for the
        # OTHER seat survives untouched and becomes the next thing offered.
        state = GameState(
            wall=[man(9), man(8)],
            hands=[
                [man(1), man(2), man(3), man(4), man(5), man(6), man(7),
                 pin(1), pin(2), pin(3), pin(4), pin(5), pin(6), pin(7)],
                [pin(3), pin(5), pin(6), man(1), man(2), man(3), man(4),
                 man(5), man(6), man(7), man(8), sou(1), sou(2)],
                [pin(4), pin(4), sou(3), sou(4), sou(5), sou(6), sou(7),
                 sou(8), sou(9), EAST, EAST, SOUTH, WEST],
                [man(4), man(5), man(6), man(7), man(8), man(9),
                 pin(8), pin(9), sou(4), sou(5), sou(6), sou(7), sou(8)],
            ],
            melds=[[], [], [], []],
            discards=[[], [], [], []],
            current_turn=1,
            phase="awaiting_claim_decision",
            status="in_progress",
            winner=None,
            dealer=0,
            round_wind=EAST,
            seat_winds=[EAST, SOUTH, WEST, NORTH],
            last_discard=pin(4),
            last_discarder=0,
            pending_claims=[
                {"seat": 1, "type": "chow", "tiles": (pin(3), pin(4), pin(5))},
                {"seat": 1, "type": "chow", "tiles": (pin(4), pin(5), pin(6))},
                {"seat": 2, "type": "pung"},
            ],
        )

        assert legal_actions(state) == [
            {"type": "chow", "tiles": (pin(3), pin(4), pin(5))},
            {"type": "chow", "tiles": (pin(4), pin(5), pin(6))},
            {"type": "pass"},
        ]

        after_pass = apply_action(state, {"type": "pass"})

        # Both chow variants gone in ONE pass -- not just the front entry.
        assert after_pass.pending_claims == [{"seat": 2, "type": "pung"}]
        # The unrelated pung tier for seat 2 survived and is now offered.
        assert after_pass.phase == "awaiting_claim_decision"
        assert after_pass.current_turn == 2
        assert legal_actions(after_pass) == [{"type": "pung"}, {"type": "pass"}]
        # The original discard context is preserved -- it's still the
        # same physical tile under contest, just a different claimant.
        assert after_pass.last_discard == pin(4)
        assert after_pass.last_discarder == 0

        # Original state (and its claims list) must be untouched.
        assert state.pending_claims == [
            {"seat": 1, "type": "chow", "tiles": (pin(3), pin(4), pin(5))},
            {"seat": 1, "type": "chow", "tiles": (pin(4), pin(5), pin(6))},
            {"seat": 2, "type": "pung"},
        ]

    def test_pass_groups_by_seat_and_type_not_by_type_alone(self):
        # No real rule lets 'chow' apply to two different seats on the
        # same discard -- only (discarder+1)%4 may ever chow -- so this
        # two-seat-same-type queue is synthetic (like
        # TestClaimQueueGeneralizes' 'future_claim'), built directly
        # rather than derived from a real discard. Its only purpose is to
        # fork the two possible 'pass' implementations, which agree on
        # every OTHER test in this file: "drop entries where type matches
        # the front" vs. the intended "drop entries where (seat, type)
        # matches the front." If the impl keyed on type alone, passing
        # here would wrongly wipe out seat 2's entry too, since it also
        # happens to be typed 'chow'.
        state = GameState(
            wall=[man(9)],
            hands=[
                [man(1), man(2), man(3), man(4), man(5), man(6), man(7),
                 pin(1), pin(2), pin(3), pin(4), pin(5), pin(6), pin(7)],
                [pin(2), pin(3), man(1), man(2), man(3), man(4), man(5),
                 man(6), man(7), man(8), sou(1), sou(2), sou(3)],
                [pin(2), pin(3), sou(4), sou(5), sou(6), sou(7), sou(8),
                 sou(9), EAST, EAST, SOUTH, WEST, NORTH],
                [man(4), man(5), man(6), man(7), man(8), man(9),
                 pin(8), pin(9), sou(4), sou(5), sou(6), sou(7), sou(8)],
            ],
            melds=[[], [], [], []],
            discards=[[], [], [], []],
            current_turn=1,
            phase="awaiting_claim_decision",
            status="in_progress",
            winner=None,
            dealer=0,
            round_wind=EAST,
            seat_winds=[EAST, SOUTH, WEST, NORTH],
            last_discard=pin(4),
            last_discarder=0,
            pending_claims=[
                {"seat": 1, "type": "chow", "tiles": (pin(2), pin(3), pin(4))},
                {"seat": 2, "type": "chow", "tiles": (pin(2), pin(3), pin(4))},
            ],
        )

        after_pass = apply_action(state, {"type": "pass"})

        # Only seat 1's entry (the front GROUP: seat=1 AND type='chow')
        # was dropped. Seat 2's same-typed entry must survive and become
        # the next thing offered -- a type-only filter would have dropped
        # it too and resumed normal play instead.
        assert after_pass.pending_claims == [
            {"seat": 2, "type": "chow", "tiles": (pin(2), pin(3), pin(4))},
        ]
        assert after_pass.phase == "awaiting_claim_decision"
        assert after_pass.current_turn == 2
        assert legal_actions(after_pass) == [
            {"type": "chow", "tiles": (pin(2), pin(3), pin(4))},
            {"type": "pass"},
        ]


class TestClaimQueueGeneralizes:
    """discard_win/pung/chow are real now, but kong (also pung-tier) still
    isn't. These tests drive the queue mechanics directly with a
    hand-built, multi-entry pending_claims (including a made-up
    'future_claim' type standing in for kong), to prove the offer/accept/
    pass machinery itself -- not just any one claim type's correctness --
    already handles more than one outstanding tier on the same discard
    without any further rework."""

    def _two_claim_state(self):
        return GameState(
            wall=[man(9), man(8)],
            hands=[
                [man(1), man(2), man(3), man(4), man(5), man(6), man(7),
                 pin(1), pin(2), pin(3), pin(4), pin(5), pin(6), pin(7)],
                [sou(1), sou(2), sou(3), sou(4), sou(5), sou(6), sou(7),
                 sou(8), sou(9), EAST, SOUTH, WEST, NORTH],
                [RED_DRAGON, RED_DRAGON, GREEN_DRAGON, GREEN_DRAGON,
                 WHITE_DRAGON, WHITE_DRAGON, man(1), man(2), man(3),
                 pin(1), pin(2), pin(3), sou(1)],
                [man(4), man(5), man(6), man(7), man(8), man(9),
                 pin(4), pin(5), pin(6), pin(7), pin(8), pin(9), sou(2)],
            ],
            melds=[[], [], [], []],
            discards=[[], [], [], []],
            current_turn=2,
            phase="awaiting_claim_decision",
            status="in_progress",
            winner=None,
            dealer=0,
            round_wind=EAST,
            seat_winds=[EAST, SOUTH, WEST, NORTH],
            last_discard=man(5),
            last_discarder=0,
            pending_claims=[
                {"seat": 2, "type": "pung"},
                {"seat": 3, "type": "future_claim"},
            ],
        )

    def test_legal_actions_reflects_the_front_claims_type_not_a_hardcoded_one(self):
        state = self._two_claim_state()
        assert legal_actions(state) == [{"type": "pung"}, {"type": "pass"}]

    def test_declining_the_front_claim_offers_the_next_one_in_queue(self):
        state = self._two_claim_state()
        after_first_pass = apply_action(state, {"type": "pass"})

        assert after_first_pass.phase == "awaiting_claim_decision"
        assert after_first_pass.current_turn == 3  # jumped to the second claimant
        assert after_first_pass.pending_claims == [{"seat": 3, "type": "future_claim"}]
        # last_discard/last_discarder are preserved -- the same physical
        # tile is still under contest, just by a different claimant now.
        assert after_first_pass.last_discard == man(5)
        assert after_first_pass.last_discarder == 0
        assert legal_actions(after_first_pass) == [{"type": "future_claim"}, {"type": "pass"}]

    def test_declining_every_claim_in_the_queue_resumes_normal_play(self):
        state = self._two_claim_state()
        after_first_pass = apply_action(state, {"type": "pass"})
        after_second_pass = apply_action(after_first_pass, {"type": "pass"})

        assert after_second_pass.phase == "awaiting_draw"
        assert after_second_pass.current_turn == 1  # (last_discarder=0) + 1
        assert after_second_pass.pending_claims == []
        assert after_second_pass.last_discard is None
        assert after_second_pass.last_discarder is None
        assert legal_actions(after_second_pass) == [{"type": "draw"}]

    def test_passing_the_queue_does_not_mutate_the_parent_states_claims(self):
        state = self._two_claim_state()
        after_first_pass = apply_action(state, {"type": "pass"})
        after_first_pass.pending_claims.append({"seat": 99, "type": "sabotage"})
        after_first_pass.pending_claims[0]["seat"] = 99

        assert state.pending_claims == [
            {"seat": 2, "type": "pung"},
            {"seat": 3, "type": "future_claim"},
        ]
