# -*- coding: utf-8 -*-
"""実戦の棋譜から詰将棋を取り出す。
詰みの判定は、詰将棋専用エンジン(KomoringHeights)に聞きます。kh(sfen, ms) -> (状態, 手順)"""
import hashlib
import shogi

PT_NAME = {shogi.PAWN: "歩", shogi.LANCE: "香", shogi.KNIGHT: "桂", shogi.SILVER: "銀", shogi.GOLD: "金",
           shogi.BISHOP: "角", shogi.ROOK: "飛", shogi.KING: "玉", shogi.PROM_PAWN: "と", shogi.PROM_LANCE: "成香",
           shogi.PROM_KNIGHT: "成桂", shogi.PROM_SILVER: "成銀", shogi.PROM_BISHOP: "馬", shogi.PROM_ROOK: "龍"}
FILES = "９８７６５４３２１"
RANKS = "一二三四五六七八九"


def sq_name(sq):
    return f"{9 - sq % 9}{'一二三四五六七八九'[sq // 9]}"


def to_attacker_black(b):
    """手番が後手なら、盤を180度回して先後を入れ替え、攻方を先手にそろえる（詰将棋の通常の形）。"""
    if b.turn == shogi.BLACK:
        return shogi.Board(b.sfen()), False
    n = shogi.Board("9/9/9/9/9/9/9/9/9 b - 1")
    for sq in range(81):
        p = b.piece_at(sq)
        if p is not None:
            n.set_piece_at(80 - sq, shogi.Piece(p.piece_type, 1 - p.color))
    for col in (shogi.BLACK, shogi.WHITE):
        for pt, c in b.pieces_in_hand[col].items():
            if c:
                n.pieces_in_hand[1 - col][pt] = c
    return shogi.Board(n.sfen()), True


def _plain(b):
    """手数カウンタを1にそろえたSFEN"""
    parts = b.sfen().split()
    return " ".join(parts[:3] + ["1"])


def find_mates(start_sfen, moves, kh, max_len=99, ms=1500, progress=None, stop=None):
    """棋譜の各局面で、手番側に max_len 手以内の詰みがあるか調べる。
    戻り値 [(手数(何手目の後か), 手番('先手'/'後手'), 詰み手数, 手順USIのリスト)]"""
    out = []
    b = shogi.Board(start_sfen)
    total = len(moves) + 1
    for i in range(total):
        if stop is not None and stop():
            break
        if i:
            b.push(shogi.Move.from_usi(moves[i - 1]))
        if progress:
            progress(i, total)
        try:
            if not any(True for _ in b.legal_moves):
                continue
        except Exception:
            continue
        state, pv = kh(b.sfen(), ms)
        if state == "mate" and pv and len(pv) <= max_len and len(pv) % 2 == 1:
            out.append((i, "先手" if b.turn == shogi.BLACK else "後手", len(pv), list(pv)))
    return out


def _candidates(b):
    """取り除いてみる駒の一覧。玉方の玉から遠い駒を先に調べる（遠い駒は要らないことが多い）。"""
    wk = b.king_squares[shogi.WHITE]
    cands = []
    for sq in range(81):
        p = b.piece_at(sq)
        if p is None or (p.piece_type == shogi.KING and p.color == shogi.WHITE):
            continue
        d = max(abs(sq % 9 - wk % 9), abs(sq // 9 - wk // 9)) if wk is not None else 0
        cands.append((-d, ("board", sq)))
    for col in (shogi.BLACK, shogi.WHITE):
        for pt, c in b.pieces_in_hand[col].items():
            if c:
                cands.append((-9 if col == shogi.WHITE else -10, ("hand", col, pt)))
    cands.sort(key=lambda t: t[0])
    return [c for _d, c in cands]


def _apply_removal(b, cand):
    n = shogi.Board(b.sfen())
    if cand[0] == "board":
        n.remove_piece_at(cand[1])
    else:
        n.pieces_in_hand[cand[1]][cand[2]] -= 1
    return shogi.Board(_plain(n))


def _describe(b, cand):
    if cand[0] == "board":
        p = b.piece_at(cand[1])
        return f"{sq_name(cand[1])}の{'攻方' if p.color == shogi.BLACK else '玉方'}の{PT_NAME.get(p.piece_type, '?')}"
    return f"{'攻方' if cand[1] == shogi.BLACK else '玉方'}の持ち駒の{PT_NAME.get(cand[2], '?')}"


_TOTAL = {shogi.ROOK: 2, shogi.BISHOP: 2, shogi.GOLD: 4, shogi.SILVER: 4, shogi.KNIGHT: 4, shogi.LANCE: 4, shogi.PAWN: 18}
_BASE = {shogi.PROM_PAWN: shogi.PAWN, shogi.PROM_LANCE: shogi.LANCE, shogi.PROM_KNIGHT: shogi.KNIGHT,
         shogi.PROM_SILVER: shogi.SILVER, shogi.PROM_BISHOP: shogi.BISHOP, shogi.PROM_ROOK: shogi.ROOK}


def fill_defender_hand(b):
    """盤上と攻方の持ち駒にない駒（取り除いた駒）を、すべて玉方の持ち駒にする（詰将棋の「残り駒は全部玉方持ち」）。"""
    used = {pt: 0 for pt in _TOTAL}
    for sq in range(81):
        p = b.piece_at(sq)
        if p is not None and p.piece_type != shogi.KING:
            used[_BASE.get(p.piece_type, p.piece_type)] += 1
    for col in (shogi.BLACK, shogi.WHITE):
        for pt, c in b.pieces_in_hand[col].items():
            if pt in used:
                used[pt] += c
    n = shogi.Board(b.sfen())
    for pt, tot in _TOTAL.items():
        rest = tot - used[pt]
        if rest > 0:
            n.pieces_in_hand[shogi.WHITE][pt] = n.pieces_in_hand[shogi.WHITE][pt] + rest
    return shogi.Board(_plain(n))


# ---------------------------------------------------------------- 棋慧エンジン（DLL）で判定する部品
def _flip_usi(u):
    """盤を180度回したときの指し手の読み替え（先手と後手を入れ替えた局面で出した手を、元の向きに戻す）"""
    def sq(f, r):
        return str(10 - int(f)) + chr(ord("a") + 8 - (ord(r) - ord("a")))
    if len(u) >= 4 and u[1] == "*":
        return u[:2] + sq(u[2], u[3])
    out = sq(u[0], u[1]) + sq(u[2], u[3])
    return out + u[4:]


def native_available():
    try:
        import tsume_native as m
        import tsume_verify  # noqa: F401
        m._library()
        return True
    except Exception:
        return False


def native_kh(sfen, ms=3000, upto=None, max_n=31):
    """棋慧エンジン(DLL)で詰みを調べる。詰将棋の約束（無駄合は応手に数えない・攻め方の玉は無い）で判定する。
    sfen は攻め方の手番（先手でも後手でもよい）。upto を渡すと、その手数までだけ調べる。
    戻り値は kh と同じ形 (状態, 手順)。状態は 'mate' / 'nomate' / 'timeout' / 'error'。手順は元の向きのUSI。"""
    import time as _t
    import tsume_native as T
    import tsume_verify as V
    try:
        b0 = shogi.Board(sfen)
    except Exception:
        return "error", []
    if b0.is_check():
        return "nomate", []                      # 手番側が王手されている局面は、詰将棋の初形にならない
    b, flipped = to_attacker_black(b0)
    ak = b.king_squares[shogi.BLACK]
    if ak is not None:
        n = shogi.Board(b.sfen())
        n.remove_piece_at(ak)
        b = shogi.Board(_plain(n))
    wk = b.king_squares[shogi.WHITE]
    if wk is None or b.attackers(shogi.BLACK, wk):
        return "nomate", []
    lim = min(upto if upto else max_n, 31)
    deadline = _t.time() + max(0.3, ms / 1000.0)
    old = T.TIMEOUT
    try:
        found = None
        for n in range(1, lim + 1, 2):
            left = deadline - _t.time()
            if left <= 0:
                return "timeout", []
            T.TIMEOUT = max(0.2, left)
            try:
                if T.can_mate(b, n):
                    found = n
                    break
            except ValueError as e:
                if "timeout" in str(e):
                    return "timeout", []
                raise
        if found is None:
            return "nomate", []
        T.TIMEOUT = max(1.0, deadline - _t.time())
        wins = V.attacker_wins(b, found)
        if not wins:
            return "error", []
        pv = V.main_line(_plain(b), [wins[0]], found)
        if flipped:
            pv = [_flip_usi(u) for u in pv]
        return "mate", pv
    except ValueError as e:
        return ("timeout" if "timeout" in str(e) else "error"), []
    finally:
        T.TIMEOUT = old


def native_unique(sfen, N):
    """初手の余詰を調べる（無駄合を除く）。N手以内で詰む初手のUSIの一覧を返す（唯一なら1個）。"""
    import tsume_verify as V
    return [m for m in V.attacker_wins(shogi.Board(sfen), N)]


def clean(sfen, kh, ms=3000, progress=None, stop=None):
    """不要な駒を取り除く。1つ外すごとに「同じ手数で詰む」ことを確かめ、詰みが変わるなら外さない。
    戻り値 dict(ok, msg, sfen, line, steps, removed[説明], flipped) 。"""
    b, flipped = to_attacker_black(shogi.Board(sfen))
    st, pv = kh(_plain(b), ms)
    if st != "mate" or not pv:
        return {"ok": False, "msg": "この局面は（時間内に）詰みを確認できませんでした"}
    N = len(pv)
    removed = []
    cur_pv = pv
    if b.king_squares[shogi.BLACK] is not None:       # 攻方の玉は詰将棋では置かない
        b2 = _apply_removal(b, ("board", b.king_squares[shogi.BLACK]))
        s2, p2 = kh(_plain(b2), ms, N)
        if s2 == "mate" and len(p2) == N:
            b, cur_pv = b2, p2
            removed.append("攻方の玉")
    changed, rounds = True, 0
    while changed and rounds < 4:
        changed = False
        rounds += 1
        for cand in _candidates(b):
            if stop is not None and stop():
                break
            if cand[0] == "board" and b.piece_at(cand[1]) is None:
                continue
            if cand[0] == "hand" and not b.pieces_in_hand[cand[1]][cand[2]]:
                continue
            b2 = _apply_removal(b, cand)
            if progress:
                progress(_describe(b, cand))
            s2, p2 = kh(_plain(b2), ms, N)
            if s2 == "mate" and len(p2) == N:
                removed.append(_describe(b, cand))
                b, cur_pv = b2, p2
                changed = True
    note = ""
    if removed:
        full = fill_defender_hand(b)
        s3, p3 = kh(_plain(full), ms)
        if s3 == "mate" and p3:
            if len(p3) != N:
                note = f"取り除いた駒を玉方の持ち駒に戻したら、詰み手数が{N}手から{len(p3)}手になりました（合駒が増えるため）"
            b, cur_pv, N = full, p3, len(p3)
        else:
            note = "取り除いた駒を玉方の持ち駒に戻した形は、時間内に確認できなかったので、駒を減らした形のままです"
    return {"ok": True, "msg": "", "sfen": _plain(b), "line": cur_pv, "steps": N, "removed": removed, "flipped": flipped, "note": note}


def _backend():
    """詰みの判定部品を返す。C++版のDLLがあればそれを、無ければ従来のPython版（tsume.py）を使う"""
    try:
        import tsume_native as m
        m._library()
        return m
    except Exception:
        import tsume as m
        return m


def check_unique(sfen, N, kh, judge_kh, gen_checks, ms=3000):
    """初手の余詰を調べる。N手で詰む王手が複数あれば、その手のUSIを返す（唯一なら1個）。"""
    b = shogi.Board(sfen)
    wins = []
    for m in gen_checks(b):
        b.push(m)
        try:
            if N == 1:
                wins.append(m.usi())
            else:
                got = judge_kh(b, N - 1, lambda s: kh(s, ms))
                if got is not None and got[1]:
                    wins.append(m.usi())
        finally:
            b.pop()
    return wins


def _eval_check(b, m, kh, ms):
    """盤bで攻方の王手mを指したあと、玉方の全応手の先で詰むかをエンジンに聞く。
    戻り値 (判定, 手数, 手順)。判定は 'mate' / 'no' / 'unsure'。手順は、玉方がいちばん粘る応手の先まで含めたUSIのリスト"""
    _t = _backend()
    b.push(m)
    try:
        evs = _t.gen_evasions(b)
        if not evs:
            return "mate", 1, [m.usi()]                    # 1手で詰み
        evs.sort(key=lambda d: 0 if (d.from_square is not None and b.piece_at(d.from_square) is not None
                                     and b.piece_at(d.from_square).piece_type == shogi.KING) else 1)
        verdict, longest, best = "mate", 0, None
        for d in evs:
            b.push(d)
            try:
                st, pv = kh(b.sfen(), ms)
            finally:
                b.pop()
            if st == "nomate":
                return "no", 0, []
            if st != "mate":
                verdict = "unsure"              # 時間切れ。他の応手で逃れると分かれば「詰まない」になる
            else:
                if best is None or len(pv) > longest:
                    longest, best = len(pv), [d.usi()] + list(pv)
        line = [m.usi()] + (best or [])
        return verdict, 2 + longest, (line if verdict == "mate" else [])     # この王手から詰むまでの手数
    finally:
        b.pop()


def _hand_total(b):
    """攻方（先手番の問題）の持駒の合計枚数。"""
    return sum(b.pieces_in_hand[0].values()) if hasattr(b.pieces_in_hand[0], "values") else 0


def _tail_only_alt(before, ln, k, line_len, main_end_hand):
    """作意以外の手が、詰め上がり直前（攻方の最後の2手）だけの違いで、手数が同じで、駒も余らないなら True。
    これは詰将棋の慣例で余詰に数えない。k は何手目（0始まりの手番番号）、ln はその王手からの詰み手順。"""
    try:
        if k + len(ln) != line_len or k < line_len - 3:
            return False
        b = shogi.Board(before)
        for u in ln:
            b.push_usi(u)
        if not _t_is_mate(b):
            return False
        return _hand_total(b) <= main_end_hand
    except Exception:
        return False


def _t_is_mate(b):
    _t = _backend()
    return not _t.gen_evasions(b) and b.is_check()


def alt_along_line(sfen, line, kh, ms=5000, progress=None, stop=None, tail_marks=None):
    """作意の手順に沿って、攻方の各手番で、作意以外の王手が（手数に関係なく）詰むかを調べる。
    戻り値 [(何手目, その局面のSFEN, USI, 'mate' or 'unsure', 全体の詰み手数, その王手からの詰み手順(USIのリスト))]
    手数・手順は詰将棋専用エンジンのもので、無駄合を応手に数えるため、柿木将棋と手数が違うことがある"""
    _t = _backend()
    b = shogi.Board(sfen)
    out = []
    main_end_hand = 0
    try:
        bm = shogi.Board(sfen)
        for u in line:
            bm.push_usi(u)
        main_end_hand = _hand_total(bm)
    except Exception:
        tail_marks = None
    # 最終手（詰ます最後の1手）の別解は、詰将棋の慣例で不問なので調べない
    for k in range(0, len(line) - 1, 2):
        if stop is not None and stop():
            break
        before = b.sfen()
        checks = [m for m in _t.gen_checks(b) if m.usi() != line[k]]
        for i, m in enumerate(checks):
            if stop is not None and stop():
                break
            if progress:
                progress(k + 1, len(line), i + 1, len(checks))
            v, n, ln = _eval_check(b, m, kh, ms)
            if v == "mate" and tail_marks is not None and _tail_only_alt(before, ln, k, len(line), main_end_hand):
                tail_marks.add((k + 1, m.usi()))      # 最終3手の変同（同手数・駒余りなし）。画面の設定で余詰に数えるかを選ぶ
            if v in ("mate", "unsure"):
                out.append((k + 1, before, m.usi(), v, k + n if v == "mate" else 0, ln))
        b.push_usi(line[k])
        if k + 1 < len(line):
            b.push_usi(line[k + 1])
    return out


def alt_retry(items, kh, ms, progress=None, stop=None):
    """時間切れだった王手だけを、長い時間で調べ直す。items は alt_along_line の戻りのうち 'unsure' のもの。
    戻り値は同じ形のリスト（まだ判定できなければ 'unsure' のまま）。詰まないと分かったものは入らない"""
    out = []
    for j, (k, before, u, _v, _t0, _ln) in enumerate(items):
        if stop is not None and stop():
            out.append((k, before, u, "unsure", 0, []))
            continue
        if progress:
            progress(k, j + 1, len(items))
        b = shogi.Board(before)
        v, n, ln = _eval_check(b, shogi.Move.from_usi(u), kh, ms)
        if v == "mate":
            out.append((k, before, u, "mate", (k - 1) + n, ln))
        elif v == "unsure":
            out.append((k, before, u, "unsure", 0, []))
    return out


def make_problem(raw_sfen, res, label):
    h = hashlib.md5(res["sfen"].encode()).hexdigest()[:8]
    n = res["steps"]
    return {"id": f"jissen:{h}", "title": f"実戦 {n}手詰 {label}".strip(), "sfen": res["sfen"], "steps": n,
            "line": res["line"], "src": "実戦", "difficulty": None, "author": "実戦から", "likes": 0, "stars": 0,
            "raw_sfen": raw_sfen}


# ====================================================================== 画面
import threading

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
                             QTableWidget, QTableWidgetItem, QVBoxLayout, QHeaderView)


class JissenDialog(QDialog):
    """実戦の棋譜（KENTOに読み込み中の棋譜）から詰みの局面を探し、不要な駒を取り除いて問題一覧に加える。"""

    def __init__(self, win, tdlg):
        super().__init__(win)
        self.win, self.tdlg = win, tdlg
        self.setWindowTitle("実戦から詰将棋を取り出す")
        self.resize(640, 560)
        self.job = None
        self.result = None
        self.found = []
        v = QVBoxLayout(self)
        v.addWidget(QLabel("① 読み込み中の棋譜から詰みを探す② 局面を選ぶ　③ 不要な駒を取り除く　④ 問題一覧に追加"))
        r1 = QHBoxLayout()
        self.b_scan = QPushButton("この棋譜から詰みを探す")
        self.b_scan.setToolTip("棋譜の各局面で、手番側に詰みがあるかを詰将棋エンジンで調べます")
        self.b_scan.clicked.connect(self.scan)
        self.b_now = QPushButton("いま盤にある局面を対象にする")
        self.b_now.clicked.connect(self.use_current)
        self.b_stop = QPushButton("中止")
        self.b_stop.clicked.connect(self.stop)
        for b in (self.b_scan, self.b_now, self.b_stop):
            r1.addWidget(b)
        v.addLayout(r1)
        r1b = QHBoxLayout()
        r1b.addWidget(QLabel("判定エンジン"))
        self.cb_eng = QComboBox()
        self.cb_eng.addItem("棋慧エンジン（無駄合を除く・速い）")
        self.cb_eng.addItem("KomoringHeights（外部エンジン）")
        self._native_ok = native_available()
        if not self._native_ok:
            self.cb_eng.setCurrentIndex(1)
            self.cb_eng.setItemText(0, "棋慧エンジン（DLLが見つかりません）")
        self.cb_eng.setToolTip("棋慧エンジンは、無駄合を数えない詰将棋の約束で、DLLを使ってすばやく判定します（目安は15手くらいまで）。"
                               "それより長い詰みはKomoringHeightsに切り替えてください")
        r1b.addWidget(self.cb_eng)
        r1b.addWidget(QLabel("探す最長手数"))
        self.cb_len = QComboBox()
        for n in (5, 7, 9, 11, 13, 15, 99):
            self.cb_len.addItem("制限なし" if n == 99 else f"{n}手まで", n)
        self.cb_len.setCurrentIndex(2)
        self.cb_len.setToolTip("棋慧エンジンでは、手数が長いほど1局面あたりの時間が増えます。まず9手まででためすのがおすすめです")
        r1b.addWidget(self.cb_len)
        r1b.addStretch(1)
        v.addLayout(r1b)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["手数（この手を指す前）", "手番", "詰み手数"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.cellClicked.connect(lambda r, c: self.goto_row())
        v.addWidget(self.table, 1)
        self.ck_clean = QCheckBox("不要な駒を取り除く（お掃除）")
        self.ck_clean.setChecked(True)
        self.ck_uni = QCheckBox("初手の余詰も調べる（棋慧エンジンなら一瞬です。Komoringだと時間がかかります）")
        v.addWidget(self.ck_clean)
        v.addWidget(self.ck_uni)
        r2 = QHBoxLayout()
        self.b_make = QPushButton("選んだ局面を問題にする")
        self.b_make.clicked.connect(self.make)
        self.b_add = QPushButton("問題一覧に追加")
        self.b_add.setEnabled(False)
        self.b_add.clicked.connect(self.add)
        self.b_show = QPushButton("できた問題を盤に出す")
        self.b_show.setEnabled(False)
        self.b_show.clicked.connect(self.show_result)
        for b in (self.b_make, self.b_show, self.b_add):
            r2.addWidget(b)
        v.addLayout(r2)
        self.msg = QPlainTextEdit()
        self.msg.setReadOnly(True)
        self.msg.setMaximumHeight(150)
        v.addWidget(self.msg)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(300)
        self.target = None          # (sfen, ラベル)

    # ---- 共通
    def _use_native(self):
        return self._native_ok and self.cb_eng.currentIndex() == 0

    def _kh(self, sfen, ms, upto=None):
        if self._use_native():
            return native_kh(sfen, ms, upto)
        return self.win._tsume_kh(sfen, ms)

    def _run(self, fn):
        if self.job and self.job["thread"].is_alive():
            self.msg.setPlainText("いま別の処理中です。終わるか「中止」を押してください")
            return
        self.job = {"stop": False, "text": "", "done": False, "out": None, "err": None}
        job = self.job

        def work():
            try:
                job["out"] = fn(job)
            except Exception as e:
                job["err"] = str(e)
            job["done"] = True

        job["thread"] = threading.Thread(target=work, daemon=True)
        job["thread"].start()

    def stop(self):
        if self.job:
            self.job["stop"] = True

    def poll(self):
        j = self.job
        if not j:
            return
        if j["done"]:
            j["text"] = ""
            if j.get("handler"):
                h, j["handler"] = j["handler"], None
                h(j)
        elif j["text"]:
            self.msg.setPlainText(j["text"])

    # ---- 探す
    def scan(self):
        w = self.win
        sfen0, moves = w.start_sfen, list(w.moves)
        if not moves:
            self.msg.setPlainText("棋譜が読み込まれていません。先にKIFなどを開いてください")
            return
        self.table.setRowCount(0)
        max_len = int(self.cb_len.currentData() or 99)
        use_nat = self._use_native()

        def fn(job):
            def prog(i, total):
                job["text"] = f"調べています… {i}/{total - 1} 手目"
            if use_nat:
                kh = lambda sf, ms: native_kh(sf, ms, None, max_len)
            else:
                kh = self._kh
            return find_mates(sfen0, moves, kh, max_len, 1500, prog, lambda: job["stop"])

        self._run(fn)
        self.job["handler"] = self._scan_done

    def _scan_done(self, j):
        if j["err"]:
            self.msg.setPlainText("エラー: " + j["err"])
            return
        self.found = j["out"] or []
        self.table.setRowCount(len(self.found))
        for r, (i, side, n, pv) in enumerate(self.found):
            for c, val in enumerate((i, side, n)):
                it = QTableWidgetItem()
                it.setData(Qt.ItemDataRole.DisplayRole, val)
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(r, c, it)
        self.msg.setPlainText(f"{len(self.found)}か所で詰みが見つかりました。" + ("途中で中止しました。" if j["stop"] else "")
                              + "\n行をクリックすると、その局面を盤に出します。")

    def goto_row(self):
        r = self.table.currentRow()
        if 0 <= r < len(self.found):
            self.win.go_to_ply(self.found[r][0])

    def use_current(self):
        b = self.win.rebuild_board()
        self.target = (b.sfen(), f"{self.win.cursor}手目")
        self.msg.setPlainText(f"いま盤にある局面（{self.win.cursor}手目）を対象にしました。「選んだ局面を問題にする」を押してください")
        self.table.clearSelection()
        self._from_now = True

    # ---- 作る
    def _selected_target(self):
        r = self.table.currentRow()
        if r >= 0 and r < len(self.found) and not getattr(self, "_from_now", False):
            i = self.found[r][0]
            b = shogi.Board(self.win.start_sfen)
            for m in self.win.moves[:i]:
                b.push(shogi.Move.from_usi(m))
            return b.sfen(), f"{i}手目"
        if self.target:
            return self.target
        return None

    def make(self):
        self._from_now = False if self.table.currentRow() >= 0 else getattr(self, "_from_now", False)
        t = self._selected_target()
        if not t:
            self.msg.setPlainText("局面を選んでください（一覧の行、または「いま盤にある局面」）")
            return
        sfen, label = t
        names = [n for n in getattr(self.win, "names", []) if n not in ("先手", "後手")]
        if len(names) == 2:
            label = f"{names[0]}対{names[1]} {label}"
        self.result = None
        self.b_add.setEnabled(False)
        self.b_show.setEnabled(False)

        do_clean, do_uni = self.ck_clean.isChecked(), self.ck_uni.isChecked()
        use_nat = self._use_native()

        def fn(job):
            job["text"] = "詰みを確認しています…"
            if do_clean:
                cnt = [0]

                def prog(d):
                    cnt[0] += 1
                    job["text"] = f"{cnt[0]}個目：{d} を外して確かめています…（「中止」で今の状態のまま完成）"
                res = clean(sfen, self._kh, 3000, prog, lambda: job["stop"])
            else:
                b, fl = to_attacker_black(shogi.Board(sfen))
                st, pv = self._kh(_plain(b), 10000)
                res = ({"ok": True, "sfen": _plain(b), "line": pv, "steps": len(pv), "removed": [], "flipped": fl}
                       if st == "mate" and pv else {"ok": False, "msg": "詰みを確認できませんでした"})
            if res["ok"] and do_uni:
                job["stop"] = False
                job["text"] = "初手の余詰を調べています…"
                try:
                    if use_nat:
                        res["alts"] = native_unique(res["sfen"], res["steps"])
                    else:
                        import tsume_mode as T
                        res["alts"] = check_unique(res["sfen"], res["steps"], self._kh, T._judge_kh, T.solver.gen_checks, 3000)
                except Exception:
                    res["alts"] = None
            res["label"], res["raw"], res["native"] = label, sfen, use_nat
            return res

        self._run(fn)
        self.job["handler"] = self._make_done

    def _make_done(self, j):
        if j["err"]:
            self.msg.setPlainText("エラー: " + j["err"])
            return
        res = j["out"]
        if not res["ok"]:
            self.msg.setPlainText(res["msg"])
            return
        self.result = res
        alts = res.get("alts")
        if alts is None:
            u = "余詰の確認はしていません"
        elif len(alts) <= 1:
            u = "初手の余詰：なし"
        else:
            u = ("初手の余詰：あり（" if res.get("native") else "初手の余詰の可能性（") + "、".join(alts[:6]) + "）"
        rm = res["removed"]
        eng = "棋慧エンジン（無駄合を除く）" if res.get("native") else "Komoring"
        txt = f"{res['steps']}手詰になりました（{eng}で判定）。{u}\n取り除いた駒 {len(rm)}個"
        if rm:
            txt += "：" + "、".join(rm[:12]) + ("…" if len(rm) > 12 else "")
        if res.get("note"):
            txt += "\n" + res["note"]
        elif rm:
            txt += "\n（取り除いた駒は、すべて玉方の持ち駒にしています）"
        if res["flipped"]:
            txt += "\n（後手番の詰みだったので、先手が攻める向きに直しています）"
        self.msg.setPlainText(txt)
        self.b_add.setEnabled(True)
        self.b_show.setEnabled(True)

    def show_result(self):
        if self.result:
            p = make_problem(self.result["raw"], self.result, self.result["label"])
            self.win.tsume_start(p)

    def add(self):
        if not self.result or self.tdlg is None:
            return
        import tsume_mode as T
        p = make_problem(self.result["raw"], self.result, self.result["label"])
        added, _f = T.db_merge(self.tdlg.probs, [p])
        T.db_save(self.tdlg.dbpath, self.tdlg.probs)
        self.tdlg.refresh_label()
        self.tdlg.apply_filter()
        self.msg.appendPlainText("\n問題一覧に追加しました（「実戦」で検索できます）" if added else "\n同じ局面がすでに登録されています")
        self.b_add.setEnabled(False)
