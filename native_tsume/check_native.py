"""Differential checks against the unchanged Python implementation.

Run from any directory: python native_tsume/check_native.py
"""
import ctypes
import json
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import shogi
import tsume as reference
import tsume_native as native


def move_set(moves):
    return {m.usi() for m in moves}


def same(label, a, b, board):
    if a != b:
        raise AssertionError(f"{label}\n{board.sfen()}\nPython: {a}\nNative: {b}")


def main():
    if ctypes.sizeof(ctypes.c_void_p) != 8:
        raise SystemExit("64-bit Python required")
    records = [json.loads(row) for row in (ROOT / "tsume_db.jsonl").read_text(encoding="utf-8").splitlines() if row.strip()]
    counts = {"positions": 0, "searches": 0, "inverse": 0, "generated": 0}
    finals = []
    started = time.perf_counter()
    skip_corpus = "--skip-corpus" in sys.argv
    for record in ([] if skip_corpus else records):
        board = shogi.Board(record["sfen"])
        moves = record.get("line", [])
        # Initial position, last three plies, and regular samples of the main line.
        checkpoints = {0, max(0, len(moves)-3), max(0, len(moves)-2), max(0, len(moves)-1), len(moves)}
        checkpoints.update(range(0, len(moves), 12))
        for i in range(len(moves)+1):
            if i in checkpoints:
                before = board.sfen()
                if board.turn == shogi.BLACK:
                    same("checks", move_set(reference.gen_checks(board)), move_set(native.gen_checks(board)), board)
                else:
                    same("evasions", move_set(reference.gen_evasions(board)), move_set(native.gen_evasions(board)), board)
                same("input unchanged", before, board.sfen(), board)
                counts["positions"] += 1
                if i == len(moves)-1 and board.turn == shogi.BLACK:
                    finals.append(board.sfen())
            if i < len(moves):
                board.push_usi(moves[i])
        if counts["positions"] % 100 < 12:
            print(f"Compared {counts['positions']} positions", flush=True)

    if skip_corpus:
        for record in records[:12]:
            b = shogi.Board(record["sfen"])
            for move in record["line"][:-1]:
                b.push_usi(move)
            finals.append(b.sfen())
    for sfen in finals[:12]:
        board = shogi.Board(sfen)
        for depth in (1,):
            same("can_mate", reference.can_mate(board, depth), native.can_mate(board, depth), board)
            same("solve", move_set(reference.solve(board, depth)), move_set(native.solve(board, depth)), board)
            same("exact", reference.mate_length_exact(board, depth), native.mate_length_exact(board, depth), board)
            counts["searches"] += 1
        for fn in ("principal_line", "verify"):
            # The reference principal_line can leave its input changed on failure.
            a = getattr(reference, fn)(shogi.Board(sfen), 1)
            b = getattr(native, fn)(board, 1)
            same(fn, None if a is None else move_set(a), None if b is None else move_set(b), board)

    for sfen in finals[:5]:
        p = reference.pos_from_board(shogi.Board(sfen))
        for mover in (0, 1):
            def inverse(module):
                return {(q.to_board(mover).sfen(), m.usi()) for q, m in module._try_unmove(p, mover, None)}
            same("inverse", inverse(reference), inverse(native), p.to_board(mover))
            same("dead", reference._knight_lance_dead(p), native._knight_lance_dead(p), p.to_board(mover))
            counts["inverse"] += 1

    # Exercise both success and deadline expiry. Native RNG differs from Python's.
    for depth in (1, 3):
        rng = random.Random(20261031 + depth)
        result = native.generate(depth, rng, budget=600, time_limit=15)
        if result is None:
            raise AssertionError(f"No generated {depth}-ply problem within 15s")
        sfen, moves = result
        a = reference.verify(shogi.Board(sfen), depth)
        if a is None or [m.usi() for m in a] != moves:
            raise AssertionError(f"Generated problem rejected by Python: {result}")
        counts["generated"] += 1
        print(f"Generated and verified {depth}-ply: {sfen} / {' '.join(moves)}", flush=True)
    assert native.generate(3, random.Random(0), time_limit=0) is None
    try:
        native.generate(2, time_limit=0)
    except ValueError:
        pass
    else:
        raise AssertionError("Even depth must be rejected")

    # Independent context per worker thread, with the GIL released during DLL calls.
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=4) as pool:
        values = list(pool.map(lambda s: native.can_mate(shogi.Board(s), 1), finals[:16]))
    assert values == [reference.can_mate(shogi.Board(s), 1) for s in finals[:16]]
    print(f"PASS {counts}; elapsed={time.perf_counter()-started:.2f}s", flush=True)

    # Use small explicit positions for the timed depth-3 benchmark. In classical
    # endings, enumerating every winning move at depth 3 can itself be expensive.
    samples = ["4k4/9/4G4/9/9/9/9/9/9 b G 1",
               "4k4/9/4G4/9/9/9/9/9/9 b S 1"]
    for sfen in samples:
        board = shogi.Board(sfen)
        same("depth3", move_set(reference.solve(board, 3)), move_set(native.solve(board, 3)), board)
        counts["searches"] += 1
    for module in (reference, native):
        module.clear_cache()
        t0 = time.perf_counter()
        for sfen in samples:
            module.solve(shogi.Board(sfen), 3)
        print(f"{module.__name__}: solve(depth=3), {len(samples)} positions: {time.perf_counter()-t0:.4f}s")


if __name__ == "__main__":
    main()
