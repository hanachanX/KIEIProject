"""Targeted compatibility and C ABI checks. No additional test packages needed."""
from pathlib import Path
import ctypes
import random
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import shogi
import tsume as reference
import tsume_native as native


def board(pieces, black=None, white=None, turn=0):
    b = shogi.Board()
    b.clear()
    for square, symbol in pieces.items():
        b.set_piece_at(square, shogi.Piece.from_symbol(symbol))
    for c, h in enumerate((black or {}, white or {})):
        for pt, count in h.items():
            b.add_piece_into_hand(pt, c, count)
    b.turn = turn
    return b


def main():
    count = 0
    cases = [
        # Pawn-drop mate, escape available, double pawn.
        board({4: 'k', 22: 'G'}, {shogi.PAWN: 1, shogi.GOLD: 1}),
        board({4: 'k'}, {shogi.PAWN: 1}),
        board({4: 'k', 40: 'P'}, {shogi.PAWN: 1}),
        # Slider check, interposition, promotion, two checks, attacker king.
        board({4: 'k', 40: 'R'}, white={shogi.PAWN: 2, shogi.GOLD: 1}, turn=1),
        board({4: 'k', 22: 'R', 12: 'B'}, white={shogi.SILVER: 1}, turn=1),
        board({4: 'k', 13: 'P', 20: 'N', 23: 'L', 21: 'S'}),
        board({4: 'k', 76: 'K', 67: 'G', 40: 'r'}, {shogi.GOLD: 1}),
    ]
    rng = random.Random(831)
    # Random sparse positions cover blockers and every promoted piece type.
    types = [p for p in range(1, 15) if p != shogi.KING]
    for _ in range(100):
        squares = rng.sample(range(81), rng.randint(3, 10))
        pieces = {squares[0]: 'k'}
        for s in squares[1:]:
            pieces[s] = shogi.Piece(rng.choice(types), rng.randrange(2)).symbol()
        cases.append(board(pieces, {p: 1 for p in range(1, 8)},
                           {p: 1 for p in range(1, 8)}, rng.randrange(2)))

    for b in cases:
        before = b.sfen()
        for color in (0, 1):
            a = {m.usi() for m in reference._board_moves(b, color)}
            c = {m.usi() for m in native._board_moves(b, color)}
            assert a == c, (b.sfen(), a ^ c)
        candidates = reference._board_moves(b, b.turn)
        candidates += [shogi.Move(None, s, False, p) for s in range(81)
                       for p in range(1, 8) if not b.piece_at(s)]
        # All moves for targeted fixtures, sample for random boards.
        if count >= 7:
            candidates = rng.sample(candidates, min(35, len(candidates)))
        for move in candidates:
            for name, fn in (("pseudo", b.is_pseudo_legal), ("legal", b.is_legal)):
                expected = fn(move)
                actual = native._run(name, text=b.sfen()+"\n"+move.usi()) == "1"
                assert expected == actual, (name, b.sfen(), move.usi(), expected, actual)
        fn = "gen_checks" if b.turn == 0 else "gen_evasions"
        a = {m.usi() for m in getattr(reference, fn)(b)}
        c = {m.usi() for m in getattr(native, fn)(b)}
        assert a == c, (fn, b.sfen(), a ^ c)
        assert b.sfen() == before
        count += 1

    # Private helper boundaries and inverse forward matching.
    p = reference.Pos({4: (shogi.KING, 1), 13: (shogi.GOLD, 0),
                       22: (shogi.GOLD, 0)}, {})
    for q, move in native._try_unmove(p, 0)[:100]:
        assert reference._forward_matches(q, move, p, 0) == native._forward_matches(q, move, p, 0)
    assert native._capture_options(p, 0) == reference._capture_options(p, 0)
    for seed in range(4):
        p = native.random_mate_position(random.Random(seed))
        if p:
            assert p.valid_counts() and reference._knight_lance_dead(p)
            assert p.to_board(1).is_checkmate()

    # Native error and buffer contracts.
    lib = native._library()
    ptr = lib.tsume_create()
    try:
        sentinel = ctypes.create_string_buffer(b"unchanged")
        sfen = cases[0].sfen().encode("ascii")
        size = lib.tsume_run(ptr, b"checks", sfen, 0, 0, 0, 1, 0, sentinel, 1)
        assert size > 1 and sentinel.value == b"unchanged"
        output = ctypes.create_string_buffer(size)
        assert lib.tsume_copy_result(ptr, output, len(output)) == size
        assert output.value.decode() == native._run("checks", cases[0])
        assert lib.tsume_run(ptr, b"checks", b"bad", 0, 0, 0, 1, 0, output, len(output)) == -1
        assert lib.tsume_error(ptr)
        assert lib.tsume_run(ptr, b"unknown", sfen, 0, 0, 0, 1, 0, output, len(output)) == -1
    finally:
        lib.tsume_destroy(ptr)
    print(f"PASS: {count} targeted/random boards, move legality, inverse helpers, random endings, C ABI")


if __name__ == "__main__":
    main()
