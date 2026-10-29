# 戦型判定（飛車の筋・筋違い角はルール、居飛車どうしの戦型は学習モデル）
import os
import shogi

_MODEL = None          # None=未読込 / False=使えない / dict=読込済み
_HERE = os.path.dirname(os.path.abspath(__file__))
FURI = {5: "中飛車", 6: "四間飛車", 7: "三間飛車", 8: "向かい飛車"}
IBISHA_CLASSES = ["矢倉", "雁木", "角換わり", "相掛かり", "横歩取り", "ひねり飛車"]
MIN_PLY, MAX_PLY, SURE_FROM, SURE_TO = 16, 50, 20, 44
MIN_PROB = 0.55
OVERRIDE = {"ひねり飛車": 0.7, "横歩取り": 0.85, "相掛かり": 0.85}


def _own(sq, color):
    f, r = 9 - sq % 9, sq // 9 + 1
    return (f, r) if color == shogi.BLACK else (10 - f, 10 - r)


def rook_file(board, color):
    for s in range(81):
        p = board.piece_at(s)
        if p and p.color == color and p.piece_type in (shogi.ROOK, shogi.PROM_ROOK):
            return _own(s, color)[0]
    return 0


def sujichigai(start_sfen, moves):
    """角を交換した直後（16手以内）に、先手なら4五・後手なら6五へ角を打ったら筋違い角"""
    b = shogi.Board(start_sfen)
    captured = False
    for k, u in enumerate(moves[:16], 1):
        mv = shogi.Move.from_usi(u)
        if mv.drop_piece_type is None:
            pc = b.piece_at(mv.to_square)
            if pc is not None and pc.piece_type in (shogi.BISHOP, shogi.PROM_BISHOP):
                captured = True
        elif mv.drop_piece_type == shogi.BISHOP:
            black = b.turn == shogi.BLACK
            return captured and ((black and u == "B*4e") or (not black and u == "B*6e"))
        b.push(mv)
    return False


# ---- 学習モデル用の特徴量（学習時と同じ作り） ----
_PIECES = ["P", "L", "N", "S", "G", "B", "R", "K", "+P", "+L", "+N", "+S", "+B", "+R"]
_PIDX = {p: i for i, p in enumerate(_PIECES)}
_HAND = ["P", "L", "N", "S", "G", "B", "R"]


def _feat(board):
    import numpy as np
    v = np.zeros(2 * 14 * 81 + 14, dtype=np.float32)
    for sq in range(81):
        pc = board.piece_at(sq)
        if pc is None:
            continue
        c = 0 if pc.color == shogi.BLACK else 1
        v[(c * 14 + _PIDX[pc.symbol().upper()]) * 81 + sq] = 1
    for c, col in enumerate((shogi.BLACK, shogi.WHITE)):
        h = board.pieces_in_hand[col]
        for j, p in enumerate(_HAND):
            v[2 * 14 * 81 + c * 7 + j] = h.get(shogi.PIECE_SYMBOLS.index(p.lower()), 0)
    ex = []
    for col in (shogi.BLACK, shogi.WHITE):
        def fr(types):
            for sq in range(81):
                p = board.piece_at(sq)
                if p and p.color == col and p.piece_type in types:
                    return [sq % 9 + 1, sq // 9 + 1]
            return [0, 0]
        nb = sum(1 for sq in range(81) if (p := board.piece_at(sq)) and p.color == col
                 and p.piece_type in (shogi.BISHOP, shogi.PROM_BISHOP))
        ex += fr((shogi.ROOK, shogi.PROM_ROOK)) + fr((shogi.KING,)) + [nb]
    return np.concatenate([v, np.array(ex, dtype=np.float32)])


def _flip(x):
    import numpy as np
    N = 2 * 14 * 81
    B = x[:14 * 81].reshape(14, 81)[:, ::-1]
    W = x[14 * 81:N].reshape(14, 81)[:, ::-1]
    H = x[N:N + 14]
    e = x[N + 14:]
    eb, ew = e[:5].copy(), e[5:].copy()
    for a in (eb, ew):
        for i in range(4):
            a[i] = 10 - a[i] if a[i] > 0 else 0
    return np.concatenate([W.ravel(), B.ravel(), H[7:], H[:7], ew, eb]).astype(np.float32)


READY_CB = None      # モデルの読み込みが終わったときに呼ぶ関数（画面の更新用）
LOG_PATH = os.path.join(_HERE, "senkei_log.txt")


def log(msg):
    try:
        import time as _t
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(_t.strftime("%H:%M:%S ") + msg + "\n")
        if os.path.getsize(LOG_PATH) > 200000:
            os.remove(LOG_PATH)
    except Exception:
        pass


def _do_load():
    global _MODEL
    try:
        import joblib
        d = joblib.load(os.path.join(_HERE, "senkei_model.joblib"))
        try:
            d["model"].n_jobs = 1          # 予測のたびにスレッドを立てない
        except Exception:
            pass
        try:      # ダミーで一度予測して、内部の部品の読み込みをここで済ませておく
            import numpy as np
            d["model"].predict_proba(np.zeros((1, len(d["keep"].nonzero()[0])), dtype=np.float32))
        except Exception:
            pass
        _MODEL = d
        log("model loaded ok")
    except Exception as e:
        import traceback
        log("model load FAILED: " + repr(e) + " " + traceback.format_exc().replace("\n", " | "))
        _MODEL = False
    try:
        if READY_CB:
            READY_CB()
    except Exception:
        pass


def preload():
    """起動時に裏で（画面を止めずに）モデルを読み込んでおく"""
    global _MODEL
    if _MODEL is None:
        _MODEL = "loading"
        import threading
        threading.Thread(target=_do_load, daemon=True).start()


def _load():
    """読み込み済みならモデルを返す。まだなら待たずに False を返す（その局面は判定しない）"""
    if _MODEL is None:
        preload()
    if isinstance(_MODEL, dict):
        return _MODEL
    return False


_CACHE = {}


def model_predict(board):
    m = _load()
    if not m:
        return None
    key = board.zobrist_hash()
    if key in _CACHE:
        return _CACHE[key]
    r = _model_predict(board, m)
    if len(_CACHE) > 2000:
        _CACHE.clear()
    _CACHE[key] = r
    return r


def _model_predict(board, m):
    import numpy as np
    x = _feat(board)
    xs = np.vstack([x[m["keep"]], _flip(x)[m["keep"]]])
    p = m["model"].predict_proba(xs).sum(0)
    cls = list(m["classes"])
    sub = {c: p[cls.index(c)] for c in IBISHA_CLASSES if c in cls}
    tot = sum(sub.values())
    if tot <= 0:
        return None
    best = max(sub, key=sub.get)
    return best, sub[best] / tot



def _pos(b, color, types):
    return [_own(s, color) for s in range(81)
            if (p := b.piece_at(s)) and p.color == color and p.piece_type in types]


def gangi_kind(b, color):
    """雁木の種類を返す（なければ None）。
    共通：6七銀、5八金・7八金、玉は5九より左側（5九・6九・7九・8八など。4八・3八へ行く風車などは含めない）
    5七にも銀 → 雁木 ／ 4七にも銀 → ツノ銀雁木   （後手は盤を反対側から見た同じ形）"""
    S = set(_pos(b, color, (shogi.SILVER,)))
    G = set(_pos(b, color, (shogi.GOLD,)))
    K = _pos(b, color, (shogi.KING,))
    if not K or K[0][0] < 5:
        return None
    if (6, 7) not in S or (5, 8) not in G or (7, 8) not in G:
        return None
    if (5, 7) in S:
        return "雁木"
    if (4, 7) in S:
        return "ツノ銀雁木"
    return None


def is_gangi(b, color):
    return gangi_kind(b, color) is not None


def yagura_kind(b, color):
    """矢倉の種類を返す（なければ None）。玉は5九より左側（5筋まで）。
    金矢倉：7七銀・6七金・7八金 ／ 銀矢倉：7七銀・6七銀・7八金 ／ 総矢倉：金矢倉に5七銀も加わった金銀4枚"""
    S = set(_pos(b, color, (shogi.SILVER,)))
    G = set(_pos(b, color, (shogi.GOLD,)))
    K = _pos(b, color, (shogi.KING,))
    if not K or K[0][0] < 5:
        return None
    if (7, 7) not in S or (7, 8) not in G:
        return None
    if (6, 7) in G:
        return "総矢倉" if (5, 7) in S else "金矢倉"
    if (6, 7) in S:
        return "銀矢倉"
    return None


def castle_kind(b, color):
    return gangi_kind(b, color) or yagura_kind(b, color)


def is_migi_shiken(b, color):
    """右四間飛車：飛車が4筋にいて、4筋の歩を5段目まで突いている"""
    R = _pos(b, color, (shogi.ROOK, shogi.PROM_ROOK))
    P = _pos(b, color, (shogi.PAWN,))
    return bool(R) and R[0][0] == 4 and any(p[0] == 4 and p[1] <= 5 for p in P)


def classify(start_sfen, moves, cursor):
    """cursor手目まで指した局面の戦型を文字列で返す。判定できなければ空文字。"""
    if start_sfen != shogi.STARTING_SFEN:
        return ""
    if cursor < MIN_PLY or cursor > MAX_PLY:
        return ""
    moves = moves[:cursor]
    if len(moves) < cursor:
        return ""
    b = shogi.Board(start_sfen)
    try:
        for u in moves:
            b.push(shogi.Move.from_usi(u))
    except Exception:
        return ""
    ref = "" if SURE_FROM <= cursor <= SURE_TO else "（参考）"
    if sujichigai(start_sfen, moves):
        return "筋違い角" + ref
    rb, rw = rook_file(b, shogi.BLACK), rook_file(b, shogi.WHITE)
    fb, fw = FURI.get(rb), FURI.get(rw)
    if fb and fw:
        return f"相振り飛車（先手 {fb}／後手 {fw}）" + ref
    if fb or fw:
        # 飛車が3筋・7筋などに寄る居飛車系の戦型（ひねり飛車・横歩取り・相掛かり）は、モデルが強く言うときだけ優先する
        rr = model_predict(b)
        log(f"ply{cursor}: furi {fb or ''}{fw or ''} model {rr}")
        if rr and rr[1] >= OVERRIDE.get(rr[0], 2):
            return rr[0] + ref
        if fb:
            return f"{fb}（先手）vs 居飛車（対抗型）" + ref
        return f"{fw}（後手）vs 居飛車（対抗型）" + ref
    kb, kw = castle_kind(b, shogi.BLACK), castle_kind(b, shogi.WHITE)
    if kb or kw:
        if kb and kw:
            fam = lambda k: "矢倉" if k.endswith("矢倉") else "雁木"
            if kb == kw:
                return f"相{kb}" + ref
            if fam(kb) == fam(kw):
                return f"相{fam(kb)}（先手 {kb}／後手 {kw}）" + ref
            return f"{kb}（先手）vs {kw}（後手）" + ref
        return (f"{kb}（先手）" if kb else f"{kw}（後手）") + ref
    if is_migi_shiken(b, shogi.BLACK) or is_migi_shiken(b, shogi.WHITE):
        return "右四間飛車" + ref
    if not _load():
        log(f"ply{cursor}: model not ready (state={'loading' if _MODEL == 'loading' else _MODEL})")
        return None                      # まだ準備中（記憶しない）
    r = model_predict(b)
    if r is None:
        log(f"ply{cursor}: predict returned None")
        return ""
    name, prob = r
    log(f"ply{cursor}: model says {name} {prob:.2f}")
    if prob < (MIN_PROB if not ref else 0.8):      # 参考の範囲（序盤・終盤寄り）では、かなり確信があるときだけ出す
        return ""
    return name + ref


def classify_sticky(start_sfen, moves, cursor, back=10):
    """classify と同じだが、今の局面で判定が出なかったときは、直前（最大back手前まで）に出ていた戦型をそのまま使う。
    確信度が基準ぎりぎりで表示が出たり消えたりするのを防ぐ。はっきり別の戦型が出たときは、そちらに変わる。"""
    if cursor > MAX_PLY:
        cursor = MAX_PLY                  # 終盤は判定対象外なので、判定対象の最後（50手）の戦型をそのまま出し続ける
    r = classify(start_sfen, moves, cursor)
    if r is None or r:
        return r
    if start_sfen != shogi.STARTING_SFEN or cursor < MIN_PLY:
        return r
    for k in range(cursor - 1, max(MIN_PLY - 1, cursor - back - 1), -1):
        rk = classify(start_sfen, moves, k)
        if rk is None:
            return None
        if rk:
            return rk
    return r
