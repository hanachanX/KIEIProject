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


CACHE_CAP = 0   # 記憶する局面の上限（0=DLLの既定。大きいほど速いがメモリを使う）。set_cache_cap で変える
TIMEOUT = 180.0   # 1回の計算の制限時間(秒)。超えると ValueError('timeout')
_cancelled = False


def set_deadline(t):
    """この呼び出しスレッドの、全体の締め切り（time.time()の値、None=なし）。過ぎたら、以後の計算はすぐ打ち切る。"""
    _local.deadline = t


def cancel(on=True):
    """実行中の計算を止める（on=False で解除）。別のスレッドから呼んでよい。古いDLLでは、次の呼び出しから止まる。"""
    global _cancelled
    _cancelled = bool(on)
    try:
        f = _library().tsume_cancel
        f.argtypes = [ctypes.c_int]
        f.restype = None
        f(1 if on else 0)
    except (AttributeError, RuntimeError, OSError):
        pass


class CancelEvent(threading.Event):
    """threading.Event と同じ使い方ができる中断フラグ。set() で、実行中のDLLの計算も止める。"""
    def set(self):
        super().set()
        cancel(True)

    def clear(self):
        super().clear()
        cancel(False)


def _run(op, board=None, n=0, color=0, seed=0, budget=600, seconds=None, text=None):
    if seconds is None:
        seconds = TIMEOUT
    if _cancelled:
        raise ValueError("timeout (cancelled)")
    dl = getattr(_local, "deadline", None)
    if dl is not None:
        import time as _t
        left = dl - _t.time()
        if left <= 0:
            raise ValueError("timeout (deadline)")
        seconds = min(seconds, left)
    if not hasattr(_local, "context"):
        _local.context = _Context()
    ctx = _local.context
    if getattr(ctx, "cap", None) != CACHE_CAP:
        ctx.cap = CACHE_CAP
        if CACHE_CAP:
            try:
                ctx.lib.tsume_run(ctx.ptr, b"cap", b"", int(CACHE_CAP), 0, 0, 0, 0.0,
                                  ctypes.create_string_buffer(64), 64)
            except Exception:
                pass          # 古いDLLには無い機能。そのまま従来どおり動く
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


class ContextStop:
    """Thread-safe stop handle; bind on the worker, close only after it is idle."""
    def __init__(self):
        self._lock = threading.Lock()
        self._requested = False
        self._ctx = None
        self._fn = None

    def bind(self):
        if not hasattr(_local, "context"):
            _local.context = _Context()
        ctx = _local.context
        try:
            fn = ctx.lib.tsume_cancel_context
        except AttributeError as exc:
            raise RuntimeError("並行探索に対応したDLLへの更新と、アプリの再起動が必要です。") from exc
        fn.argtypes = [ctypes.c_void_p, ctypes.c_int]
        fn.restype = None
        with self._lock:
            self._ctx, self._fn = ctx, fn
            fn(ctx.ptr, int(self._requested))
        return self

    def stop(self):
        with self._lock:
            self._requested = True
            if self._fn is not None:
                self._fn(self._ctx.ptr, 1)

    def is_stopped(self):
        with self._lock:
            return self._requested

    def rearm(self):
        with self._lock:
            self._requested = False
            if self._fn is not None:
                self._fn(self._ctx.ptr, 0)

    def close(self):
        with self._lock:
            if self._fn is not None:
                self._fn(self._ctx.ptr, 0)
            self._ctx, self._fn = None, None


class SearchProgress:
    """Aggregate native visits for a whole job on the calling worker thread.

    snapshot() is safe for a display thread: each update replaces the dictionary.
    NPS uses total wall time, including time between native operations.
    """
    def __init__(self):
        self.stats = None
        self._total = 0
        self._setter = None
        self._callback = None

    def __enter__(self):
        import time
        self._started = time.monotonic()
        if not hasattr(_local, "context"):
            _local.context = _Context()
        self._ctx = _local.context
        try:
            setter = self._ctx.lib.tsume_set_search_progress
        except AttributeError:
            return self  # Older DLL: do not invent a zero count.
        setter.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        setter.restype = None
        def report(nodes, seconds, phase):
            if phase == 0:
                self._total += int(nodes)
                count = self._total
            else:
                count = self._total + int(nodes)
            self.stats = {"nodes": count}
        self._callback = ctypes.CFUNCTYPE(None, ctypes.c_ulonglong, ctypes.c_double, ctypes.c_int)(report)
        setter(self._ctx.ptr, ctypes.cast(self._callback, ctypes.c_void_p))
        self._setter = setter
        self.stats = {"nodes": 0}
        return self

    def snapshot(self):
        import time
        if self.stats is None:
            return None
        return {**self.stats, "search_seconds": max(0.0, time.monotonic() - self._started)}

    def close(self):
        if self._setter is not None:
            self._setter(self._ctx.ptr, None)
            self._setter = None
            self._callback = None

    def __exit__(self, *args):
        self.close()


def _moves(text):
    return [shogi.Move.from_usi(m) for m in text.split()]


def set_cache_cap(n):
    """記憶する局面の上限を決める（0=DLLの既定）。次の計算から効く。メモリの目安：1000万件で約350MB。"""
    global CACHE_CAP
    CACHE_CAP = max(0, int(n))


def set_floor(k):
    """無駄合の判定に使う手数の下限を設ける（0で解除）。浅い探索でも無駄合を見抜けるようにする、短い手数の再確認用。
    古いDLLには無い機能なので、使えないときは False を返し、そのまま従来どおり動く。"""
    try:
        _run("futile_floor", n=int(k))
        return True
    except ValueError:
        return False


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


def win_move(b, n):
    """can_mate(b, n) が真だった直後に呼ぶ。詰みの確認に使った初手を、全初手を調べ直さずに返す（分からなければ None）。古いDLLでは None。"""
    try:
        r = _run("winmove", b, n=n)
    except ValueError as e:
        if "timeout" in str(e):
            raise
        return None
    if r == "-":
        return None
    ms = _moves(r)
    return ms[0].usi() if ms else None


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


def quick_mate(sfen, seconds=60.0, progress=None, excluded_firsts=None, nonmate_trace=False):
    """df-pn による詰み問合せ。詰みの有無と、手順の一例を返す（最短・正確な手数は保証しない）。
    戻り値: ("mate", [USI...]) / ("nomate", []) / ("unknown", [])。時間切れは ValueError('timeout')。
    excluded_firstsにUSIの初手リストを指定すると、その初手だけを根で除外する。
    除外時のnomateは残り候補の簡易判定であり、厳密な余詰なしの証明には使わない。
    古いDLLには無い機能なので、その場合は ValueError('Unknown operation') になる。"""
    setter = None
    ctx = None
    callback = None
    if progress is not None:
        if not hasattr(_local, "context"):
            _local.context = _Context()
        ctx = _local.context
        try:
            setter = ctx.lib.tsume_set_progress
        except AttributeError:
            pass  # Older DLL: the UI can still show elapsed wall time.
        if setter is not None:
            setter.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            setter.restype = None
            def report(nodes, elapsed, phase):
                try:
                    progress({"nodes": int(nodes), "search_seconds": float(elapsed), "phase": int(phase)})
                except Exception:
                    pass  # Display failures must not interrupt the native search.
            callback = ctypes.CFUNCTYPE(None, ctypes.c_ulonglong, ctypes.c_double, ctypes.c_int)(report)
            setter(ctx.ptr, ctypes.cast(callback, ctypes.c_void_p))
    try:
        excluded = None if excluded_firsts is None else tuple(excluded_firsts)
        operation = ("dfpn_trace" if nonmate_trace else "dfpn") if excluded is None else "dfpn_excluding"
        text = sfen if excluded is None else sfen + "\n" + " ".join(excluded)
        r = _run(operation, text=text, seconds=seconds)
    finally:
        if setter is not None:
            setter(ctx.ptr, None)

    if r.startswith("M"):
        parts = r.split()
        pv = parts[2:]
        if excluded is not None and pv and pv[0] in excluded:
            raise ValueError("Excluded first move returned by native solver")
        return "mate", pv
    return ("nomate" if r.startswith("N") else "unknown"), []


def prime_hints(sfen, seconds=20.0):
    """df-pn(詰み問合せ)で詰みを見つけ、その手を「先に試す手」として登録する。精密な探索の結果は変わらず、読む順番だけが良くなる。
    成功したら True。時間切れ・古いDLL・詰みが見つからないときは False（そのまま従来どおり探索できる）。"""
    try:
        r = _run("prime", text=sfen, seconds=seconds)
    except ValueError:
        return False
    return r.startswith("M")


def hint_line(sfen, moves):
    """手順（USIの手のリスト）の攻め方の手を、精密な探索が先に試す手として登録する（結果は変わらず、読む順番だけが良くなる）。
    登録できた手数を返す。古いDLLのときは 0。"""
    try:
        return int(_run("hintline", text=sfen + "\n" + " ".join(moves)))
    except ValueError:
        return 0


def proof_report(sfen, seconds=60.0, max_nodes=50000):
    """診断用：df-pnの証明根拠を上限付きで記録し、探索表なしで構造を点検する。

    structurally_complete は省略条件付きの場合もある。最短手数・無駄合の
    厳密検証には使わない。通常のquick_mate/prime_hintsでは記録しない。
    """
    import json
    return json.loads(_run("dfpn_proof", text=sfen, n=max(1, min(int(max_nodes), 100000)), seconds=seconds))


def last_proof_report(seconds=30.0):
    """最後の診断記録を再点検する。探索表は使わない。"""
    import json
    return json.loads(_run("proof_report", text="", seconds=seconds))


def export_proof(seconds=30.0):
    """元の診断記録と、持駒違いへ適用できた対象局面の記録を返す。"""
    import json
    return json.loads(_run("proof_export", text="", seconds=seconds))


def repair_defense(sfen, move, seconds=10.0, strict_budget=0, max_nodes=50000):
    """診断用：指定予算で無駄合と判定されなかった合駒を、省かず再探索。

    元の数値表は再利用しない。返った証明も最短性・余詰を保証せず、
    厳密側の確定キャッシュには入れない。records_merged後も再点検が必要。
    """
    import json
    return json.loads(_run("repair_defense", text=sfen + "\n" + str(move), n=int(strict_budget),
                           budget=max(1, min(int(max_nodes), 100000)), seconds=seconds))


def export_feedback(seconds=30.0):
    """最後の分離した再探索で得た証明記録を返す。"""
    import json
    return json.loads(_run("feedback_export", text="", seconds=seconds))


def repair_pending(sfen, seconds=10.0, strict_budget=0, max_requests=4, max_nodes=50000):
    """診断用：証明点検→厳密な合駒判定→df-pn補修→再点検の小さな往復。

    complete は最短手数や余詰の確認完了ではない。通常の詳細検討からは未使用。
    """
    import time
    end = time.monotonic() + max(0.001, float(seconds))
    requests = []
    def remaining():
        left = end - time.monotonic()
        if left <= 0:
            raise ValueError("timeout (feedback deadline)")
        return left
    try:
        report = proof_report(sfen, seconds=remaining(), max_nodes=max_nodes)
        seen = set()
        for _ in range(max(0, min(int(max_requests), 16))):
            if report.get("complete_without_omissions"):
                break
            pending = next((p for p in report.get("pending_defenses", [])
                            if (p["sfen"], p["move"]) not in seen), None)
            if pending is None:
                break
            seen.add((pending["sfen"], pending["move"]))
            result = repair_defense(pending["sfen"], pending["move"], seconds=remaining(),
                                    strict_budget=strict_budget, max_nodes=max_nodes)
            requests.append({"sfen": pending["sfen"], "move": pending["move"], "response": result})
            report = last_proof_report(seconds=remaining())
            if result["status"] in ("unknown", "incomplete_proof", "nomate_candidate"):
                break
        status = ("certificate_complete" if report.get("complete_without_omissions") else
                  "conditional" if report.get("structurally_complete") else "incomplete")
        return {"status": status, "proof": report, "requests": requests, "strict_result_reused": False}
    except ValueError as exc:
        if "timeout" not in str(exc):
            raise
        return {"status": "unknown", "proof": None, "requests": requests,
                "error": str(exc), "strict_result_reused": False}
