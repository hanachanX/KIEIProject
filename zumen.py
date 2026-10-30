# -*- coding: utf-8 -*-
"""局面図（Web・棋書・論文などの盤面の画像）から、局面（SFEN）を読み取る。

 ・盤の9x9の線を見つけて、1マスずつ駒を見分ける（zumen_board.npz）
 ・盤の左右にある「持ち駒」の文字を読む（zumen_glyph.npz）
 ・駒の字は、いろいろなフォントで自動生成した画像から学習してあるので、特定のサイトの図に限らない
 ・読み取りは100%ではないので、読んだあとに盤で確認・修正する前提
 ・将棋ソフトの画面（色付き・動く画面）は対象外
"""
import os

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))

TYPES = ["K", "R", "B", "G", "S", "N", "L", "P", "+R", "+B", "+S", "+N", "+L", "+P"]
CLASSES = ["empty"] + [s + t for s in ("s", "g") for t in TYPES]
KANJI_NUM = {"二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
FEAT_N = 24
_models = {}


class _MLP:
    """学習済みの小さなニューラルネット（numpy だけで計算する。scikit-learn のバージョンに左右されない）"""

    def __init__(self, path):
        d = np.load(path, allow_pickle=False)
        self.classes_ = d["classes"]
        n = int(d["n"])
        self.w = [d[f"w{i}"] for i in range(n)]
        self.b = [d[f"b{i}"] for i in range(n)]
        self.names = [str(x) for x in d["names"]] if "names" in d.files else None

    def predict_proba(self, X):
        a = np.asarray(X, np.float32)
        for i, (w, b) in enumerate(zip(self.w, self.b)):
            a = a @ w + b
            if i < len(self.w) - 1:
                a = np.maximum(a, 0)
        a = a - a.max(axis=1, keepdims=True)
        e = np.exp(a)
        return e / e.sum(axis=1, keepdims=True)


def _model(name):
    if name not in _models:
        _models[name] = _MLP(os.path.join(HERE, name))
    return _models[name]


# ------------------------------------------------------------------ 特徴
def cell_feature(cell):
    if cell.ndim == 3:
        cell = cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY)
    h, w = cell.shape
    m = max(1, int(round(min(h, w) * 0.08)))
    c = cell[m:h - m, m:w - m].astype(np.float32)
    bg = float(np.median(c))
    if bg < 110:
        c = 255 - c
        bg = 255 - bg
    ink = np.clip(bg - c, 0, None)
    mx = ink.max()
    ink = np.zeros_like(ink) if mx < 25 else ink / mx
    ink = cv2.resize(ink, (FEAT_N, FEAT_N), interpolation=cv2.INTER_AREA)
    return ink.reshape(-1)


def glyph_feature_from_crop(gray):
    h, w = gray.shape
    side = max(h, w)
    pad = int(side * 0.16) + 1
    bg = float(np.median(np.concatenate([gray[0, :], gray[-1, :], gray[:, 0], gray[:, -1]])))
    canvas = np.full((side + 2 * pad, side + 2 * pad), bg, np.float32)
    y0 = pad + (side - h) // 2
    x0 = pad + (side - w) // 2
    canvas[y0:y0 + h, x0:x0 + w] = gray
    return cell_feature(canvas.astype(np.uint8))


def _peaks(profile, min_gap=3):
    """プロファイル（線の強さ）から、線の位置を取り出す。"""
    p = np.asarray(profile, dtype=float)
    if p.max() <= 0:
        return []
    thr = p.max() * 0.35
    idx = np.where(p >= thr)[0]
    if len(idx) == 0:
        return []
    groups, cur = [], [idx[0]]
    for i in idx[1:]:
        if i - cur[-1] <= min_gap:
            cur.append(i)
        else:
            groups.append(cur)
            cur = [i]
    groups.append(cur)
    out = []
    for g in groups:
        w = p[g]
        out.append(float((np.array(g) * w).sum() / w.sum()))
    return out


def _best_ten(pos, min_cell=14):
    """線の位置の並びから、等間隔の10本（＝9マス）を探す。"""
    pos = sorted(pos)
    best, best_score = None, 1e9
    n = len(pos)
    for i in range(n):
        for j in range(i + 1, n):
            # pos[i] を1本目、pos[j] を k 本目とみなして間隔を決める
            for k in range(1, 10):
                step = (pos[j] - pos[i]) / k
                if step < min_cell:
                    continue
                if i + 0 >= n:
                    continue
                grid = [pos[i] + step * m for m in range(10)]
                # 各格子点に近い検出線があるか
                err, hit = 0.0, 0
                for g in grid:
                    d = min(abs(g - q) for q in pos)
                    if d < step * 0.12:
                        hit += 1
                        err += d
                if hit >= 9:
                    score = err / hit - hit * 0.5 - step * 0.01   # 本数が多く、大きい盤を優先
                    if score < best_score:
                        best_score, best = score, grid
    return best


def find_grid(bgr):
    """戻り値: (xs, ys)  それぞれ長さ10の線の位置。見つからなければ None"""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
    h, w = gray.shape
    # 背景が暗い・明るいに関わらず、線（インク）を白にする
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    if bw.mean() > 127:
        bw = 255 - bw
    kx = max(15, w // 10)
    ky = max(15, h // 10)
    horiz = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (kx, 1)))
    vert = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, ky)))
    ys = _peaks(horiz.sum(axis=1))
    xs = _peaks(vert.sum(axis=0))
    gy = _best_ten(ys)
    gx = _best_ten(xs)
    if gx is None or gy is None:
        return None
    return gx, gy

def _order_quad(pts):
    pts = np.array(pts, np.float32).reshape(-1, 2)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).reshape(-1)
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], np.float32)   # 左上・右上・右下・左下


def rectify(bgr, cell=48, margin=3):
    """写真などで盤が傾いている・ゆがんでいるとき、盤の外枠を探して、まっすぐな正方形に直す。
    戻り値: (直した画像, xs, ys)。盤が見つからなければ None"""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    blk = max(15, (min(h, w) // 12) | 1)
    bw = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, blk, 8)
    hz = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(9, w // 22), 1)))
    vt = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(9, h // 22))))
    m = cv2.dilate(cv2.bitwise_or(hz, vt), np.ones((5, 5), np.uint8))
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best, best_area = None, 0
    for c in cnts:
        x, y, cw, ch = cv2.boundingRect(c)
        if cw < w * 0.25 or ch < h * 0.25:
            continue
        if not 0.6 < cw / ch < 1.6:
            continue
        a = cv2.contourArea(cv2.convexHull(c))
        if a > best_area:
            best, best_area = c, a
    if best is None:
        return None
    hull = cv2.convexHull(best)
    peri = cv2.arcLength(hull, True)
    ap = cv2.approxPolyDP(hull, 0.02 * peri, True)
    quad = ap.reshape(-1, 2) if len(ap) == 4 else cv2.boxPoints(cv2.minAreaRect(hull))
    src = _order_quad(quad)
    # 膨張させた分だけ、内側に少し縮める
    ctr = src.mean(axis=0)
    src = ctr + (src - ctr) * 0.992
    size = (9 + 2 * margin) * cell
    dst = np.array([[margin * cell, margin * cell], [(margin + 9) * cell, margin * cell],
                    [(margin + 9) * cell, (margin + 9) * cell], [margin * cell, (margin + 9) * cell]], np.float32)
    Hm = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(bgr, Hm, (size, size), flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255))
    xs = [margin * cell + i * cell for i in range(10)]
    ys = list(xs)
    g = find_grid(warped)          # 線の位置を微調整できればそれを使う
    if g is not None and abs(g[0][0] - xs[0]) < cell * 0.5 and abs(g[1][0] - ys[0]) < cell * 0.5:
        xs, ys = g
    return warped, xs, ys



# ------------------------------------------------------------------ 持ち駒
def _components(gray, box, cell):
    x0, y0, x1, y1 = [int(v) for v in box]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(gray.shape[1], x1), min(gray.shape[0], y1)
    if x1 - x0 < 5 or y1 - y0 < 5:
        return []
    sub = gray[y0:y1, x0:x1]
    blk = max(15, (int(cell * 0.8)) | 1)
    lo, hi = np.percentile(sub, 2), np.percentile(sub, 98)
    if hi - lo > 150:                       # くっきりした図（画面・きれいなスキャン）は普通の二値化
        _, bw = cv2.threshold(sub, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
        if bw.mean() > 127:
            bw = 255 - bw
    else:                                   # 写真など、明るさにむらがあるものは周りとの差で見る
        bw = cv2.adaptiveThreshold(sub, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, blk, 8)
        bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))      # 点状のノイズを消す
    k = max(3, int(cell * 0.14))
    dil = cv2.dilate(bw, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    n, lab, st, _ = cv2.connectedComponentsWithStats(dil)
    out = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        # 元の線画でのはっきりした範囲に絞る
        m = (lab[y:y + h, x:x + w] == i) & (bw[y:y + h, x:x + w] > 0)
        if m.sum() < max(6, 0.01 * cell * cell):
            continue
        ys, xs = np.where(m)
        bx, by, bx2, by2 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
        if (bx2 - bx) > cell * 1.6 or (by2 - by) > cell * 1.6:
            continue
        bw_, bh_ = bx2 - bx, by2 - by
        sub_m = m[by:by2, bx:bx2]
        if bh_ < 0.6 * cell and bw_ > 1.15 * bh_:
            cols = sub_m.any(axis=0)
            pieces, start = [], None
            for ci, v in enumerate(list(cols) + [False]):
                if v and start is None:
                    start = ci
                if (not v) and start is not None:
                    pieces.append((start, ci))
                    start = None
            if len(pieces) >= 2:
                for (a, b) in pieces:
                    out.append((x0 + x + bx + a, y0 + y + by, b - a, bh_))
                continue
        if bh_ > 1.6 * bw_ and bh_ > 0.9 * cell:
            # たて書きで文字がくっついたものを、いちばん広い隙間で上下に分ける
            rows = sub_m.any(axis=1)
            best, gaps, st_ = None, [], None
            for ri, v in enumerate(list(rows) + [True]):
                if (not v) and st_ is None:
                    st_ = ri
                if v and st_ is not None:
                    gaps.append((st_, ri))
                    st_ = None
            cand = [(b - a, a, b) for a, b in gaps if a >= 0.3 * cell and bh_ - b >= 0.3 * cell]
            if cand:
                _, a, b = max(cand)
                for (r0, r1) in ((0, a), (b, bh_)):
                    part = sub_m[r0:r1]
                    if part.any():
                        yy, xx = np.where(part)
                        out.append((x0 + x + bx + xx.min(), y0 + y + by + r0 + yy.min(), xx.max() + 1 - xx.min(), yy.max() + 1 - yy.min()))
                continue
        out.append((x0 + x + bx, y0 + y + by, bw_, bh_))
    return out


def _num_value(chars):
    """数字の文字の並び → 数（アラビア数字 '18'、漢数字 '十八'）"""
    if not chars:
        return 1
    if all(c.isdigit() for c in chars):
        return int("".join(chars))
    if "十" in chars:
        i = chars.index("十")
        tens = KANJI_NUM.get(chars[i - 1], 1) if i > 0 else 1
        if i > 0 and chars[i - 1] == "十":
            tens = 1
        ones = KANJI_NUM.get(chars[i + 1], 0) if i + 1 < len(chars) else 0
        return tens * 10 + ones
    return KANJI_NUM.get(chars[0], 1)


def read_hands(bgr, xs, ys):
    """戻り値: {'s': {'R': 2, ...}, 'g': {...}}, デバッグ用の文字の一覧"""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    H, W = gray.shape
    cell = (xs[-1] - xs[0]) / 9.0
    top, bot = ys[0] - 1.4 * cell, ys[-1] + 1.4 * cell
    regions = [(0, top, xs[0] - 0.15 * cell, bot), (xs[-1] + 0.8 * cell, top, W, bot)]
    clf, classes = glyph_model()
    hands = {"s": {}, "g": {}}
    debug = []
    for ri, box in enumerate(regions):
        comps = _components(gray, box, cell)
        toks = []
        for (x, y, w, h) in comps:
            crop = gray[y:y + h, x:x + w]
            p = clf.predict_proba(glyph_feature_from_crop(crop).reshape(1, -1))[0]
            k = int(p.argmax())
            cls = classes[int(clf.classes_[k])]
            conf = float(p[k])
            if conf < 0.5:
                cls = "other"
            toks.append({"cls": cls, "x": x + w / 2, "y": y + h / 2, "conf": conf})
        debug += [(ri, t["cls"], round(t["conf"], 2)) for t in toks]
        # この領域の向き（字が正立か逆さか）を、駒の字の多い方で決める
        pieces = [t for t in toks if t["cls"] != "other" and "#" not in t["cls"]]
        if not pieces:
            continue
        side = "s" if sum(1 for t in pieces if t["cls"][0] == "s") >= len(pieces) / 2 else "g"
        seq = [t for t in toks if t["cls"] != "other"]
        # 読む順（正立: 上から下、逆さ: 下から上）。同じ高さの数字は、正立なら左から・逆さなら右から
        tol = 0.3 * cell
        seq.sort(key=lambda t: t["y"], reverse=(side == "g"))
        lines, cur_line = [], []
        for t in seq:
            if cur_line and abs(t["y"] - cur_line[-1]["y"]) > tol:
                lines.append(cur_line)
                cur_line = []
            cur_line.append(t)
        if cur_line:
            lines.append(cur_line)
        cur, nums = None, []

        def flush():
            if cur is not None:
                hands[side][cur] = hands[side].get(cur, 0) + _num_value(nums)
        for ln in lines:
            ln.sort(key=lambda t: t["x"], reverse=(side == "g"))
            for t in ln:
                body = t["cls"][1:]
                if body.startswith("#"):
                    d = body[1:]
                    if t["cls"][0] != side:      # 向きが逆の数字は、6と9だけ読み替える
                        d = {"6": "9", "9": "6"}.get(d, d)
                    nums.append(d)
                else:
                    flush()
                    cur, nums = body, []
        flush()
    return hands, debug


def glyph_model():
    m = _model("zumen_glyph.npz")
    return m, m.names


# ------------------------------------------------------------------ 盤
def _remove_grid_lines(gray, cell):
    """盤の升目の線（長い横線・縦線）を、背景色で塗りつぶす。写真など線が波打つ画像で、線を駒と間違えないため。"""
    blk = max(15, (int(cell * 0.9)) | 1)
    bw = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, blk, 8)
    L = max(9, int(cell * 0.75))
    hz = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (L, 1)))
    vt = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, L)))
    mask = cv2.dilate(cv2.bitwise_or(hz, vt), np.ones((3, 3), np.uint8))
    bg = cv2.medianBlur(gray, max(5, (int(cell * 0.6)) | 1))
    out = gray.copy()
    out[mask > 0] = bg[mask > 0]
    return out


def read_board(bgr, xs, ys):
    """9x9のクラス名（上が一段・左が9筋）と信頼度を返す"""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    cell = (xs[-1] - xs[0]) / 9.0
    gray = _remove_grid_lines(gray, cell)
    feats = []
    for r in range(9):
        for c in range(9):
            x0, x1 = int(round(xs[c])), int(round(xs[c + 1]))
            y0, y1 = int(round(ys[r])), int(round(ys[r + 1]))
            feats.append(cell_feature(gray[y0:y1, x0:x1]))
    clf = _model("zumen_board.npz")
    P = clf.predict_proba(np.array(feats, np.float32))
    idx = P.argmax(axis=1)
    cls = np.array(clf.classes_)[idx]
    board = [[CLASSES[int(cls[r * 9 + c])] for c in range(9)] for r in range(9)]
    return board, P.max(axis=1).reshape(9, 9)


def _sfen_board(board):
    rows = []
    for row in board:
        s, run = "", 0
        for x in row:
            if x == "empty":
                run += 1
                continue
            if run:
                s += str(run)
                run = 0
            t = x[1:]
            ch = t.replace("+", "")
            ch = ch.upper() if x[0] == "s" else ch.lower()
            s += ("+" if t.startswith("+") else "") + ch
        if run:
            s += str(run)
        rows.append(s)
    return "/".join(rows)


def _sfen_hands(hands):
    out = ""
    for side in ("s", "g"):
        for t in ("R", "B", "G", "S", "N", "L", "P"):
            n = hands[side].get(t, 0)
            if n:
                out += (str(n) if n > 1 else "") + (t if side == "s" else t.lower())
    return out or "-"


def remaining_for_gote(board, hands):
    """詰将棋の慣習：盤上と先手の持ち駒に無い駒は、すべて後手（玉方）の持ち駒"""
    total = {"R": 2, "B": 2, "G": 4, "S": 4, "N": 4, "L": 4, "P": 18}
    used = {k: 0 for k in total}
    for row in board:
        for x in row:
            if x != "empty" and x[1:].lstrip("+") in used:
                used[x[1:].lstrip("+")] += 1
    for t, n in hands["s"].items():
        used[t] += n
    return {t: max(0, total[t] - used[t]) for t in total}


def read_diagram(bgr, gote_rest=None):
    """局面図の画像から局面を読む。

    戻り値: dict(sfen, board, hands, notes, ok)
      notes: 利用者への確認事項（読み取りに自信がない・数が合わない等）
    読めなければ ValueError
    """
    g = find_grid(bgr)
    if g is None:
        r = rectify(bgr)       # 写真など：盤が傾いている・ゆがんでいる場合は、まっすぐに直してから読む
        if r is None:
            raise ValueError("盤の9×9の升目の線が見つかりませんでした。盤全体が写っていて、線がはっきり見える画像を使ってください。")
        bgr, xs, ys = r
    else:
        xs, ys = g
    board, conf = read_board(bgr, xs, ys)
    hands, _dbg = read_hands(bgr, xs, ys)
    notes = []
    n_ks = sum(1 for row in board for x in row if x == "sK")
    n_kg = sum(1 for row in board for x in row if x == "gK")
    if gote_rest is None:      # 先手の玉が無く、後手の持ち駒の記載も無ければ、詰将棋の図とみなす
        gote_rest = (n_ks == 0 and n_kg == 1 and not hands["g"])
        if gote_rest:
            notes.append("詰将棋の図とみなして、後手の持ち駒を「残り全部」にしました（違う場合は編集モードで直せます）")
    if gote_rest:
        hands["g"] = remaining_for_gote(board, hands)
    low = [(r, c) for r in range(9) for c in range(9) if conf[r][c] < 0.8]
    if low:
        names = "、".join(f"{9 - c}{'一二三四五六七八九'[r]}" for r, c in low[:6])
        notes.append(f"次のマスは読み取りに自信がありません：{names}")
    kings = {"s": sum(1 for row in board for x in row if x == "sK"), "g": sum(1 for row in board for x in row if x == "gK")}
    if kings["g"] != 1:
        notes.append(f"後手の玉が{kings['g']}枚あります（詰将棋なら1枚のはずです）")
    if kings["s"] > 1:
        notes.append("先手の玉が2枚以上あります")
    # 枚数チェック
    total = {"R": 2, "B": 2, "G": 4, "S": 4, "N": 4, "L": 4, "P": 18}
    cnt = {k: 0 for k in total}
    for row in board:
        for x in row:
            t = x[1:].lstrip("+") if x != "empty" else None
            if t in cnt:
                cnt[t] += 1
    for side in ("s", "g"):
        for t, n in hands[side].items():
            cnt[t] += n
    over = [f"{'飛角金銀桂香歩'['RBGSNLP'.index(t)]}が{cnt[t]}枚" for t in total if cnt[t] > total[t]]
    if over:
        notes.append("駒の数が多すぎます（" + "、".join(over) + "）。読み間違いがあるかもしれません")
    sfen = f"{_sfen_board(board)} b {_sfen_hands(hands)} 1"
    return {"sfen": sfen, "board": board, "hands": hands, "notes": notes}
