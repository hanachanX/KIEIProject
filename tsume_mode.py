# -*- coding: utf-8 -*-
"""詰将棋 解答モード（問題の読み込み・正誤判定・問題一覧ダイアログ）"""
import json
import os
import random
import threading

import shogi
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                             QPushButton, QTableWidget, QTableWidgetItem, QAbstractItemView, QVBoxLayout,
                             QHeaderView)

try:
    import tsume as solver
except Exception:
    solver = None

DEFAULT_FOLDER = r"C:\FX_RISKMANAGER\TUME\data"
SOLVE_MAX_PLIES = 7      # 正解手順が無い問題で、ソルバーに判定させる残り手数の上限


# ====================================================================== 読み込み
def _read_jsonl(path, limit=None):
    out = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for i, ln in enumerate(fh):
            if limit is not None and i >= limit:
                break
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except Exception:
                pass
    return out


def _valid_sfen(s):
    try:
        shogi.Board(s)
        return True
    except Exception:
        return False


def _mk(pid, title, sfen, steps, line, src, **kw):
    d = {"id": pid, "title": title or f"{steps}手詰", "sfen": sfen, "steps": int(steps or 0),
         "line": line or None, "src": src, "difficulty": kw.get("difficulty"), "author": kw.get("author") or "",
         "likes": kw.get("likes") or 0}
    return d


def load_path(path):
    """フォルダまたはファイルから、問題の一覧を作る。"""
    files = []
    if os.path.isdir(path):
        for root, _d, names in os.walk(path):
            for n in sorted(names):
                files.append(os.path.join(root, n))
            if root.count(os.sep) - path.count(os.sep) >= 2:
                _d[:] = []
    else:
        files = [path]
    probs, sols = [], {}
    for f in files:
        ext = os.path.splitext(f)[1].lower()
        base = os.path.basename(f)
        try:
            if ext == ".jsonl":
                head = _read_jsonl(f, 1)
                if not head:
                    continue
                h = head[0]
                if "局面" in h:                       # 実戦から抜き出した詰将棋（tsume_clean.jsonl）
                    for i, r in enumerate(_read_jsonl(f)):
                        if _valid_sfen(r.get("局面", "")):
                            probs.append(_mk(f"{base}:{i}", f"{r.get('戦型', '')} {r.get('詰み手数', '')}手詰",
                                             r["局面"], r.get("詰み手数"), r.get("手順"), base))
                elif "sfen" in h and ("steps" in h or "token" in h):    # TUMEの問題一覧
                    for i, r in enumerate(_read_jsonl(f)):
                        if r.get("fairy") or not _valid_sfen(r.get("sfen", "")):
                            continue
                        line = r.get("solution")
                        if isinstance(line, str):
                            line = line.split() if line else None
                        probs.append(_mk(r.get("token") or f"{base}:{i}", r.get("title"), r["sfen"], r.get("steps"),
                                         line, base, difficulty=r.get("difficulty"), author=r.get("author"),
                                         likes=r.get("likes")))
                elif "token" in h and "line" in h and os.path.getsize(f) < 200_000_000:   # 正解手順だけのファイル
                    for r in _read_jsonl(f):
                        if r.get("line") and r.get("token"):
                            sols.setdefault(r["token"], r["line"])
            elif ext in (".kif", ".kifu"):
                import core
                g = core.load_kif(f)
                if _valid_sfen(g["sfen"]):
                    mv = list(g["moves"])
                    probs.append(_mk(f"{base}", os.path.splitext(base)[0], g["sfen"], len(mv), mv or None, base))
            elif ext in (".sfen", ".txt"):
                with open(f, encoding="utf-8", errors="replace") as fh:
                    for i, ln in enumerate(fh):
                        s = ln.strip()
                        for pre in ("position sfen ", "sfen "):
                            if s.startswith(pre):
                                s = s[len(pre):]
                        mv = None
                        if " moves " in s:
                            s, m = s.split(" moves ", 1)
                            mv = m.split()
                        s = s.strip()
                        if s and _valid_sfen(s):
                            probs.append(_mk(f"{base}:{i}", f"{os.path.splitext(base)[0]} {i + 1}", s,
                                             len(mv) if mv else 0, mv, base))
        except Exception:
            continue
    for p in probs:
        if not p["line"] and p["id"] in sols:
            p["line"] = sols[p["id"]]
    for p in probs:
        if not p["steps"] and p["line"]:
            p["steps"] = len(p["line"])
    return probs


# ====================================================================== 問題データベース（1ファイルに集約）
DB_NAME = "tsume_db.jsonl"


def sfen_key(sfen):
    return " ".join(sfen.split()[:3])        # 手数カウンタを除いた局面


def db_load(path):
    if not os.path.exists(path):
        return []
    out = _read_jsonl(path)
    for p in out:
        p.setdefault("line", None)
        p.setdefault("difficulty", None)
        p.setdefault("author", "")
        p.setdefault("likes", 0)
        p.setdefault("src", "")
        p.setdefault("stars", 0)
        p.setdefault("memo", "")
        p.setdefault("steps", len(p["line"]) if p.get("line") else 0)
    return out


def db_save(path, probs):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for p in probs:
            fh.write(json.dumps(p, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def db_merge(db, new):
    """new を db に足す。同じ局面は重複させず、足りない情報（正解手順など）だけ補う。戻り値 (追加数, 補完数)"""
    idx = {sfen_key(p["sfen"]): p for p in db}
    ids = {p["id"] for p in db}
    added = filled = 0
    for q in new:
        k = sfen_key(q["sfen"])
        p = idx.get(k)
        if p is None:
            if q["id"] in ids:
                q["id"] = f"{q['id']}#{len(db)}"
            db.append(q)
            idx[k] = q
            ids.add(q["id"])
            added += 1
        else:
            ch = False
            if not p.get("line") and q.get("line"):
                p["line"] = q["line"]
                ch = True
            if not p.get("steps") and q.get("steps"):
                p["steps"] = q["steps"]
                ch = True
            for f in ("difficulty", "author", "memo"):
                if not p.get(f) and q.get(f):
                    p[f] = q[f]
                    ch = True
            filled += ch
    return added, filled


# ====================================================================== 判定
def _board_after(sfen, moves):
    b = shogi.Board(sfen)
    for m in moves:
        b.push_usi(m)
    return b


def _best_defence(b, remaining):
    """玉方の最長抵抗（詰むまでが一番長い応手）のUSI。"""
    evs = solver.gen_evasions(b)
    best, best_len = None, -1
    for d in evs:
        b.push(d)
        L = None
        for k in range(1, remaining + 1, 2):
            if solver.can_mate(b, k):
                L = k
                break
        b.pop()
        if L is None:
            L = 99
        if L > best_len:
            best, best_len = d, L
    return best.usi() if best is not None else None


def _mated(b):
    """玉方が詰んでいるか。詰将棋のルールで、無駄合（取られても詰みが変わらない合駒）は逃れとして数えない。"""
    if solver is not None:
        try:
            return not solver.gen_evasions(b)
        except Exception:
            pass
    return b.is_checkmate()


def _escape(b, remaining):
    """詰まされない（逃れる）玉方の応手のUSI。分からなければ玉の動き優先で適当に選ぶ。"""
    evs = solver.gen_evasions(b) if solver is not None else list(b.legal_moves)
    if not evs:
        return None
    if solver is not None and remaining <= 9:
        for d in evs:
            b.push(d)
            lost = solver.can_mate(b, remaining - 1) if remaining - 1 >= 1 else False
            b.pop()
            if not lost:
                return d.usi()
    kings = [d for d in evs if d.from_square is not None and b.piece_at(d.from_square) is not None
             and b.piece_at(d.from_square).piece_type == shogi.KING]
    return (kings or evs)[0].usi()


def _escape_fast(b, remaining, budget_sec=2.0):
    """正解でない手への応手。浅い読みから順に深くしていき、詰まされない応手を選ぶ（時間で打ち切る）。"""
    import time
    evs = solver.gen_evasions(b)
    if not evs:
        return None
    alive = list(evs)
    t0 = time.time()
    k = 1
    while k <= min(remaining - 1, 7) and len(alive) > 0:
        nxt = []
        for d in alive:
            b.push(d)
            lost = solver.can_mate(b, k)
            b.pop()
            if not lost:
                nxt.append(d)
            if time.time() - t0 > budget_sec:
                break
        else:
            if not nxt:          # このk手で全部詰まされる：直前まで生き残った中から選ぶ
                break
            alive = nxt
            k += 2
            continue
        # 時間切れ：途中までの結果で、詰まされると分かった手を除く
        done = set(id(x) for x in nxt)
        if nxt:
            alive = nxt
        break
    kings = [d for d in alive if d.from_square is not None and b.piece_at(d.from_square) is not None
             and b.piece_at(d.from_square).piece_type == shogi.KING]
    return (kings or alive)[0].usi()


def normalize_pv(sfen, pv, kh):
    """専用エンジンの詰み手順を、詰将棋の作意らしく整える。
    玉方の応手が「合駒（駒を打つ手）」で、同じ長さで詰む「駒を打たない応手（王手の駒を取る手・玉を動かす手など）」が
    あれば、そちらに置き換える（最長手数は変えない）。駒余りや無駄な合駒の手順になるのを避けるため。"""
    try:
        pos = shogi.Board(sfen)
        pv = list(pv)
        i = 0
        while i < len(pv):
            pos.push_usi(pv[i])
            if i + 1 >= len(pv):
                break
            mv = shogi.Move.from_usi(pv[i + 1])
            if mv.drop_piece_type is not None:                 # 玉方の合駒
                rest = len(pv) - (i + 2)                       # 玉方が応じたあとに残る手数
                evs = [d for d in solver.gen_evasions(pos) if d.drop_piece_type is None]
                # 王手の駒を取る手を先に調べる
                evs.sort(key=lambda d: 0 if pos.piece_at(d.to_square) is not None else 1)
                for d in evs:
                    pos.push(d)
                    try:
                        st, pv2 = kh(pos.sfen())
                    finally:
                        pos.pop()
                    if st == "mate" and pv2 and len(pv2) == rest:
                        pv = pv[:i + 1] + [d.usi()] + list(pv2)
                        break
            pos.push_usi(pv[i + 1])
            i += 2
        return pv
    except Exception:
        return list(pv)


_PV_CACHE = {}      # 局面(攻方番のSFEN) -> (状態, 詰み手順)  専用エンジンの答えを覚えておく


def _kh_follow(sfen_before, usi, remaining_total, kh):
    """攻方番の局面から専用エンジンを1回だけ呼び、その最短の詰み手順(玉方は最長抵抗)に沿っていれば、
    次の応手を返す。戻り値: ("done", None) / ("reply", USI) / None（手順に沿っていない・分からない）。"""
    key = sfen_before
    if key not in _PV_CACHE:
        if len(_PV_CACHE) > 400:
            _PV_CACHE.clear()
        st0, pv0 = kh(key)
        if st0 == "mate" and pv0:
            pv0 = normalize_pv(key, pv0, kh)
        _PV_CACHE[key] = (st0, pv0)
    st, pv = _PV_CACHE[key]
    if st != "mate" or not pv or len(pv) > remaining_total or pv[0] != usi:
        return None
    if len(pv) == 1:
        return "done", None
    return "reply", pv[1]


def _kh_remember(sfen_after_reply, rest):
    """手順に沿って進んだ先の局面の答えも、エンジンを呼ばずに分かるよう覚えておく。"""
    if rest:
        _PV_CACHE[sfen_after_reply] = ("mate", list(rest))


def _judge_kh(b, remaining, kh):
    """詰将棋専用エンジンで、玉方の応手を決める。bは攻方の手を指した後（玉方番・王手中）。
    各応手のあとの詰み手数をエンジンに聞き、全応手が手数内に詰むなら「最長抵抗」を、詰まない応手があればそれを返す。
    戻り値: (還り値の応手USI, 手数内に詰む局面か) 。エンジンが使えないときは None。"""
    INF = 10 ** 6
    evs = solver.gen_evasions(b)
    if not evs:
        return None
    # 玉の動きを先に調べる（詰まない応手が見つかりやすい）
    evs.sort(key=lambda d: 0 if (d.from_square is not None and b.piece_at(d.from_square) is not None
                                 and b.piece_at(d.from_square).piece_type == shogi.KING) else 1)
    res = []
    for d in evs:
        b.push(d)
        try:
            state, pv = kh(b.sfen())
        finally:
            b.pop()
        if state == "mate" and pv:
            L = len(pv)
        elif state == "nomate":
            L = INF
        elif state == "timeout":
            L = INF - 1            # 時間切れ＝かなり長い（逃れている可能性が高い）として扱う
        else:
            return None            # エンジンの異常。従来の方法に切り替える
        if L > remaining - 1 and remaining - 1 >= 1 and remaining <= 9:
            # エンジンは無駄合を逃れとして数えるため、手数が延びて見えることがある。
            # 詰将棋のルール（無駄合は数えない）の自前ソルバーで詰むと分かれば、そちらを信じる
            try:
                b.push(d)
                try:
                    ok = solver.can_mate(b, remaining - 1)
                finally:
                    b.pop()
                if ok:
                    L = remaining - 1
            except Exception:
                pass
        res.append((L, d))
        if L > remaining - 1:      # 手数内に詰まない応手が見つかった（以降は調べなくてよい）
            return d.usi(), False
    # 同じ長さなら、合駒（駒を打つ手）より、駒を取る手・玉を動かす手を選ぶ
    best = max(res, key=lambda t: (t[0], t[1].drop_piece_type is None, b.piece_at(t[1].to_square) is not None))
    return best[1].usi(), True


def judge(sfen, moves, usi, steps, line, emate=None, tree=None, kh=None):
    """利用者の攻方の手 usi を受け付け、玉方の応手を決める。間違いは、その場では知らせない（最後まで指させる）。
    戻り値 dict: ok(受け付けたか), msg, reply(玉方の応手 or None), done(詰み達成), fail(手数内に詰まず失敗)"""
    idx = len(moves)
    R = lambda ok, msg, reply=None, done=False, fail=False: {"ok": ok, "msg": msg, "reply": reply, "done": done, "fail": fail}
    try:
        if idx >= steps:
            return R(False, "手数を超えています。「初形に戻す」でやり直してください")
        b = _board_after(sfen, moves)
        sfen_before = b.sfen()
        if tree:
            # 事前に計算した「正解の手→玉方の最長抵抗」の表で、すぐに判定する
            key = " ".join(list(moves) + [usi])
            if key in tree:
                b.push_usi(usi)
                if not b.is_check():
                    return R(False, "王手になっていません（詰将棋は王手の連続です）")
                rep = tree[key]
                if rep == "" or _mated(b):
                    return R(True, "詰みました", done=True)
                return R(True, "", rep)
        on_line = bool(line) and moves == line[:idx] and idx < len(line) and usi == line[idx]
        b.push_usi(usi)
        if not b.is_check():
            return R(False, "王手になっていません（詰将棋は王手の連続です）")
        if _mated(b):
            return R(True, "詰みました", done=True)
        remaining = steps - (idx + 1)
        if kh is not None and solver is not None:
            # まず、専用エンジンの最短手順に沿っているか（1回の探索で済む）
            try:
                fol = _kh_follow(sfen_before, usi, steps - idx, kh)
            except Exception:
                fol = None
            if fol is not None:
                if fol[0] == "done":
                    return R(True, "詰みました", done=True)
                try:
                    bb = shogi.Board(b.sfen())
                    bb.push_usi(fol[1])
                    st_, pv_ = _PV_CACHE.get(sfen_before, (None, None))
                    _kh_remember(bb.sfen(), pv_[2:] if pv_ else None)
                except Exception:
                    pass
                return R(True, "", fol[1])
        if remaining < 2:
            return R(True, "手数切れ", fail=True)
        if on_line:
            return R(True, "", line[idx + 1] if idx + 1 < len(line) else _escape(b, remaining))
        if kh is not None and solver is not None:
            # 詰将棋専用エンジンで、玉方の最長抵抗（または逃れる手）を正確に決める
            try:
                got = _judge_kh(b, remaining, kh)
            except Exception:
                got = None
            if got is not None:
                return R(True, "", got[0])
        if tree and solver is not None:
            # 表に無い王手は正解の手ではない。重い探索はせず、逃れる応手をすぐ返す
            return R(True, "", _escape_fast(b, remaining))
        # 手順と違う手：まだ詰むなら最長抵抗、もう詰まないなら逃れる応手を指す
        still = None
        if solver is not None and remaining <= 9 and solver.defenders_all_lose(b, remaining):
            return R(True, "", _best_defence(b, remaining))
        if emate is not None and (solver is None or remaining > 9):   # 長い問題だけ、エンジンの詰み探索を使う
            state, pv = emate(b.sfen())
            if state == "mate" and pv and len(pv) <= remaining:
                return R(True, "", pv[0])
            still = False
        return R(True, "", _escape(b, remaining))
    except Exception as e:
        return R(False, f"判定でエラー: {e}")


def solve_line(sfen, steps):
    """正解手順の無い問題を、ソルバーで解く（USIのリストか、解けなければNone）。"""
    if solver is None or steps > 9:
        return None
    try:
        b = shogi.Board(sfen)
        solver.clear_cache()
        wins = solver.solve(b, steps)
        if not wins:
            return None
        line, remaining = [], steps
        a = wins[0]
        while True:
            line.append(a.usi())
            b.push(a)
            if not solver.gen_evasions(b):
                break
            d = _best_defence(b, remaining - 2)
            if d is None:
                break
            line.append(d)
            b.push_usi(d)
            remaining -= 2
            ws = solver.solve(b, remaining)
            if not ws:
                return None
            a = ws[0]
        return line
    except Exception:
        return None


# ====================================================================== 余詰の結果
class AltResultDialog(QDialog):
    """余詰検査の結果。文章はコピーでき、時間切れの王手は長い時間で調べ直せ、手順は変化つきのKIFで保存・コピーできる。"""

    def __init__(self, parent, win, sfen, line, out, ms, stopped=False, target=None, tdlg=None):
        super().__init__(parent)
        self.target, self.tdlg = target, tdlg
        from PyQt6.QtWidgets import QPlainTextEdit
        self.win, self.sfen, self.line, self.ms, self.stopped = win, sfen, line, ms, stopped
        self.out = list(out or [])
        self.job = None
        self.setWindowTitle("余詰の確認")
        self.resize(760, 620)
        v = QVBoxLayout(self)
        self.box = QPlainTextEdit()
        self.box.setReadOnly(True)
        self.box.setStyleSheet("font-family: 'MS Gothic', 'Consolas', monospace; font-size: 13px;")
        v.addWidget(self.box, 1)
        self.lab = QLabel("")
        v.addWidget(self.lab)
        row = QHBoxLayout()
        self.b_copy = QPushButton("文章をコピー")
        self.b_copy.clicked.connect(self.copy_text)
        self.b_retry = QPushButton("時間切れを長い時間で調べ直す")
        self.b_retry.setToolTip("時間内に判定できなかった王手だけを、1手あたり30秒まで使って調べ直します。もう一度押すと中止")
        self.b_retry.clicked.connect(self.retry)
        self.b_kifcopy = QPushButton("余詰の手順をKIFでコピー")
        self.b_kifcopy.setToolTip("作意を本手順、見つかった余詰を「変化」にしたKIFを、クリップボードに入れます（KENTOや柿木将棋で開けます）")
        self.b_kifcopy.clicked.connect(self.copy_kif)
        self.b_kifsave = QPushButton("KIFで保存…")
        self.b_kifsave.clicked.connect(self.save_kif)
        self.b_memo = QPushButton("結果をメモに書き込む")
        self.b_memo.setToolTip("この余詰検査の結果（日付つき）を、問題一覧のメモ欄の末尾に書き足します")
        self.b_memo.clicked.connect(self.write_memo)
        self.b_memo.setEnabled(target is not None)
        b_close = QPushButton("閉じる")
        b_close.clicked.connect(self.accept)
        for b in (self.b_copy, self.b_retry, self.b_kifcopy, self.b_kifsave, self.b_memo, b_close):
            row.addWidget(b)
        v.addLayout(row)
        self.rebuild()

    def write_memo(self):
        import datetime
        found, unsure, n = self._items()
        d = datetime.date.today().isoformat()
        if found:
            parts = []
            for k, name, tot, pv, ln, _b in found:
                parts.append(f"{k}手目{name}(全{tot}手)")
            txt = f"[{d} 余詰検査] 余詰あり {len(found)}か所：" + "、".join(parts)
        else:
            txt = f"[{d} 余詰検査] 余詰なし（最終手の別解は不問）"
        if unsure:
            txt += f"／判定できず {len(unsure)}手：" + "、".join(f"{k}手目{name}" for k, name in unsure)
        if self.stopped:
            txt += "／途中で中止"
        old = (self.target.get("memo") or "").strip()
        self.target["memo"] = (old + "\n" if old else "") + txt
        db_save(self.tdlg.dbpath, self.tdlg.probs)
        self.tdlg.apply_filter()
        self.b_memo.setEnabled(False)
        self.b_memo.setText("メモに書き込みました")
        self.win.status.setText("余詰検査の結果をメモに書き込みました")

    # ---- 文章
    def _items(self):
        import core
        found, unsure = [], []
        n = len(self.line)
        for k, bsfen, u, vv, tot, ln in self.out:
            try:
                bd = shogi.Board(bsfen)
                name = core.move_ja(bd, u)
                pv = core.pv_ja(bd, ln, 120) if ln else ""
            except Exception:
                name, pv = u, ""
            if vv == "mate":
                found.append((k, name, tot, pv, ln, bsfen))
            else:
                unsure.append((k, name))
        return found, unsure, n

    def rebuild(self):
        found, unsure, n = self._items()
        t = []
        if found:
            t.append(f"【余詰あり】作意（{n}手）以外の手順でも詰みます（{len(found)}か所）。作品として不完全です。")
            t.append("※手数と手順は詰将棋エンジンのもので、無駄合を応手に数えるため、柿木将棋と手数が違うことがあります。")
            t.append("")
            for k, name, tot, pv, ln, _b in found:
                tag = "（作意より短い）" if tot < n else ""
                t.append(f"■ {k}手目 {name}　全{tot}手{tag}")
                if pv:
                    t.append("   手順：" + pv)
                t.append("")
        else:
            t.append("作意の手順上では、作意以外の王手で詰む手は見つかりませんでした。")
            t.append("")
        if unsure:
            t.append(f"【時間内に判定できなかった王手】{len(unsure)}手（詰む可能性があります）")
            t.append("、".join(f"{k}手目 {name}" for k, name in unsure))
            t.append("")
        t.append(f"※最終手（{n}手目）の別解は、詰将棋の慣例にならい不問として、調べていません。")
        if self.stopped:
            t.append("（途中で中止しました。調べていない手があります）")
        self.box.setPlainText("\n".join(t))
        self.b_retry.setEnabled(bool(unsure) and self.job is None or (self.job is not None))
        self.b_retry.setText("時間切れを長い時間で調べ直す" if self.job is None else "中止")
        self.b_kifcopy.setEnabled(bool(found))
        self.b_kifsave.setEnabled(bool(found))

    def copy_text(self):
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.box.toPlainText())
        self.lab.setText("文章をコピーしました")

    # ---- 調べ直し
    def retry(self):
        import tsume_jissen
        from PyQt6.QtCore import QTimer
        if self.job is not None:
            self.job["stop"] = True
            return
        items = [x for x in self.out if x[3] != "mate"]
        if not items:
            return
        job = {"stop": False, "done": False, "text": "調べ直しています…", "res": None}
        self.job = job
        win = self.win

        def work():
            try:
                job["res"] = tsume_jissen.alt_retry(
                    items, lambda s, m: win._tsume_kh(s, m), 30000,
                    lambda k, i, n: job.__setitem__("text", f"時間切れの王手を調べ直しています… {i}/{n}（作意の{k}手目）"),
                    lambda: job["stop"])
            except Exception as e:
                job["res"] = items
                job["text"] = "エラー：" + str(e)
            job["done"] = True

        threading.Thread(target=work, daemon=True).start()
        self.b_retry.setText("中止")
        tm = QTimer(self)

        def tick():
            self.lab.setText(job["text"])
            if job["done"]:
                tm.stop()
                done = [x for x in self.out if x[3] == "mate"]
                self.out = sorted(done + list(job["res"] or []), key=lambda x: x[0])
                if job["stop"]:
                    self.stopped = True
                self.job = None
                self.lab.setText("調べ直しが終わりました")
                self.rebuild()

        tm.timeout.connect(tick)
        tm.start(400)

    # ---- KIF
    def kif_text(self):
        import core
        vars_ = []
        for k, bsfen, u, vv, tot, ln in self.out:
            if vv != "mate" or not ln:
                continue
            try:
                prefix = list(self.line[:k - 1])
                vars_.append({"from": k, "prefix": prefix, "moves": list(ln), "parent": -1, "end": "詰み",
                              "comments": {k: f"【余詰】全{tot}手（無駄合を含む手数）"}})
            except Exception:
                continue
        return core.export_kif(self.sfen, self.line, ["先手", "後手"], None, variations=vars_)

    def copy_kif(self):
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.kif_text())
        self.lab.setText("KIFをコピーしました（KENTOの「KIFを貼り付け」や柿木将棋で開けます）")

    def save_kif(self):
        import core
        path, _ = QFileDialog.getSaveFileName(self, "余詰つきKIFを保存", "yozume.kif", "KIF（Shift-JIS）(*.kif);;KIFU（UTF-8）(*.kifu)")
        if not path:
            return
        utf8 = path.lower().endswith(".kifu")
        try:
            with open(path, "wb") as f:
                f.write(core.kif_bytes(self.kif_text(), utf8))
            self.lab.setText("保存しました：" + path)
        except OSError as e:
            self.lab.setText("保存できませんでした：" + str(e))


# ====================================================================== 一覧ダイアログ
class TsumeDialog(QDialog):
    def __init__(self, win, dbpath, state):
        super().__init__(win)
        self.win = win
        self.state = state          # {"solved": {id: True}}
        self.probs = []
        self.shown = []
        self.dbpath = dbpath
        self.setWindowTitle("詰将棋 問題一覧")
        self.resize(760, 640)
        v = QVBoxLayout(self)
        top = QHBoxLayout()
        self.path_label = QLabel("")
        self.path_label.setWordWrap(True)
        b1 = QPushButton("フォルダから追加…")
        b1.setToolTip("フォルダの中の詰将棋（jsonl・kif・sfen・txt）を、このデータベースに取り込みます")
        b1.clicked.connect(self.pick_folder)
        b2 = QPushButton("ファイルから追加…")
        b2.clicked.connect(self.pick_file)
        b3 = QPushButton("いまの盤面を追加")
        b3.setToolTip("KENTOの盤にある局面（手順があれば正解手順として）を問題に加えます")
        b3.clicked.connect(self.add_current)
        b6 = QPushButton("余詰を調べる")
        b6.setToolTip("出題中の問題で、作意の手順の各局面に、作意以外の手順で詰む王手（余詰）がないか、詰将棋エンジンで調べます。時間がかかります")
        b6.clicked.connect(self.check_alt)
        b5 = QPushButton("実戦から作る…")
        b5.setToolTip("読み込んだ棋譜から詰みの局面を探して、問題にします")
        b5.clicked.connect(self.open_jissen)
        top.addWidget(self.path_label, 1)
        for b in (b1, b2, b3, b5, b6):
            top.addWidget(b)
        v.addLayout(top)
        fl = QHBoxLayout()
        self.cb_steps = QComboBox()
        self.cb_steps.addItem("手数：すべて", 0)
        for n in (3, 5, 7, 9, 11, 13, 15):
            self.cb_steps.addItem(f"{n}手詰", n)
        self.cb_steps.addItem("17手以上", 17)
        self.cb_diff = QComboBox()
        self.cb_diff.addItem("難易度：すべて", 0)
        for n in range(1, 8):
            self.cb_diff.addItem(f"難易度 {n}", n)
        self.cb_star = QComboBox()
        for lab, sval in (("評価：すべて", -1), ("未評価（★0）", 0), ("★1以上", 1), ("★2以上", 2), ("★3以上", 3), ("★4以上", 4), ("★5のみ", 5)):
            self.cb_star.addItem(lab, sval)
        self.cb_star.currentIndexChanged.connect(self.apply_filter)
        self.ck_unsolved = QCheckBox("未解答のみ")
        self.ck_ready = QCheckBox("正解データ有りのみ")
        self.ck_hidden = QCheckBox("外したものも表示")
        self.ed = QLineEdit()
        self.ed.setPlaceholderText("タイトル・作者・メモで検索")
        for w in (self.cb_steps, self.cb_diff):
            w.currentIndexChanged.connect(self.apply_filter)
        for w in (self.ck_unsolved, self.ck_ready, self.ck_hidden):
            w.stateChanged.connect(self.apply_filter)
        self.ed.textChanged.connect(self.apply_filter)
        for w in (self.cb_steps, self.cb_diff, self.cb_star, self.ck_unsolved, self.ck_ready, self.ck_hidden):
            fl.addWidget(w)
        fl.addWidget(self.ed, 1)
        v.addLayout(fl)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["No", "タイトル", "手数", "難易度", "作者", "状態", "評価", "メモ"])
        self.table.setColumnWidth(7, 220)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSortingEnabled(True)
        self.table.cellDoubleClicked.connect(lambda r, c: self.start_selected())
        v.addWidget(self.table, 1)
        self.count = QLabel("")
        v.addWidget(self.count)
        rl = QHBoxLayout()
        rl.addWidget(QLabel("選んだ問題を評価："))
        for n in range(6):
            b = QPushButton("未評価" if n == 0 else "★" * n)
            b.setToolTip("星0は未評価（まだ解いていない・評価していない）。1〜5で自分の評価をつけます")
            b.clicked.connect(lambda _c=False, n=n: self.rate(n))
            rl.addWidget(b)
        rl.addStretch(1)
        be = QPushButton("タイトル・作者・難易度・メモを編集…")
        be.setToolTip("選んだ問題（または出題中の問題）のタイトル・作者・難易度・メモ（余詰の注意・制作日などの雑メモ）を書き換えます")
        be.clicked.connect(self.edit_info)
        rl.addWidget(be)
        v.addLayout(rl)
        bl = QHBoxLayout()
        for text, fn in [("出題", self.start_selected), ("一覧から外す／戻す", self.toggle_hidden), ("ランダム出題", self.start_random),
                         ("次の問題", self.start_next), ("ヒント", lambda: self.win.tsume_hint()),
                         ("答えを見る", lambda: self.win.tsume_answer()),
                         ("初形に戻す", lambda: self.win.tsume_reset()),
                         ("詰将棋モードを終える", lambda: self.win.tsume_exit())]:
            b = QPushButton(text)
            b.clicked.connect(fn)
            bl.addWidget(b)
        v.addLayout(bl)
        self.probs = db_load(dbpath)
        self.refresh_label()
        self.apply_filter()

    def check_alt(self):
        import threading
        import tsume_jissen
        from PyQt6.QtCore import QTimer
        cur = self.win.tsume.get("prob") if getattr(self.win, "tsume", None) else None
        if cur:
            sfen, line = cur["sfen"], cur.get("line")
        else:
            # 出題中でなければ、KIFを開いている局面（初形と手順）を調べる
            sfen = getattr(self.win, "start_sfen", None)
            line = list(getattr(self.win, "moves", []) or [])
            if not sfen or not line:
                self.win.status.setText("先に問題を出題するか、手順つきのKIFを開いてください")
                return
        if getattr(self, "_alt_job", None) and not self._alt_job["done"]:
            self._alt_job["stop"] = True
            return
        if not line:
            self.win.status.setText("この問題には正解手順がないため調べられません")
            return
        target = None
        key = sfen_key(sfen)
        if cur:
            target = next((q for q in self.probs if q["id"] == cur["id"]), None)
        if target is None:
            target = next((q for q in self.probs if sfen_key(q["sfen"]) == key), None)
        job = {"stop": False, "done": False, "text": "調べています…（もう一度押すと中止）", "out": None}
        self._alt_job = job
        win = self.win
        line = list(line)
        ms = 5000

        def work():
            try:
                job["out"] = tsume_jissen.alt_along_line(
                    sfen, line, lambda s, m: win._tsume_kh(s, m), ms,
                    lambda k, n, i, m: job.__setitem__("text", f"作意の{k}手目（全{n}手）の別の王手を調べています… {i}/{m}"),
                    lambda: job["stop"])
            except Exception as e:
                job["out"] = []
                job["text"] = "エラー：" + str(e)
            job["done"] = True

        threading.Thread(target=work, daemon=True).start()
        tm = QTimer(self)

        def tick():
            win.status.setText(job["text"])
            if job["done"]:
                tm.stop()
                dlg = AltResultDialog(self, win, sfen, line, job["out"], ms, stopped=job["stop"], target=target, tdlg=self)
                dlg.exec()

        tm.timeout.connect(tick)
        tm.start(400)

    def open_jissen(self):
        import tsume_jissen
        if getattr(self, "jissen_dlg", None) is None:
            self.jissen_dlg = tsume_jissen.JissenDialog(self.win, self)
        self.jissen_dlg.show()
        self.jissen_dlg.raise_()

    # ---- データベースへの追加
    def refresh_label(self):
        self.path_label.setText(f"{self.dbpath}　（{len(self.probs)}問）")

    def import_path(self, path):
        from PyQt6.QtWidgets import QApplication, QMessageBox
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            new = load_path(path)
            added, filled = db_merge(self.probs, new)
            db_save(self.dbpath, self.probs)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "取り込めません", str(e))
            return
        QApplication.restoreOverrideCursor()
        self.refresh_label()
        self.apply_filter()
        self.win.status.setText(f"{len(new)}問を読み込み：新しく{added}問を追加、{filled}問の足りない情報を補いました")

    def pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, "取り込む詰将棋のフォルダ", DEFAULT_FOLDER if os.path.isdir(DEFAULT_FOLDER) else "")
        if d:
            self.import_path(d)

    def pick_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "取り込む詰将棋のファイル", "",
                                           "詰将棋 (*.jsonl *.kif *.kifu *.sfen *.txt);;すべて (*)")
        if f:
            self.import_path(f)

    def add_current(self):
        from PyQt6.QtWidgets import QInputDialog, QMessageBox
        w = self.win
        sfen, mv = w.start_sfen, list(w.moves)
        steps = len(mv)
        if not _valid_sfen(sfen):
            return
        if not mv:
            steps, ok = QInputDialog.getInt(self, "手数", "何手詰ですか？（正解手順は付きません）", 3, 1, 99, 2)
            if not ok:
                return
        title, ok = QInputDialog.getText(self, "タイトル", "タイトル：", text=f"{steps}手詰")
        if not ok:
            return
        q = _mk(f"user:{len(self.probs)}:{abs(hash(sfen)) % 100000}", title.strip() or f"{steps}手詰", sfen, steps, mv or None, "手動追加")
        added, _f = db_merge(self.probs, [q])
        if not added:
            QMessageBox.information(self, "追加", "同じ局面がすでに登録されています（足りない情報だけ補いました）")
        db_save(self.dbpath, self.probs)
        self.refresh_label()
        self.apply_filter()

    # ---- 一覧
    def status_of(self, p):
        if p.get("hidden"):
            return "外した"
        if self.state["solved"].get(p["id"]):
            return "解いた"
        return "未解答"

    def apply_filter(self):
        n = self.cb_steps.currentData()
        dmin = self.cb_diff.currentData()
        kw = self.ed.text().strip()
        out = []
        for p in self.probs:
            if n == 17 and p["steps"] < 17 or n and n != 17 and p["steps"] != n:
                continue
            if p.get("hidden") and not self.ck_hidden.isChecked():
                continue
            if dmin and p["difficulty"] != dmin:
                continue
            if self.ck_unsolved.isChecked() and self.state["solved"].get(p["id"]):
                continue
            sv = self.cb_star.currentData()
            st = p.get("stars", 0) or 0
            if sv == 0 and st != 0 or sv and sv > 0 and (st < sv or sv == 5 and st != 5):
                continue
            if self.ck_ready.isChecked() and not p["line"]:
                continue
            if kw and kw not in p["title"] and kw not in p["author"] and kw not in (p.get("memo") or ""):
                continue
            out.append(p)
        self.shown = out
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(out))
        for r, p in enumerate(out):
            vals = [r + 1, p["title"], p["steps"], p["difficulty"] if p["difficulty"] is not None else "",
                    p["author"], self.status_of(p), "★" * (p.get("stars", 0) or 0) or "－",
                    (p.get("memo") or "").replace("\n", " ")]
            for c, val in enumerate(vals):
                it = QTableWidgetItem()
                it.setData(Qt.ItemDataRole.DisplayRole, val)
                if c == 0:
                    it.setData(Qt.ItemDataRole.UserRole, r)
                self.table.setItem(r, c, it)
        self.table.setSortingEnabled(True)
        self.count.setText(f"{len(out)}問を表示　（解いた {sum(1 for p in out if self.state['solved'].get(p['id']))}問）")

    def selected_prob(self):
        r = self.table.currentRow()
        if r < 0:
            return None
        it = self.table.item(r, 0)
        if it is None:
            return None
        return self.shown[it.data(Qt.ItemDataRole.UserRole)]

    def rate(self, n):
        p = self.selected_prob()
        if not p:
            cur = self.win.tsume.get("prob") if getattr(self.win, "tsume", None) else None
            p = next((q for q in self.probs if cur and q["id"] == cur["id"]), None)
        if not p:
            self.win.status.setText("評価する問題を一覧から選んでください")
            return
        p["stars"] = n
        db_save(self.dbpath, self.probs)
        for r in range(self.table.rowCount()):
            if self.shown[self.table.item(r, 0).data(Qt.ItemDataRole.UserRole)]["id"] == p["id"]:
                self.table.item(r, 6).setText("★" * n or "－")
        self.win.status.setText(f"「{p['title']}」を {'未評価' if n == 0 else '★' * n} にしました")

    def edit_info(self):
        from PyQt6.QtWidgets import QDialogButtonBox, QFormLayout, QPlainTextEdit, QSpinBox
        p = self.selected_prob()
        if not p:
            cur = self.win.tsume.get("prob") if getattr(self.win, "tsume", None) else None
            p = next((q for q in self.probs if cur and q["id"] == cur["id"]), None)
        if not p:
            self.win.status.setText("編集する問題を一覧から選んでください")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("問題の情報を編集")
        form = QFormLayout(dlg)
        ed_t = QLineEdit(p.get("title") or "")
        ed_a = QLineEdit(p.get("author") or "")
        sp = QSpinBox()
        sp.setRange(0, 9)
        sp.setSpecialValueText("なし")
        sp.setValue(p.get("difficulty") or 0)
        form.addRow("タイトル", ed_t)
        form.addRow("作者", ed_a)
        form.addRow("難易度", sp)
        ed_m = QPlainTextEdit(p.get("memo") or "")
        ed_m.setPlaceholderText("例：9手目に別解あり（最終手は不問）／2026-10-29 制作")
        ed_m.setFixedHeight(90)
        form.addRow("メモ", ed_m)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        p["title"] = ed_t.text().strip() or p.get("title") or ""
        p["author"] = ed_a.text().strip()
        p["difficulty"] = sp.value() or None
        p["memo"] = ed_m.toPlainText().strip()
        db_save(self.dbpath, self.probs)
        self.apply_filter()
        self.win.status.setText(f"「{p['title']}」の情報を更新しました")

    def toggle_hidden(self):
        """選んだ問題を一覧から外す（データは消さない）。外したものは「外したものも表示」で出して、戻せる。"""
        p = self.selected_prob()
        if not p:
            self.win.status.setText("外す問題を一覧から選んでください")
            return
        if p.get("hidden"):
            p.pop("hidden", None)
            msg = "一覧に戻しました"
        else:
            p["hidden"] = True
            msg = "一覧から外しました（データは残っています。「外したものも表示」で戻せます）"
        db_save(self.dbpath, self.probs)
        row = self.table.currentRow()
        self.apply_filter()
        if self.table.rowCount():
            self.table.selectRow(min(row, self.table.rowCount() - 1))
        self.win.status.setText(msg)

    def start_selected(self):
        p = self.selected_prob()
        if p:
            self.win.tsume_start(p)

    def start_random(self):
        cand = [p for p in self.shown if not self.state["solved"].get(p["id"])] or self.shown
        if cand:
            p = random.choice(cand)
            self._select(p)
            self.win.tsume_start(p)

    def start_next(self):
        cur = self.win.tsume.get("prob") if self.win.tsume else None
        ids = [self.table.item(r, 0).data(Qt.ItemDataRole.UserRole) for r in range(self.table.rowCount())]
        start = 0
        if cur is not None:
            for r in range(self.table.rowCount()):
                if self.shown[ids[r]]["id"] == cur["id"]:
                    start = r + 1
                    break
        for r in range(start, self.table.rowCount()):
            p = self.shown[ids[r]]
            if not self.state["solved"].get(p["id"]):
                self.table.selectRow(r)
                self.win.tsume_start(p)
                return
        self.win.status.setText("この一覧には、これ以上の未解答の問題はありません")

    def _select(self, p):
        for r in range(self.table.rowCount()):
            if self.shown[self.table.item(r, 0).data(Qt.ItemDataRole.UserRole)]["id"] == p["id"]:
                self.table.selectRow(r)
                return

    def mark_solved(self, p):
        self.state["solved"][p["id"]] = True
        for r in range(self.table.rowCount()):
            if self.shown[self.table.item(r, 0).data(Qt.ItemDataRole.UserRole)]["id"] == p["id"]:
                self.table.item(r, 5).setText("解いた")
        self.count.setText(f"{len(self.shown)}問を表示　（解いた {sum(1 for q in self.shown if self.state['solved'].get(q['id']))}問）")


def engine_line(sfen, steps, emate):
    """エンジンの詰み探索で、初形からの手順を得る（USIのリスト or None）。"""
    state, pv = emate(sfen)
    if state == "mate" and pv:
        return list(pv)
    return None
