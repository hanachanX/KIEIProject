"""詰将棋 自動生成（逆算法）＋検証ソルバー

- 攻方=先手(BLACK)。攻方玉は盤上に置かない。玉方持駒は「全40枚から盤上と攻方持駒を引いた残り」（標準ルール）。
- 検証条件:
  1. ちょうど N 手詰（それより短い手順で詰まない）
  2. 攻方の手は各局面で唯一（余詰なし）
  3. 本手順の詰み上がりで攻方の持駒が空（駒余りなし）
"""
import random
import shogi
from shogi import Board, Move, BLACK, WHITE

TOTAL = {
    shogi.PAWN: 18, shogi.LANCE: 4, shogi.KNIGHT: 4, shogi.SILVER: 4,
    shogi.GOLD: 4, shogi.BISHOP: 2, shogi.ROOK: 2,
}
UNPROM = {
    shogi.PROM_PAWN: shogi.PAWN, shogi.PROM_LANCE: shogi.LANCE,
    shogi.PROM_KNIGHT: shogi.KNIGHT, shogi.PROM_SILVER: shogi.SILVER,
    shogi.PROM_BISHOP: shogi.BISHOP, shogi.PROM_ROOK: shogi.ROOK,
}
PROM = {v: k for k, v in UNPROM.items()}
SFEN_CH = {shogi.PAWN: "P", shogi.LANCE: "L", shogi.KNIGHT: "N", shogi.SILVER: "S",
           shogi.GOLD: "G", shogi.BISHOP: "B", shogi.ROOK: "R"}


# ---------- 局面表現 ----------
class Pos:
    """board: {sq: (ptype, color)}, hand: 攻方持駒 {ptype: n}"""

    def __init__(self, board, hand):
        self.board = dict(board)
        self.hand = {k: v for k, v in hand.items() if v > 0}

    def copy(self):
        return Pos(self.board, self.hand)

    def remainder(self):
        used = dict(self.hand)
        for pt, _ in self.board.values():
            if pt == shogi.KING:
                continue
            base = UNPROM.get(pt, pt)
            used[base] = used.get(base, 0) + 1
        return {t: TOTAL[t] - used.get(t, 0) for t in TOTAL}

    def valid_counts(self):
        return all(v >= 0 for v in self.remainder().values())

    def to_board(self, turn):
        rows = []
        for r in range(9):
            row, empty = "", 0
            for f in range(9):
                p = self.board.get(r * 9 + f)
                if p is None:
                    empty += 1
                    continue
                if empty:
                    row += str(empty)
                    empty = 0
                pt, col = p
                prom = pt in UNPROM
                base = UNPROM.get(pt, pt)
                ch = "K" if base == shogi.KING else SFEN_CH[base]
                ch = ch if col == BLACK else ch.lower()
                row += ("+" if prom else "") + ch
            if empty:
                row += str(empty)
            rows.append(row)
        h = ""
        for t in (shogi.ROOK, shogi.BISHOP, shogi.GOLD, shogi.SILVER, shogi.KNIGHT, shogi.LANCE, shogi.PAWN):
            n = self.hand.get(t, 0)
            if n:
                h += (str(n) if n > 1 else "") + SFEN_CH[t]
        for t in (shogi.ROOK, shogi.BISHOP, shogi.GOLD, shogi.SILVER, shogi.KNIGHT, shogi.LANCE, shogi.PAWN):
            n = self.remainder()[t]
            if n:
                h += (str(n) if n > 1 else "") + SFEN_CH[t].lower()
        return Board(f"{'/'.join(rows)} {'b' if turn == BLACK else 'w'} {h or '-'} 1")

    def king_sq(self):
        for sq, (pt, col) in self.board.items():
            if pt == shogi.KING and col == WHITE:
                return sq


def pos_from_board(b: Board):
    board = {}
    for sq in range(81):
        p = b.piece_at(sq)
        if p:
            board[sq] = (p.piece_type, p.color)
    hand = {t: n for t, n in b.pieces_in_hand[BLACK].items() if n}
    return Pos(board, hand)


# ---------- ソルバー ----------
BB = shogi.BB_SQUARES
_SLIDER = {shogi.LANCE, shogi.BISHOP, shogi.ROOK, shogi.PROM_BISHOP, shogi.PROM_ROOK}
_CAN_PROMOTE = {shogi.PAWN, shogi.LANCE, shogi.KNIGHT, shogi.SILVER, shogi.BISHOP, shogi.ROOK}


def _board_moves(b: Board, color):
    """color の盤上駒の擬似合法手（成/不成の両方）"""
    occ = b.occupied
    moves = []
    for sq in range(81):
        p = b.piece_at(sq)
        if not p or p.color != color:
            continue
        mask = Board.attacks_from(p.piece_type, sq, occ, color)
        for to in range(81):
            if not (mask & BB[to]):
                continue
            q = b.piece_at(to)
            if q and q.color == color:
                continue
            moves.append(Move(sq, to, False))
            if p.piece_type in _CAN_PROMOTE:
                zone = (lambda r: r <= 2) if color == BLACK else (lambda r: r >= 6)
                if zone(sq // 9) or zone(to // 9):
                    moves.append(Move(sq, to, True))
    return moves


def gen_checks(b: Board):
    """先手番bの合法な王手手（攻方玉なし前提）"""
    ksq = b.king_squares[WHITE]
    occ = b.occupied
    out = []
    for pt, n in list(b.pieces_in_hand[BLACK].items()):
        if n <= 0:
            continue
        mask = Board.attacks_from(pt, ksq, occ, WHITE)
        for s in range(81):
            if (mask & BB[s]) and b.piece_at(s) is None:
                m = Move(None, s, False, pt)
                if b.is_legal(m):
                    out.append(m)
    for m in _board_moves(b, BLACK):
        if not b.is_pseudo_legal(m):
            continue
        b.push(m)
        chk = b.is_check()
        b.pop()
        if chk:
            out.append(m)
    return out


def gen_evasions(b: Board):
    """後手番b(王手中)の合法な王手回避手"""
    ksq = b.king_squares[WHITE]
    out = []
    for m in _board_moves(b, WHITE):
        if b.is_legal(m):
            out.append(m)
    # 合駒（飛び駒の単独王手のときのみ）
    att = [s for s in range(81) if (b.attackers(BLACK, ksq) & BB[s])]
    if len(att) == 1:
        a = att[0]
        p = b.piece_at(a)
        dr, dc = a // 9 - ksq // 9, a % 9 - ksq % 9
        dist = max(abs(dr), abs(dc))
        if p.piece_type in _SLIDER and dist > 1 and (dr == 0 or dc == 0 or abs(dr) == abs(dc)):
            sr = (dr > 0) - (dr < 0)
            sc = (dc > 0) - (dc < 0)
            for k in range(1, dist):
                s = (ksq // 9 + sr * k) * 9 + (ksq % 9 + sc * k)
                for pt, n in list(b.pieces_in_hand[WHITE].items()):
                    if n > 0:
                        m = Move(None, s, False, pt)
                        if b.is_legal(m) and not _futile_interposition(b, m, a):
                            out.append(m)
    return out


_CACHE_F = {}   # (局面, 合駒のUSI) -> bool  無駄合か


def _futile_interposition(b: Board, d: Move, a: int):
    """無駄合（詰将棋のルールで、玉方が応じなくてよい合駒）か。
    合駒dを、王手をかけている飛び駒（aのマス）がそのまま取って、取った後に玉方の応手が無い（詰み）なら無駄合とみなす。
    （取られても詰みの形が変わらず、手数が延びるだけの合駒。連続した合駒も、この判定を繰り返して外れる）"""
    key = (_key(b), d.usi())
    r = _CACHE_F.get(key)
    if r is not None:
        return r
    res = False
    b.push(d)
    try:
        for promo in (False, True):
            m = Move(a, d.to_square, promo)
            if not b.is_pseudo_legal(m):
                continue
            b.push(m)
            try:
                if b.is_check() and not gen_evasions(b):
                    res = True
            finally:
                b.pop()
            if res:
                break
    finally:
        b.pop()
    _CACHE_F[key] = res
    return res


_CACHE_A = {}   # (局面, plies) -> bool  攻方番で詰むか
_CACHE_D = {}   # (局面, plies) -> bool  玉方番で全応手が詰むか


def _key(b: Board):
    return b.sfen().rsplit(" ", 1)[0]


def clear_cache():
    _CACHE_A.clear()
    _CACHE_D.clear()
    _CACHE_F.clear()


def can_mate(b: Board, plies: int):
    """先手番bで plies 手(奇数)以内に詰むか（存在判定・キャッシュ付き）"""
    k = (_key(b), plies)
    r = _CACHE_A.get(k)
    if r is not None:
        return r
    checks = gen_checks(b)
    scored = []
    for m in checks:
        b.push(m)
        evs = gen_evasions(b)
        b.pop()
        if not evs:
            _CACHE_A[k] = True
            return True
        scored.append((len(evs), m))
    res = False
    if plies >= 3:
        scored.sort(key=lambda t: t[0])  # 逃げ道の少ない王手から
        for _, m in scored:
            b.push(m)
            ok = defenders_all_lose(b, plies - 1)
            b.pop()
            if ok:
                res = True
                break
    _CACHE_A[k] = res
    return res


def solve(b: Board, plies: int):
    """先手番bで plies 手(奇数)以内に詰む手の全リスト。"""
    wins = []
    for m in gen_checks(b):
        b.push(m)
        ok = defenders_all_lose(b, plies - 1)
        b.pop()
        if ok:
            wins.append(m)
    return wins


def defenders_all_lose(b: Board, plies: int):
    """後手番bで、全応手に対し残り plies 手(偶数)以内に詰まされるか。"""
    k = (_key(b), plies)
    r = _CACHE_D.get(k)
    if r is not None:
        return r
    moves = gen_evasions(b)
    if not moves:
        res = True  # 詰み
    elif plies < 2:
        res = False
    else:
        res = True
        for m in moves:
            b.push(m)
            ok = can_mate(b, plies - 1)
            b.pop()
            if not ok:
                res = False
                break
    _CACHE_D[k] = res
    return res


def mate_length_exact(b: Board, n: int):
    """ちょうどn手詰か（n-2手以内では詰まない）"""
    if n >= 3 and can_mate(b, n - 2):
        return False
    return can_mate(b, n)


def principal_line(b: Board, n: int):
    """唯一解チェックしつつ本手順（玉方は最長抵抗）を返す。不適格ならNone。"""
    line = []
    cur = b
    remaining = n
    while True:
        wins = solve(cur, remaining)
        if len(wins) != 1:
            return None  # 余詰 or 詰まない
        a = wins[0]
        line.append(a)
        cur.push(a)
        if not gen_evasions(cur):
            break
        # 玉方: 最長抵抗（詰むまでが最も長い応手）
        best, best_len = None, -1
        for d in gen_evasions(cur):
            cur.push(d)
            L = None
            for k in range(1, remaining - 1, 2):
                if can_mate(cur, k):
                    L = k
                    break
            cur.pop()
            if L is not None and L > best_len:
                best, best_len = d, L
        if best is None:
            return None
        line.append(best)
        cur.push(best)
        remaining -= 2
    for _ in line:
        cur.pop()
    return line


def verify(b: Board, n: int):
    """b: 先手番の初形。合格なら本手順(Move列)、不合格ならNone。"""
    if b.is_check():
        return None
    if not mate_length_exact(b, n):
        return None
    work = Board(b.sfen())
    line = principal_line(work, n)
    if line is None or len(line) != n:
        return None
    # 駒余りなし: 本手順の最後で攻方持駒が空
    chk = Board(b.sfen())
    for m in line:
        chk.push(m)
    if any(v for v in chk.pieces_in_hand[BLACK].values()):
        return None
    return line


# ---------- 逆算ジェネレーター ----------
def _try_unmove(P: Pos, mover, want_turn_after):
    """局面P(直前に mover が指した)から、可能な「ひとつ前」局面とその手を列挙する。
    返り値: [(Q:Pos, Move)]  Q は mover 番。"""
    out = []
    enemy = WHITE if mover == BLACK else BLACK
    occ = P.to_board(mover).occupied
    caps = [None] + _capture_options(P, mover)
    for to, (pt, col) in list(P.board.items()):
        if col != mover:
            continue
        base = UNPROM.get(pt, pt)

        # --- 打った手の取り消し（攻方・玉方共通） ---
        if pt != shogi.KING and pt not in UNPROM:
            Q = P.copy()
            del Q.board[to]
            if mover == BLACK:
                Q.hand[pt] = Q.hand.get(pt, 0) + 1
            if Q.valid_counts():
                out.append((Q, Move(None, to, False, pt)))

        # --- 盤上の駒を動かした手の取り消し ---
        cand_types = [(pt, False)]
        if pt in UNPROM:
            cand_types.append((UNPROM[pt], True))  # 成った手
        for src_pt, promoted in cand_types:
            mask = shogi.Board.attacks_from(src_pt, to, occ, enemy)
            for from_sq in range(81):
                if from_sq in P.board or not (mask & shogi.BB_SQUARES[from_sq]):
                    continue
                for cap in caps:
                    Q = P.copy()
                    del Q.board[to]
                    Q.board[from_sq] = (src_pt, mover)
                    if cap is not None:
                        cpt, cprom = cap
                        if mover == BLACK:
                            if Q.hand.get(cpt, 0) <= 0:
                                continue
                            Q.hand[cpt] -= 1
                        Q.board[to] = (PROM[cpt] if cprom else cpt, enemy)
                    if not Q.valid_counts():
                        continue
                    out.append((Q, Move(from_sq, to, promoted)))
    return out


def _capture_options(P: Pos, mover):
    opts = []
    for t in TOTAL:
        opts.append((t, False))
        if t in PROM:
            opts.append((t, True))
    return opts


def _forward_matches(Q: Pos, mv: Move, P: Pos, mover):
    """Qでmoverが mv を指して P になるか検証"""
    b = Q.to_board(mover)
    try:
        if not b.is_legal(mv):
            return False
    except Exception:
        return False
    b.push(mv)
    if b.sfen().split(" ")[0] != P.to_board(mover).sfen().split(" ")[0]:
        return False
    # 持駒（攻方）も一致
    pb = pos_from_board(b)
    return pb.hand == P.hand


def _knight_lance_dead(P: Pos):
    """行き場のない駒(段違反)がないか"""
    for sq, (pt, col) in P.board.items():
        r = sq // 9
        if col == BLACK:
            if pt in (shogi.PAWN, shogi.LANCE) and r == 0:
                return False
            if pt == shogi.KNIGHT and r <= 1:
                return False
        else:
            if pt in (shogi.PAWN, shogi.LANCE) and r == 8:
                return False
            if pt == shogi.KNIGHT and r >= 7:
                return False
    return True


def random_mate_position(rng):
    """頭金など、詰み上がりの形をランダムに作る。攻方持駒は空。"""
    for _ in range(2000):
        ksq = rng.choice([r * 9 + f for r in range(0, 3) for f in range(9)])
        board = {ksq: (shogi.KING, WHITE)}
        n = rng.randint(2, 4)
        types = [shogi.GOLD, shogi.SILVER, shogi.PROM_SILVER, shogi.BISHOP, shogi.ROOK,
                 shogi.PROM_BISHOP, shogi.PROM_ROOK, shogi.KNIGHT, shogi.LANCE, shogi.PAWN, shogi.PROM_PAWN]
        kr, kf = divmod(ksq, 9)
        near = [(kr + dr) * 9 + (kf + df) for dr in (-1, 0, 1, 2) for df in (-1, 0, 1)
                if 0 <= kr + dr < 9 and 0 <= kf + df < 9 and (dr, df) != (0, 0)]
        for _ in range(n):
            sq = rng.choice(near + [rng.randrange(81)])
            if sq in board:
                continue
            board[sq] = (rng.choice(types), BLACK)
        for _ in range(rng.choice([0, 0, 1, 2])):
            sq = rng.choice(near)
            if sq not in board:
                board[sq] = (rng.choice([shogi.PAWN, shogi.SILVER, shogi.GOLD, shogi.LANCE, shogi.KNIGHT]), WHITE)
        P = Pos(board, {})
        if not (P.valid_counts() and _knight_lance_dead(P)):
            continue
        b = P.to_board(WHITE)
        if b.is_checkmate():
            return P
    return None


def _node_ok(Q: Pos, mover, remaining):
    """逆算で得た途中局面Qの健全性。remaining=Qからの残り手数。"""
    if not _knight_lance_dead(Q):
        return False
    if mover == BLACK:
        # Q: 攻方番。玉方は王手されていない／残りremaining手でちょうど唯一解で詰む
        if Q.to_board(WHITE).is_check():
            return False
        bb = Q.to_board(BLACK)
        if remaining >= 3 and can_mate(bb, remaining - 2):
            return False  # 短手数で詰む
        wins = solve(bb, remaining)
        return len(wins) == 1
    # Q: 玉方番で王手中。全応手が残りremaining手以内に詰み、それより短くは詰まない
    bw = Q.to_board(WHITE)
    if not bw.is_check():
        return False
    if not defenders_all_lose(bw, remaining):
        return False
    if defenders_all_lose(bw, remaining - 2):
        return False
    return True


def _search(P: Pos, mover, r, n, rng, budget):
    """Pは mover が直前に指した局面(残りr手)。初形(残りn手)まで遡る。"""
    cands = _try_unmove(P, mover, None)
    rng.shuffle(cands)
    for Q, mv in cands:
        if budget[0] <= 0:
            return None
        if not _forward_matches(Q, mv, P, mover):
            continue
        budget[0] -= 1
        if not _node_ok(Q, mover, r + 1):
            continue
        if r + 1 == n:
            return Q
        res = _search(Q, WHITE if mover == BLACK else BLACK, r + 1, n, rng, budget)
        if res is not None:
            return res
    return None


def generate(n_plies: int, rng=None, budget=600, time_limit=180):
    """n_plies手詰(奇数)を1問生成。返り値: (sfen, 本手順USI列) または None"""
    import time
    rng = rng or random.Random()
    t0 = time.time()
    while time.time() - t0 < time_limit:
        P = random_mate_position(rng)
        if P is None:
            continue
        if len(_CACHE_A) + len(_CACHE_D) > 400000:
            clear_cache()
        Q = _search(P, BLACK, 0, n_plies, rng, [budget])
        if Q is None:
            continue
        b = Q.to_board(BLACK)
        line = verify(b, n_plies)
        if line:
            return b.sfen(), [m.usi() for m in line]
    return None


# ---------- 表示 ----------
JP = {shogi.PAWN: "歩", shogi.LANCE: "香", shogi.KNIGHT: "桂", shogi.SILVER: "銀", shogi.GOLD: "金",
      shogi.BISHOP: "角", shogi.ROOK: "飛", shogi.KING: "玉", shogi.PROM_PAWN: "と", shogi.PROM_LANCE: "杏",
      shogi.PROM_KNIGHT: "圭", shogi.PROM_SILVER: "全", shogi.PROM_BISHOP: "馬", shogi.PROM_ROOK: "龍"}


def show(sfen: str):
    b = Board(sfen)
    lines = ["  ９ ８ ７ ６ ５ ４ ３ ２ １"]
    kan = "一二三四五六七八九"
    for r in range(9):
        s = ""
        for f in range(9):
            p = b.piece_at(r * 9 + f)
            s += (" " + JP[p.piece_type] if p and p.color == BLACK else
                  "v" + JP[p.piece_type] if p else " ・")
        lines.append(f"{s} {kan[r]}")
    h = "".join(JP[t] + (str(n) if n > 1 else "") for t, n in b.pieces_in_hand[BLACK].items() if n)
    lines.append("攻方持駒: " + (h or "なし"))
    return "\n".join(lines)


if __name__ == "__main__":
    import sys, time
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    cnt = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    rng = random.Random()
    for i in range(cnt):
        t = time.time()
        r = generate(n, rng)
        if not r:
            print("生成失敗")
            continue
        sfen, line = r
        print(f"--- {n}手詰 #{i+1} ({time.time()-t:.1f}s) ---")
        print(show(sfen))
        print("SFEN:", sfen)
        print("解:", " ".join(line))
