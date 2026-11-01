"""検証役: 作意手順の各場面で、玉方の応手を「有効/無駄合」に分け、正しい残り手数と攻め方の別解を調べる。"""
import shogi, tsume_native as T

def _remaining(b, maxp):
    for p in range(1, maxp + 1, 2):
        if T.can_mate(b, p):
            return p
    return None

def is_futile(b, drop_usi, n):
    """b: 王手がかかった局面(玉方手番)。drop_usi: 合駒の打ち方。n: 残り手数(玉方の手を含む)。"""
    # 王手している遠隔駒の位置を探す
    ksq = b.king_squares[b.turn]
    att = [sq for sq in b.attackers(1 - b.turn, ksq)]
    if len(att) != 1:
        return False
    a = att[0]
    conv = lambda sq: sq   # python-shogi と native の升番号は同じ
    text = b.sfen() + "\n" + drop_usi
    return T._run("futile", text=text, n=conv(a), budget=n) == "1"

def replies(b, n):
    """b: 玉方手番の局面。各応手について (usi, 種別, 残り手数) を返す。種別: '玉移動など'/'合駒'/'無駄合'"""
    res = []
    for m in b.legal_moves:
        u = m.usi()
        q = shogi.Board(b.sfen()); q.push(m)
        if m.from_square is None or u[1] == '*':
            if is_futile(b, u, n):
                res.append((u, '無駄合', None)); continue
            kind = '合駒'
        else:
            kind = '通常'
        L = _remaining(q, n - 1)
        res.append((u, kind, L))
    return res

def attacker_wins(b, n):
    out = []
    for m in b.legal_moves:
        q = shogi.Board(b.sfen()); q.push(m)
        if not q.is_check():
            continue
        if n == 1:
            if not T.gen_evasions(q): out.append(m.usi())
        elif T.defenders_all_lose(q, n - 1):
            out.append(m.usi())
    return out

def report(sfen, first_moves, total, out=print):
    """first_moves: 作意の先頭から確定している手(攻め方の手で終わる)。total: 全手数。"""
    b = shogi.Board(sfen)
    for u in first_moves: b.push_usi(u)
    ply = len(first_moves)
    while True:
        n = total - ply                      # 玉方手番での残り手数
        rep = replies(b, n)
        out(f"--- {ply}手目まで({first_moves[-1] if first_moves else ''})・玉方の応手 (残り{n}手) ---")
        valid = [r for r in rep if r[1] != '無駄合' and r[2] is not None]
        for u, k, L in rep:
            out(f"   {u:6s} {k:4s} " + ("-" if L is None else f"残り{L}手 → 全{ply+1+L}手"))
        if not valid: break
        mx = max(r[2] for r in valid)
        pv = next(r for r in valid if r[2] == mx)
        b.push_usi(pv[0]); ply += 1
        n = mx
        wins = attacker_wins(b, n)
        out(f"--- {ply}手目 {pv[0]} のあとの攻め方の正解手(残り{n}手): {wins}")
        if not wins: break
        b.push_usi(wins[0]); ply += 1
        first_moves = first_moves + [pv[0], wins[0]]
        if n == 1: break


def tree(sfen, first_moves, total, out=print, fmt=None):
    """作意の全分岐を調べる。玉方は最長に粘る応手(同じ最長手数の応手すべて)を辿り、攻め方は正解手すべてを列挙する。
    out(深さ, 文章) の形で出力する。fmt(盤, USI) で指し手を日本語にする。"""
    b0 = shogi.Board(sfen)
    for u in first_moves: b0.push_usi(u)
    f = fmt or (lambda bd, u: u)

    def names(bd, us):
        return " ".join(f(bd, u) for u in us)

    def defender(b, ply, n, depth):
        rep = replies(b, n)
        valid = [r for r in rep if r[1] != '無駄合' and r[2] is not None]
        futile = [r[0] for r in rep if r[1] == '無駄合']
        if not valid:
            out(depth, "（応手なし＝詰み）"); return
        mx = max(r[2] for r in valid)
        longest = [r for r in valid if r[2] == mx]
        short = [r for r in valid if r[2] != mx]
        drops = [r for r in longest if r[1] == '合駒']
        nondrops = [r for r in longest if r[1] != '合駒']
        if short:
            out(depth, "早く詰む応手： " + " ".join(f"{f(b, r[0])}（全{ply+1+r[2]}手）" for r in short))
        if futile:
            out(depth, "無駄合として除外： " + names(b, futile))
        if len(drops) > 1:
            out(depth, f"合駒は何でもよい（{len(drops)}種）： " + names(b, [r[0] for r in drops]))
        todo = nondrops + drops[:1]
        for u, k, L in todo:
            d2 = depth + (1 if len(todo) > 1 else 0)
            tag = "（合駒）" if k == '合駒' else ""
            if len(todo) > 1:
                out(depth, f"**変化：{ply+1}手目 {f(b, u)}**{tag}")
            else:
                out(depth, f"{ply+1}手目 {f(b, u)}{tag}")
            q = shogi.Board(b.sfen()); q.push_usi(u)
            attacker(q, ply + 1, L, d2)

    def attacker(b, ply, n, depth):
        wins = attacker_wins(b, n)
        if not wins:
            out(depth, "（詰みなし）"); return
        if len(wins) > 1:
            out(depth, f"攻め方の正解が{len(wins)}通り（非限定）： " + names(b, wins))
        w = wins[0]
        out(depth, f"{ply+1}手目 {f(b, w)}" + ("　（以下はこの手の場合）" if len(wins) > 1 else ""))
        q = shogi.Board(b.sfen()); q.push_usi(w)
        if n == 1: return
        defender(q, ply + 1, n - 1, depth)

    defender(b0, len(first_moves), total - len(first_moves), 0)


import time as _time


class _Timeout(Exception):
    pass


def verify_markdown(sfen, pv, time_limit=60, max_lines=160, fmt=None):
    """KH の手順 pv の先頭の手を信じて、無駄合を除いた正しい手数と全分岐を調べ、表示用の文章(Markdown)を返す。
    調べられない場合は空文字を返す。"""
    b = shogi.Board(sfen)
    if b.turn != shogi.BLACK or not pv or len(pv) < 3:
        return ""
    deadline = _time.time() + time_limit
    q = shogi.Board(sfen)
    q.push_usi(pv[0])
    N = None
    L = len(pv) if len(pv) % 2 == 1 else len(pv) - 1
    # KH の手数 L は無駄合を含むので、本当の手数は L 以下。L が成り立てば、L-2, L-4 ... と下げて最短を探す
    if T.defenders_all_lose(q, L - 1):
        N = L
        while N > 3:
            if _time.time() > deadline:
                return "## 無駄合を除いた検証\n\n時間内に確認できませんでした。\n"
            if T.defenders_all_lose(q, N - 3):
                N -= 2
            else:
                break
    else:
        for n in range(L + 2, L + 7, 2):
            if T.defenders_all_lose(q, n - 1):
                N = n
                break
    if N is None:
        return ""
    lines = []

    class _Full(Exception):
        pass

    def out(depth, s):
        if _time.time() > deadline:
            raise _Timeout()
        if len(lines) >= max_lines:
            raise _Full()
        lines.append("　" * depth + s)

    note = ""
    try:
        tree(sfen, [pv[0]], N, out=out, fmt=fmt)
    except _Timeout:
        note = "（時間切れのため、ここまでで打ち切りました）"
    except _Full:
        note = "（長いため、ここまでで打ち切りました）"
    first = fmt(b, pv[0]) if fmt else pv[0]
    head = ["## 無駄合を除いた検証（棋慧エンジン）", ""]
    if N == len(pv):
        head.append(f"無駄合を除いた詰み手数は **{N}手** で、KomoringHeightsの報告と同じです。")
    else:
        head.append(f"無駄合を除いた詰み手数は **{N}手** です（KomoringHeightsの手順は{len(pv)}手）。")
    head.append(f"初手 {first} はKomoringHeightsの手を前提にしています（初手の余詰は調べていません）。")
    head.append("")
    body = ["- " + l if l.strip() else l for l in lines]
    return "\n".join(head + body) + ("\n\n" + note if note else "") + "\n"


def _exact_length(q, L, deadline):
    """q: 初手を指した後の局面。L: KHの手数。無駄合を除いた詰み手数を返す(分からなければ None)。"""
    # 短い手数から順に調べる（正しい手数がKHの手順より短いとき、長い探索をしなくて済む）
    for m in range(2, L - 1, 2):
        if _time.time() > deadline:
            return None
        if T.defenders_all_lose(q, m):
            return m + 1
    if T.defenders_all_lose(q, L - 1):
        return L
    for n in range(L + 2, L + 7, 2):
        if T.defenders_all_lose(q, n - 1):
            return n
    return None


def main_line(sfen, first_moves, N):
    """正しい手数 N での手順の一例。玉方は最も長く粘る手(合駒でない手を優先)、攻め方は最初の正解手。"""
    b = shogi.Board(sfen)
    for u in first_moves:
        b.push_usi(u)
    out = list(first_moves)
    n = N - len(first_moves)
    while n > 0:
        rep = replies(b, n)
        valid = [r for r in rep if r[1] != '無駄合' and r[2] is not None]
        if not valid:
            break
        mx = max(r[2] for r in valid)
        pick = sorted([r for r in valid if r[2] == mx], key=lambda r: r[1] == '合駒')[0]
        b.push_usi(pick[0]); out.append(pick[0])
        n = pick[2]
        if n <= 0:
            break
        wins = attacker_wins(b, n)
        if not wins:
            break
        b.push_usi(wins[0]); out.append(wins[0])
        n -= 1
        if n == 0:
            break
    return out


def quick_markdown(sfen, pv, time_limit=20, max_len=13, fmt=None):
    """詰みを探す用の軽い確認。KHの手順に無駄合が混ざっていないかだけを短く報告する。空文字なら何も出さない。"""
    f = fmt or (lambda bd, u: u)
    b = shogi.Board(sfen)
    if b.turn != shogi.BLACK or not pv or len(pv) < 3:
        return ""
    L = len(pv) if len(pv) % 2 == 1 else len(pv) - 1
    if L > max_len:
        return "無駄合チェック：手数が長いため省略しました（「余詰を調べる」で確認できます）。"
    deadline = _time.time() + time_limit
    q = shogi.Board(sfen)
    q.push_usi(pv[0])
    N = _exact_length(q, L, deadline)
    if N is None:
        return "無駄合チェック：時間内に確認できませんでした。"
    # KHの手順の中の無駄合
    futile_moves = []
    bd = shogi.Board(sfen)
    for i, u in enumerate(pv[:L]):
        if i % 2 == 1 and u[1] == '*' and N - i > 0:
            try:
                if is_futile(bd, u, N - i):
                    futile_moves.append(f(bd, u))
            except Exception:
                pass
        bd.push_usi(u)
    if N == L and not futile_moves:
        return f"無駄合チェック：問題ありません（無駄合を除いても{N}手詰です）。"
    lines = ["**⚠ 無駄合チェック：KomoringHeightsの手順に無駄合が含まれています。**", ""]
    if futile_moves:
        lines.append("無駄合： " + " ".join(futile_moves))
    lines.append(f"無駄合を除いた正しい詰み手数は **{N}手** です（KomoringHeightsは{len(pv)}手と報告）。")
    try:
        ml = main_line(sfen, [pv[0]], N)
        bd = shogi.Board(sfen); txt = []
        for u in ml:
            txt.append(f(bd, u)); bd.push_usi(u)
        lines += ["", "無駄合を除いた手順の一例：", "", " ".join(txt) + f"　まで{len(ml)}手"]
    except Exception:
        pass
    lines += ["", "分岐や余詰の詳しい確認は「余詰を調べる」で行えます。"]
    return "\n".join(lines)


# ------------------------------------------------------------------ 棋慧の画面用(手順検証・余詰検証)
_ZEN = "０１２３４５６７８９"
_KAN = "〇一二三四五六七八九"
_NAME = {"P": "歩", "L": "香", "N": "桂", "S": "銀", "G": "金", "B": "角", "R": "飛", "K": "玉",
         "+P": "と", "+L": "成香", "+N": "成桂", "+S": "成銀", "+B": "馬", "+R": "龍"}


def ja_move(bd, u):
    """指し手を日本語の棋譜表記にする（例: ▲２七飛打 / △２六角打 / ▲同飛 / ▲４一角打）。
    直前の手と同じ升への指し手は「同」。同じ駒が複数動ける曖昧な場合だけ (元の升) を付ける。"""
    side = "▲" if bd.turn == shogi.BLACK else "△"
    to = shogi.SQUARE_NAMES.index(u[2:4])
    same = bool(bd.move_stack) and bd.move_stack[-1].to_square == to
    dest = "同" if same else _ZEN[int(u[2])] + _KAN[ord(u[3]) - 96]
    if u[1] == "*":
        return f"{side}{dest}{_NAME[u[0]]}打"
    frm = shogi.SQUARE_NAMES.index(u[0:2])
    pc = bd.piece_at(frm)
    sym = pc.symbol().upper()
    key = ("+" + sym.replace("+", "")) if "+" in pc.symbol() else sym
    name = _NAME.get(key, sym)
    promo = "成" if u.endswith("+") else ""
    amb = ""
    for m in bd.legal_moves:
        if m.from_square is not None and m.from_square != frm and m.to_square == to:
            p2 = bd.piece_at(m.from_square)
            if p2 is not None and p2.piece_type == pc.piece_type:
                amb = f"({u[0]}{ord(u[1]) - 96})"
                break
    return f"{side}{dest}{name}{promo}{amb}"


def line_ja(sfen, pv):
    """手順 pv を日本語の棋譜表記の文にする。"""
    bd = shogi.Board(sfen)
    out = []
    for u in pv:
        try:
            out.append(ja_move(bd, u)); bd.push_usi(u)
        except Exception:
            break
    return " ".join(out)


def _clone(bd):
    nb = shogi.Board(bd.sfen())
    nb.move_stack = list(bd.move_stack)
    return nb


def _jp(fmt, bd, u):
    return ja_move(bd, u)


def check_line(sfen, pv, time_limit=30, fmt=None):
    """「手順検証」: KHの手順を、無駄合を除いた正しい手順に直す。
    返り値: dict(state='ok'|'warn'|'skip'|'timeout'|'error', N, futile=[...], line='...', sec, msg)"""
    t0 = _time.time()
    res = {"state": "skip", "N": None, "futile": [], "line": "", "sec": 0.0, "msg": ""}
    b = shogi.Board(sfen)
    if b.turn != shogi.BLACK or not pv or len(pv) < 3:
        res["msg"] = "この局面（先手番の詰将棋・3手以上）でないため、検証できません。"
        return res
    L = len(pv) if len(pv) % 2 == 1 else len(pv) - 1
    old = T.TIMEOUT
    T.TIMEOUT = max(1.0, time_limit)
    try:
        deadline = _time.time() + time_limit
        q = shogi.Board(sfen); q.push_usi(pv[0])
        N = _exact_length(q, L, deadline)
        if N is None:
            res["state"] = "timeout"; res["msg"] = "時間内に確認できませんでした。"
            return res
        res["N"] = N
        bd = shogi.Board(sfen)
        for i, u in enumerate(pv[:L]):
            if i % 2 == 1 and u[1] == '*' and N - i > 0:
                if is_futile(bd, u, N - i):
                    res["futile"].append(_jp(fmt, bd, u))
            bd.push_usi(u)
        ml = main_line(sfen, [pv[0]], N)
        bd = shogi.Board(sfen); txt = []
        for u in ml:
            txt.append(_jp(fmt, bd, u)); bd.push_usi(u)
        res["line"] = " ".join(txt) + f"　まで{len(ml)}手"
        res["pv_usi"] = list(ml)
        res["kh_eff"] = len(pv) - 2 * len(res["futile"])
        res["state"] = "ok" if (N == L and not res["futile"] and len(pv) == L) else "warn"
        return res
    except ValueError as e:
        res["state"] = "timeout" if "timeout" in str(e) else "error"
        res["msg"] = "時間内に確認できませんでした。" if res["state"] == "timeout" else str(e)
        return res
    finally:
        T.TIMEOUT = old
        res["sec"] = _time.time() - t0


def _gou(text):
    """「△２三香打」→「△２三合」（合駒の種類を問わない表記）"""
    import re
    return re.sub(r"[歩香桂銀金角飛]打$", "合", text)


def detail(sfen, pv, time_limit=120, fmt=None, max_blocks=40):
    """「余詰検証」: 手順（本手順）と、変化・非限定・無駄合・合駒の扱いを、普通の手順の書き方で返す。
    返り値: dict(state, N, blocks=[(見出し, 手順文, [注])...], sec, msg)"""
    t0 = _time.time()
    res = {"state": "skip", "N": None, "blocks": [], "sec": 0.0, "msg": ""}
    b0 = shogi.Board(sfen)
    if b0.turn != shogi.BLACK or not pv or len(pv) < 3:
        res["msg"] = "この局面（先手番の詰将棋・3手以上）でないため、検証できません。"
        return res
    L = len(pv) if len(pv) % 2 == 1 else len(pv) - 1
    old = T.TIMEOUT
    T.TIMEOUT = max(1.0, time_limit)
    deadline = _time.time() + time_limit
    try:
        q = shogi.Board(sfen); q.push_usi(pv[0])
        N = _exact_length(q, L, deadline)
        if N is None:
            res["state"] = "timeout"; res["msg"] = "時間内に確認できませんでした。"
            return res
        res["N"] = N
        res["kh_futile"] = []
        bd0 = shogi.Board(sfen)
        for i, u in enumerate(pv[:L]):
            if i % 2 == 1 and u[1] == '*' and N - i > 0:
                try:
                    if is_futile(bd0, u, N - i):
                        res["kh_futile"].append(_jp(fmt, bd0, u))
                except ValueError:
                    raise
                except Exception:
                    pass
            bd0.push_usi(u)
        res["kh_eff"] = len(pv) - 2 * len(res["kh_futile"])
        blocks = []
        names = lambda bd, us: " ".join(_jp(fmt, bd, u) for u in us)

        vlist = []
        _rc, _wc, _okc = {}, {}, {}

        def rep_c(bd, n):
            k = (bd.sfen(), n)
            if k not in _rc:
                _rc[k] = replies(bd, n)
            return _rc[k]

        def wins_c(bd, n):
            k = (bd.sfen(), n)
            if k not in _wc:
                _wc[k] = attacker_wins(bd, n)
            return _wc[k]

        def hand_empty(bd):
            return sum(bd.pieces_in_hand[shogi.BLACK].values()) == 0

        def pick(rep):
            """玉方の応手のうち、最長の変化になるもの（非限定の合駒は代表1つ）を (usi, 種別, 残り手数) のリストで返す。"""
            valid = [r for r in rep if r[1] != '無駄合' and r[2] is not None]
            if not valid:
                return []
            mx = max(r[2] for r in valid)
            longest = [r for r in valid if r[2] == mx]
            return [r for r in longest if r[1] != '合駒'] + [r for r in longest if r[1] == '合駒'][:1]

        def finish_ok(bd, n, defender_turn):
            """この局面から、攻め方の持駒を使い切って（駒余りなしで）詰ませる手順が、最長の変化の中にあるか。"""
            k = (bd.sfen(), n, defender_turn)
            if k in _okc:
                return _okc[k]
            if _time.time() > deadline:
                raise ValueError("timeout")
            if n <= 0:
                r = hand_empty(bd)
            elif defender_turn:
                ch = pick(rep_c(bd, n))
                if not ch:
                    r = hand_empty(bd)
                else:
                    r = False
                    for c in ch:
                        q = _clone(bd); q.push_usi(c[0])
                        if finish_ok(q, c[2], False):
                            r = True; break
            else:
                ws = wins_c(bd, n)
                if not ws:
                    r = hand_empty(bd)
                else:
                    r = False
                    for w in ws:
                        q = _clone(bd); q.push_usi(w)
                        if finish_ok(q, n - 1, True):
                            r = True; break
            _okc[k] = r
            return r

        def walk(b, n, defender_turn, tokens, notes, path, vidx):
            while n > 0:
                if _time.time() > deadline:
                    raise ValueError("timeout")
                if defender_turn:
                    rep = rep_c(b, n)
                    valid = [r for r in rep if r[1] != '無駄合' and r[2] is not None]
                    futile = [r[0] for r in rep if r[1] == '無駄合']
                    if not valid:
                        break
                    mx = max(r[2] for r in valid)
                    longest = [r for r in valid if r[2] == mx]
                    nondrops = [r for r in longest if r[1] != '合駒']
                    drops = [r for r in longest if r[1] == '合駒']
                    choices = nondrops + drops[:1]
                    if len(choices) > 1:
                        # 同じ長さの受けが複数ある（変同）：攻め方の駒が余らない手順を、本手順（作意）にする
                        def _fin(c):
                            q = _clone(b); q.push_usi(c[0])
                            return 0 if finish_ok(q, c[2], False) else 1
                        choices = sorted(choices, key=_fin)
                    first = choices[0]
                    for alt in choices[1:]:
                        if len(blocks) >= max_blocks:
                            break
                        qb = _clone(b)
                        label = _jp(fmt, qb, alt[0])
                        qb.push_usi(alt[0])
                        prev = next((t for t in reversed(tokens) if t != "（非限定）"), "")
                        toks, nts = [("…" + prev) if prev else "…", label], []
                        sub_path = list(path) + [alt[0]]
                        vitem = {"from": len(path) + 1, "prefix": list(path), "moves": [alt[0]], "parent": vidx,
                                 "comments": {}, "all_comments": {}, "end": "詰み"}
                        vlist.append(vitem)
                        walk(qb, alt[2], False, toks, nts, sub_path, len(vlist) - 1)
                        vitem["moves"] = sub_path[len(path):]
                        blocks.append((f"{prev} のあと {label} の変化", " ".join(toks).replace("（非限定） ", "（非限定）") + "　まで", nts))
                    tok = _jp(fmt, b, first[0])
                    if first[1] == '合駒' and len(drops) > 1:
                        tok = _gou(tok)             # 打てる合駒なら何でもよい
                    tokens.append(tok); b.push_usi(first[0]); path.append(first[0])
                    n = first[2]; defender_turn = False
                else:
                    wins = wins_c(b, n)
                    if not wins:
                        break
                    if len(wins) > 1:
                        def _fin2(w):
                            q = _clone(b); q.push_usi(w)
                            return 0 if finish_ok(q, n - 1, True) else 1
                        wins = sorted(wins, key=_fin2)
                    tokens.append(_jp(fmt, b, wins[0]))
                    if len(wins) > 1:
                        tokens.append("（非限定）")
                    b.push_usi(wins[0]); path.append(wins[0])
                    n -= 1; defender_turn = True

        main_path = [pv[0]]
        b = shogi.Board(sfen); b.push_usi(pv[0])
        toks, nts = [_jp(fmt, shogi.Board(sfen), pv[0])], []
        try:
            walk(b, N - 1, True, toks, nts, main_path, -1)
            res["state"] = "ok"
        except ValueError as e:
            if "timeout" not in str(e):
                raise
            res["state"] = "timeout"; res["msg"] = "時間切れのため、ここまでの結果です。"
        fix = lambda ts: " ".join(ts).replace("（非限定） ", "（非限定）")
        res["blocks"] = [("手順", fix(toks) + f"　まで{N}手", nts)] + blocks
        # 棋慧の「変化（分岐棋譜）」として盤に取り込める形
        for v in vlist:
            try:
                bb = shogi.Board(sfen)
                for u in v["prefix"]:
                    bb.push_usi(u)
                first = ja_move(bb, v["moves"][0])
            except Exception:
                first = v["moves"][0]
            v["label"] = f"変化 {v['from']}手目 {first}…（{len(v['prefix']) + len(v['moves'])}手）"
        res["main_usi"] = list(main_path)
        res["game"] = {"sfen": sfen, "moves": list(main_path), "comments": {}, "variations": vlist}
        return res
    except ValueError as e:
        res["state"] = "timeout" if "timeout" in str(e) else "error"
        res["msg"] = "時間内に確認できませんでした。" if res["state"] == "timeout" else str(e)
        return res
    finally:
        T.TIMEOUT = old
        res["sec"] = _time.time() - t0


def quick_check(sfen, pv, time_limit=20, fmt=None):
    """「手順検証」(軽量版): KHの手順に出てくる合駒だけを、1つずつ「無駄合か」確かめる。
    他の変化や余詰は調べない（それは詳細検討の仕事）。
    返り値: dict(state='ok'|'warn'|'skip'|'timeout'|'error', futile=[...], sec, msg)"""
    t0 = _time.time()
    res = {"state": "skip", "N": None, "futile": [], "line": "", "sec": 0.0, "msg": ""}
    b = shogi.Board(sfen)
    if b.turn != shogi.BLACK or not pv or len(pv) < 3:
        res["msg"] = "この局面（先手番の詰将棋・3手以上）でないため、検証できません。"
        return res
    L = len(pv) if len(pv) % 2 == 1 else len(pv) - 1
    old = T.TIMEOUT
    T.TIMEOUT = max(1.0, time_limit)
    try:
        # 局面を順に作っておく
        boards, txt = [], []
        bd = shogi.Board(sfen)
        for i, u in enumerate(pv[:L]):
            boards.append(_clone(bd))
            txt.append(_jp(fmt, bd, u)); bd.push_usi(u)
        # 後ろの合駒から調べる（後ろに無駄合があれば、その分だけ残り手数が短くなるため、前の合駒の判定が軽くなる）
        k = 0
        found = []
        pending = []
        deadline = t0 + time_limit
        idx = [i for i in range(L) if i % 2 == 1 and pv[i][1] == '*']
        left_n = len(idx)
        for i in range(L - 1, -1, -1):
            u = pv[i]
            if i % 2 == 1 and u[1] == '*' and L - i - 2 * k > 0:
                # 無駄合なら短時間で分かるが、「無駄合でない」と確かめるのは重い。
                # 1つの合駒で時間を使い切らないよう、残り時間を残りの合駒数で割って使う。
                T.TIMEOUT = max(1.0, (deadline - _time.time()) / max(1, left_n))
                left_n -= 1
                try:
                    if is_futile(boards[i], u, L - i - 2 * k):
                        found.append(txt[i]); k += 1
                except ValueError as e:
                    if "timeout" not in str(e):
                        raise
                    pending.append(txt[i])
        res["futile"] = list(reversed(found))
        res["pending"] = list(reversed(pending))
        res["line"] = " ".join(txt) + f"　まで{L}手"
        res["pv_usi"] = list(pv[:L])
        res["state"] = "warn" if res["futile"] else ("pending" if res["pending"] else "ok")
        return res
    except ValueError as e:
        res["state"] = "timeout" if "timeout" in str(e) else "error"
        res["msg"] = "時間内に確認できませんでした。" if res["state"] == "timeout" else str(e)
        return res
    finally:
        T.TIMEOUT = old
        res["sec"] = _time.time() - t0

def solve_first(sfen, time_limit=150, max_n=31):
    """棋慧だけで詰みを探す（Komoring不要）。短い手数から順に、詰む最短の手数 N を求める。
    返り値: dict(state='ok'|'nomate'|'timeout'|'skip'|'error', N, firsts(初手の候補), pv(手順の一例), upto(ここまでは詰まないと確認した手数), msg, sec)"""
    t0 = _time.time()
    res = {"state": "skip", "N": None, "firsts": [], "pv": [], "upto": 0, "msg": "", "sec": 0.0}
    try:
        b = shogi.Board(sfen)
    except Exception as e:
        res["state"] = "error"; res["msg"] = str(e); return res
    if b.turn != shogi.BLACK:
        res["msg"] = "先手（攻め方）の手番の詰将棋の形でないため、解けません。「手番切替」で攻め方の手番にしてください。"
        return res
    old = T.TIMEOUT
    deadline = t0 + time_limit
    try:
        N = None
        n = 1
        while n <= max_n:
            left = deadline - _time.time()
            if left <= 0:
                res["state"] = "timeout"; res["msg"] = f"時間内に解けませんでした（{res['upto']}手までは詰まないことを確認しました）。"
                return res
            T.TIMEOUT = max(1.0, left)
            try:
                if T.can_mate(b, n):
                    N = n; break
            except ValueError as e:
                if "timeout" not in str(e):
                    raise
                res["state"] = "timeout"; res["msg"] = f"時間内に解けませんでした（{res['upto']}手までは詰まないことを確認しました）。"
                return res
            res["upto"] = n
            n += 2
        if N is None:
            res["state"] = "nomate"; res["msg"] = f"{max_n}手以内には詰みが見つかりませんでした（不詰、またはもっと長い手数）。"
            return res
        T.TIMEOUT = max(1.0, deadline - _time.time())
        wins = attacker_wins(b, N)
        if not wins:
            res["state"] = "error"; res["msg"] = "初手を特定できませんでした。"; return res
        res["N"], res["firsts"] = N, wins
        res["pv"] = main_line(sfen, [wins[0]], N)
        res["state"] = "ok"
        return res
    except ValueError as e:
        res["state"] = "timeout" if "timeout" in str(e) else "error"
        res["msg"] = (f"時間内に解けませんでした（{res['upto']}手までは詰まないことを確認しました）。"
                      if res["state"] == "timeout" else str(e))
        return res
    finally:
        T.TIMEOUT = old
        res["sec"] = _time.time() - t0

