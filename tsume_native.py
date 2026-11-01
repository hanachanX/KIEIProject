"""Optional native backend. The original tsume.py remains the reference implementation.

Use `import tsume_native as solver` to opt in. No automatic application switch.
"""
import ctypes
from pathlib import Path
import random
import threading

import shogi
from tsume import Pos, pos_from_board, show, TOTAL, UNPROM, PROM, SFEN_CH, JP

_local = threading.local()
_dll = None
_load_lock = threading.Lock()


def _library():
    global _dll
    with _load_lock:
        if _dll is None:
            path = Path(__file__).resolve().parent / "native_tsume" / "tsume.dll"
            if not path.is_file():
                raise RuntimeError("先に native_tsume/build.bat でDLLをビルドしてください。")
            lib = ctypes.CDLL(str(path))
            lib.tsume_create.argtypes = []
            lib.tsume_create.restype = ctypes.c_void_p
            lib.tsume_destroy.argtypes = [ctypes.c_void_p]
            lib.tsume_destroy.restype = None
            lib.tsume_error.argtypes = [ctypes.c_void_p]
            lib.tsume_error.restype = ctypes.c_char_p
            lib.tsume_run.argtypes = [
                ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p,
                ctypes.c_int, ctypes.c_int, ctypes.c_ulonglong,
                ctypes.c_int, ctypes.c_double, ctypes.c_void_p, ctypes.c_size_t,
            ]
            lib.tsume_run.restype = ctypes.c_int
            lib.tsume_copy_result.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
            lib.tsume_copy_result.restype = ctypes.c_int
            _dll = lib
    return _dll


class _Context:
    def __init__(self):
        self.lib = _library()
        self.ptr = self.lib.tsume_create()
        if not self.ptr:
            raise MemoryError("Cannot create native solver")

    def __del__(self):
        if getattr(self, "ptr", None):
            self.lib.tsume_destroy(self.ptr)
            self.ptr = None


TIMEOUT = 180.0   # 1回の計算の制限時間(秒)。超えると ValueError('timeout')


def _run(op, board=None, n=0, color=0, seed=0, budget=600, seconds=None, text=None):
    if seconds is None:
        seconds = TIMEOUT
    if not hasattr(_local, "context"):
        _local.context = _Context()
    ctx = _local.context
    if text is None:
        text = board.sfen() if board is not None else ""
    buf = ctypes.create_string_buffer(65536)
    size = ctx.lib.tsume_run(ctx.ptr, op.encode("ascii"), text.encode("ascii"),
                             n, color, seed, budget, seconds, buf, len(buf))
    if size < 0:
        raise ValueError(ctx.lib.tsume_error(ctx.ptr).decode("utf-8", errors="replace"))
    if size > len(buf):
        buf = ctypes.create_string_buffer(size)
        ctx.lib.tsume_copy_result(ctx.ptr, buf, len(buf))
    return buf.value.decode("ascii")


def _moves(text):
    return [shogi.Move.from_usi(m) for m in text.split()]


def clear_cache():
    """Clear caches belonging to the calling thread."""
    _run("clear")


def _board_moves(b, color):
    return _moves(_run("moves", b, color=color))


def _key(b):
    return b.sfen().rsplit(" ", 1)[0]


def _futile_interposition(b, d, a):
    return _run("futile", n=a, text=b.sfen() + "\n" + d.usi()) == "1"


def _capture_options(p, mover):
    return [(t, promoted) for t in TOTAL for promoted in ((False, True) if t in PROM else (False,))]


def _forward_matches(q, mv, p, mover):
    text = q.to_board(mover).sfen() + "\n" + p.to_board(mover).sfen() + "\n" + mv.usi()
    return _run("forward", color=mover, text=text) == "1"


def gen_checks(b):
    return _moves(_run("checks", b))


def gen_evasions(b):
    return _moves(_run("evasions", b))


def can_mate(b, plies):
    return _run("can_mate", b, n=plies) == "1"


def defenders_all_lose(b, plies):
    return _run("defenders", b, n=plies) == "1"


def solve(b, plies):
    return _moves(_run("solve", b, n=plies))


def mate_length_exact(b, n):
    return _run("exact", b, n=n) == "1"


def principal_line(b, n):
    result = _run("line", b, n=n)
    return None if result == "-" else _moves(result)


def verify(b, n):
    result = _run("verify", b, n=n)
    return None if result == "-" else _moves(result)


def _seed(rng):
    return (rng if rng is not None else random).getrandbits(64)


def _try_unmove(p, mover, want_turn_after=None):
    result = []
    for row in _run("unmove", p.to_board(mover), color=mover).splitlines():
        sfen, move = row.split("\t")
        result.append((pos_from_board(shogi.Board(sfen)), shogi.Move.from_usi(move)))
    return result


def _knight_lance_dead(p):
    return _run("dead", p.to_board(0)) == "1"


def _node_ok(q, mover, remaining):
    return _run("node", q.to_board(mover), n=remaining, color=mover) == "1"


def random_mate_position(rng):
    result = _run("random", seed=_seed(rng))
    return pos_from_board(shogi.Board(result)) if result else None


def _search(p, mover, r, n, rng, budget):
    result = _run("search", p.to_board(mover), n=n-r, color=mover,
                  seed=_seed(rng), budget=budget[0])
    sfen, remaining = result.split("\n")
    budget[0] = int(remaining)
    return None if sfen == "-" else pos_from_board(shogi.Board(sfen))


def generate(n_plies, rng=None, budget=600, time_limit=180):
    result = _run("generate", n=n_plies, seed=_seed(rng), budget=budget, seconds=time_limit)
    if not result:
        return None
    sfen, line = result.split("\n")
    return sfen, line.split()


def set_oracle(fn):
    """Optional: fn(sfen:str) -> 1 (mate under normal rules) / -1 (no mate) / 0 (unknown), or None to clear.
    Used by the native search to discard attacker positions that cannot be mate (an external fast engine answers).
    Needs a DLL built with tsume_set_oracle; returns False when the DLL does not have it."""
    if not hasattr(_local, "context"):
        _local.context = _Context()
    ctx = _local.context
    try:
        setter = ctx.lib.tsume_set_oracle
    except AttributeError:
        return False
    setter.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    setter.restype = None
    if fn is None:
        setter(ctx.ptr, None)
        _local.oracle_cb = None
        return True
    proto = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_char_p)

    def _cb(text):
        try:
            return int(fn(text.decode("ascii")))
        except Exception:
            return 0
    cb = proto(_cb)
    _local.oracle_cb = cb            # keep a reference so it is not garbage collected
    setter(ctx.ptr, ctypes.cast(cb, ctypes.c_void_p))
    return True


def oracle_stats():
    """(number of questions asked, number of positions discarded) in this thread's context."""
    try:
        a, b = _run("oracle_stats", text="").split()
        return int(a), int(b)
    except Exception:
        return 0, 0
