"""KomoringHeightsの手順に混ざった無駄合を、Komoringへの問い合わせで直す（試験版）。

考え方
  KomoringHeightsは、無駄合も普通の応手として数えて「最長の粘り」を手順にします。
  そのため、手順に無駄合が入ると、本当の最長の抵抗とは別の筋を、正解として出してしまいます。
  そこで、手順を後ろから順にたどり、玉方の手の場面ごとに、
    1. 無駄合を除いた応手を、全部数え上げる
    2. Komoringが選んだ手以外の応手も、そのあとの局面をKomoringに渡して、手数を聞く
    3. 手数が長い応手があれば、その筋に取り替える（その筋にも無駄合があれば、同じことを繰り返す）
  として、無駄合を数えない本当の最長の抵抗を探します。

  Komoringの答えは「無駄合を数えた手数」なので、本当の手数以上です。
  この性質を使って、「Komoringの手数が今の最長以下の応手」は、聞くだけで捨てられます。

  最後に、棋慧のエンジンで検査します（短く詰む筋がないか、駒余りがないか）。
  余詰・変同などの完全な検査は、別の「手順検証」「詳細検討」の仕事です。
"""
import time

import shogi

import tsume_native as N


def _key(sfen):
    return sfen.rsplit(" ", 1)[0]


def is_futile(q, usi, budget):
    """q: 王手を受ける局面（玉方番）。usi が合駒の打ち方で、それが無駄合か。budget: この場面の残り手数（玉方の手を含む）。"""
    if usi[1] != "*":
        return False
    ksq = q.king_squares[q.turn]
    att = list(q.attackers(1 - q.turn, ksq))
    if len(att) != 1:
        return False
    return N._run("futile", text=q.sfen() + "\n" + usi, n=att[0], budget=budget) == "1"


class Asker:
    """Komoringに「この局面（攻方番）は詰むか。詰むなら手順は」と聞く。同じ局面は聞き直さない。
    fn(sfen) -> (状態, 手順)。状態は mate / nomate / timeout / error。"""

    def __init__(self, fn):
        self.fn = fn
        self.memo = {}
        self.count = 0
        self.sec = 0.0
        self.by_state = {}

    def __call__(self, sfen):
        k = _key(sfen)
        if k in self.memo:
            return self.memo[k]
        t = time.time()
        state, pv = self.fn(sfen)
        dt = time.time() - t
        self.count += 1
        self.sec += dt
        c = self.by_state.setdefault(state, [0, 0.0])
        c[0] += 1
        c[1] += dt
        self.memo[k] = (state, list(pv or []))
        return self.memo[k]


def _seed(self, sfen, result, sec=0.0):
    """最初の局面（問題そのもの）の答えを、先に入れておく（長い制限時間で聞いた結果を使うため）。"""
    self.count += 1
    self.sec += sec
    c = self.by_state.setdefault(result[0], [0, 0.0])
    c[0] += 1
    c[1] += sec
    self.memo[_key(sfen)] = (result[0], list(result[1] or []))


Asker.seed = _seed


def komoring_fn(exe, ms=3000, hash_mb=256):
    """本物のKomoringHeightsに聞く関数を作る（棋慧の core.UsiEngine を使う）。戻り値の .close() で終了。"""
    import core
    holder = {"eng": None}

    def start():
        eng = core.UsiEngine(exe, {"USI_Hash": hash_mb})
        eng.start()
        holder["eng"] = eng

    def ask(sfen, ms_override=None):
        use_ms = ms_override or ms
        tries = [sfen]
        try:
            alt = core.mate_king_candidates(sfen, 1)[0][0]
            if alt != sfen:
                tries.append(alt)
        except Exception:
            pass
        last = ("error", [])
        for s in tries:
            for attempt in (0, 1):
                try:
                    eng = holder["eng"]
                    if eng is None or eng.proc is None or eng.proc.poll() is not None:
                        start()
                    state, pv, _n = holder["eng"].mate(s, use_ms)
                    if state in ("mate", "nomate", "timeout"):
                        return state, pv or []
                    last = (state, pv or [])
                    break
                except (OSError, RuntimeError, TimeoutError):
                    holder["eng"] = None
        return last

    def close():
        eng = holder["eng"]
        if eng is not None:
            try:
                eng.stop()
                eng.close()
            except Exception:
                pass

    ask.close = close
    return ask


class Repair:
    def __init__(self, ask, log=None, max_asks=800, time_limit=600.0, max_depth=10,
                 exact_max=0, exact_sec=90.0, judge_sec=15.0):
        self.ask = ask if isinstance(ask, Asker) else Asker(ask)
        self.log = log or (lambda s: None)
        self.max_asks = max_asks
        self.deadline = time.time() + time_limit
        self.max_depth = max_depth
        self.exact_max = exact_max          # 切り詰めた手順がこの手数以下なら、棋慧のエンジンで全変化を確かめる
        self.exact_sec = exact_sec          # その確認の制限時間(秒)
        self.judge_sec = judge_sec          # 無駄合かどうか等の、1回の判定の制限時間(秒)
        self.memo = {}
        self.xmemo = {}
        self.incomplete = []         # 確かめきれなかった場面の説明
        self.notes = []              # 手順を取り替えた場面の記録

    def _ask(self, sfen):
        """Komoringに聞く。ただし、攻方が王手されている局面（玉方の逆王手の合駒など）は、Komoringが
        誤って「不詰」と答えるため、聞かずに棋慧のエンジンで解く（解けなければ timeout＝分からない）。"""
        try:
            in_check = shogi.Board(sfen).is_check()
        except Exception:
            in_check = False
        if not in_check:
            return self.ask(sfen)
        key = _key(sfen)
        if key in self.xmemo:
            return self.xmemo[key]
        res = ("timeout", [])
        try:
            b = shogi.Board(sfen)
            old = N.TIMEOUT
            N.TIMEOUT = max(1.0, self.judge_sec)
            try:
                for n in range(1, 16, 2):
                    if time.time() > self.deadline:
                        break
                    if N.can_mate(b, n):
                        ln = self._dll_line(b, n)
                        if ln:
                            res = ("mate", ln)
                            self.notes.append("攻方が王手されている局面は、Komoringに聞かず、棋慧のエンジンで解きました")
                        break
            finally:
                N.TIMEOUT = old
        except ValueError:
            pass
        self.xmemo[key] = res
        return res

    @staticmethod
    def _dll_line(b, n):
        """棋慧のエンジンで n 手で詰む局面から、詰みの手順を1本作る（玉方は一番長く逃げる手を選ぶ）。"""
        cur, rem, out = shogi.Board(b.sfen()), n, []
        while rem > 0:
            firsts = N.solve(cur, rem)
            if not firsts:
                return None
            m = firsts[0]
            out.append(m.usi())
            cur.push(m)
            if rem == 1:
                break
            evs = N.gen_evasions(cur)
            if not evs:
                break
            best = None
            for e in evs:
                q = shogi.Board(cur.sfen())
                q.push(e)
                k = next((x for x in range(1, rem - 1, 2) if N.can_mate(q, x)), None)
                if k is None:
                    return None
                if best is None or k > best[0]:
                    best = (k, e, q)
            out.append(best[1].usi())
            cur, rem = best[2], best[0]
        return out

    def _over(self):
        return self.ask.count >= self.max_asks or time.time() > self.deadline

    def run(self, sfen):
        t0 = time.time()
        st, pv = self._ask(sfen)
        res = {"state": st, "komoring_pv": list(pv), "komoring_n": len(pv)}
        if st != "mate" or not pv:
            res.update(n=None, line=[], asks=self.ask.count, sec=time.time() - t0)
            return res
        r, exact = None, False
        old_timeout = N.TIMEOUT
        try:
            N.TIMEOUT = max(1.0, self.judge_sec)
            cand = self._cut_pv(sfen, pv) if self.exact_max > 0 else None   # 試験中の近道。既定では使わない
            if cand is not None:
                if cand[0] <= self.exact_max:
                    ok = self._exact_verify(sfen, cand[0])
                    if ok is True:
                        r, exact = cand, True
                        self.notes.append(f"手順の無駄合を取り除くと{cand[0]}手になり、棋慧のエンジンが全変化を確かめました")
                    elif ok is False:
                        self.notes.append(f"{cand[0]}手に切り詰めた手順は、全変化の確認で成り立ちませんでした（問い合わせで探し直します）")
                    else:
                        self.notes.append("全変化の確認は時間内に終わりませんでした（問い合わせで探し直します）")
                else:
                    self.notes.append(f"切り詰めた手順は{cand[0]}手で、棋慧のエンジンで全変化を確かめるには長すぎます（問い合わせで探し直します）")
            if r is None:
                r = self._solve(sfen, 0)
        finally:
            N.TIMEOUT = old_timeout
        res["exact"] = exact
        if r is None:
            res.update(state="broken", n=None, line=[])
        else:
            res.update(n=r[0], line=r[1])
        res["changed"] = bool(r) and r[1] != list(pv)
        res["asks"] = self.ask.count
        res["sec"] = time.time() - t0
        res["incomplete"] = list(self.incomplete)
        res["notes"] = list(self.notes)
        return res

    def _cut_pv(self, sfen, pv):
        """Komoringの手順の無駄合だけを、後ろから調べて取り除き、手順を切り詰める（Komoringへは聞かない）。
        無駄合を除くと玉方に応手が残らない場面があれば、そこで詰みなので、その先は要らない。
        手順の玉方の手が無駄合で、かつほかの応手も残るときは、単純に切り詰められないので None を返す。"""
        b = shogi.Board(sfen)
        before = []
        try:
            for u in pv:
                before.append(b.sfen())
                b.push_usi(u)
        except Exception:
            return None
        tail_n, tail_line = 0, []
        for i in range(len(pv) - 1, -1, -1):
            u = pv[i]
            if i % 2 == 0:
                tail_line = [u] + tail_line
                tail_n += 1
                continue
            budget = 1 + tail_n
            q = shogi.Board(before[i])
            if u[1] != "*":                      # 玉の移動・駒を取る手：無駄合ではない
                tail_line = [u] + tail_line
                tail_n += 1
                continue
            try:
                futile = is_futile(q, u, budget)
            except ValueError:
                self.incomplete.append(f"{i + 1}手目 {u} が無駄合か判定できませんでした")
                return None
            if not futile:
                tail_line = [u] + tail_line
                tail_n += 1
                continue
            # 手順の手は無駄合：ほかに（無駄合でない）応手が残るかを調べる
            rest = False
            for m in N.gen_evasions(q):
                mu = m.usi()
                if mu == u:
                    continue
                if mu[1] != "*":
                    rest = True
                    break
                try:
                    if not is_futile(q, mu, budget):
                        rest = True
                        break
                except ValueError:
                    self.incomplete.append(f"{i + 1}手目 {mu} が無駄合か判定できませんでした")
                    return None
            if rest:
                return None
            self.notes.append(f"{i + 1}手目 {u} は無駄合で、ほかの応手がないため、ここで詰みです（{len(pv) - i}手分短くなります）")
            tail_n, tail_line = 0, []
        return tail_n, tail_line

    def _exact_verify(self, sfen, n):
        """棋慧のエンジンで、「ちょうどn手で詰む（玉方がどう受けても、無駄合を除いて）」ことを確かめる。True/False/None(時間切れ)。"""
        old = N.TIMEOUT
        N.TIMEOUT = max(1.0, self.exact_sec)
        try:
            b = shogi.Board(sfen)
            if not N.can_mate(b, n):
                return False
            if n >= 3 and N.can_mate(b, n - 2):
                return False
            return True
        except ValueError:
            return None
        finally:
            N.TIMEOUT = old

    def _solve(self, sfen, depth):
        """攻方番の局面。Komoringの手順をもとに、無駄合を数えない最長の抵抗に直した (手数, 手順) を返す。"""
        k = _key(sfen)
        if k in self.memo:
            return self.memo[k]
        self.memo[k] = None
        ind = "  " * depth
        st, pv = self._ask(sfen)
        if st != "mate" or not pv:
            if st == "timeout":
                self.incomplete.append(f"{ind}時間切れ：{sfen}")
            return None
        b = shogi.Board(sfen)
        before = []
        try:
            for u in pv:
                before.append(b.sfen())
                b.push_usi(u)
        except Exception:
            self.incomplete.append(f"{ind}Komoringの手順が読めません：{sfen}")
            return None
        tail_n, tail_line = 0, []
        for i in range(len(pv) - 1, -1, -1):
            u = pv[i]
            if i % 2 == 0:                       # 攻方の手：Komoringの選んだ手をそのまま使う
                tail_line = [u] + tail_line
                tail_n += 1
                continue
            # 玉方の手の場面（i手目の前の局面は、玉方が王手を受けている）
            q = shogi.Board(before[i])
            budget = 1 + tail_n                  # この場面の残り手数（いま分かっている最長の筋で数える）
            cands = []
            for m in N.gen_evasions(q):
                mu = m.usi()
                if mu[1] == "*":
                    try:
                        if is_futile(q, mu, budget):
                            continue             # 無駄合は応手に数えない
                    except ValueError:           # 棋慧の判定が時間切れ：無駄合かどうか分からない（応手として残す）
                        self.incomplete.append(f"{ind}{i + 1}手目 {mu} が無駄合か判定できませんでした")
                cands.append(m)
            if not cands:
                # 無駄合を除くと、玉方に応手が残らない＝ここで詰み。この場面から後ろの手順は要らない
                self.notes.append(f"{ind}{i + 1}手目の場面は、無駄合を除くと応手がなく、詰みです（{len(pv) - i}手分短くなります）")
                tail_n, tail_line = 0, []
                continue
            cur_ok = any(m.usi() == u for m in cands)
            best_n = 1 + tail_n if cur_ok else -1
            best_line = [u] + tail_line if cur_ok else None
            if not cur_ok:
                self.notes.append(f"{ind}{i + 1}手目 {u} は無駄合のため除きます")
            # Komoringに、ほかの応手のあとの手数を聞く（手数の上限が分かる）
            alts = []
            for m in cands:
                mu = m.usi()
                if mu == u:
                    continue
                q2 = shogi.Board(before[i])
                q2.push(m)
                if self._over():
                    self.incomplete.append(f"{ind}問い合わせの上限に達しました")
                    break
                st2, pv2 = self._ask(q2.sfen())
                if st2 == "nomate":
                    # 普通のルールでも詰まない応手がある＝この局面は詰みではない
                    self.notes.append(f"{ind}{i + 1}手目 {mu} で逃れられます（不詰）")
                    return None
                if st2 != "mate":
                    self.incomplete.append(f"{ind}{i + 1}手目 {mu} のあとは確かめられませんでした（{st2}）")
                    continue
                alts.append((1 + len(pv2), mu, q2.sfen()))
            alts.sort(key=lambda x: -x[0])
            for bound, mu, s2 in alts:
                if bound <= best_n:
                    break                        # 上限が今の最長以下：追い越せないので調べない
                if depth >= self.max_depth:
                    self.incomplete.append(f"{ind}深さの上限")
                    continue
                self.log(f"{ind}{i + 1}手目の別の応手 {mu}（Komoringの手数 {bound}）を調べます")
                r = self._solve(s2, depth + 1)
                if r is None:
                    continue
                if 1 + r[0] > best_n:
                    if best_n > 0:
                        self.notes.append(f"{ind}{i + 1}手目：{u} より {mu} のほうが長く粘れます（{1 + r[0]}手 > {best_n}手）")
                    best_n, best_line = 1 + r[0], [mu] + r[1]
            if best_line is None:
                return None
            tail_n, tail_line = best_n, best_line
        self.memo[k] = (tail_n, tail_line)
        return self.memo[k]


def check(sfen, line, max_shorter=17):
    """棋慧のエンジンで、取り替えた手順の最低限の検査をする。"""
    out = {"legal": True, "mate": False, "shorter": None, "extra_piece": None, "futile": []}
    b = shogi.Board(sfen)
    try:
        for i, u in enumerate(line):
            if i % 2 == 1 and u[1] == "*":
                try:
                    if is_futile(b, u, len(line) - i):
                        out["futile"].append(u)
                except ValueError:
                    pass
            b.push_usi(u)
    except Exception:
        out["legal"] = False
        return out
    out["mate"] = b.is_check() and not N.gen_evasions(b)
    n = len(line)
    if 3 <= n <= max_shorter:
        try:
            out["shorter"] = bool(N.can_mate(shogi.Board(sfen), n - 2))
        except ValueError:
            out["shorter"] = None            # 時間切れ
    elif n > max_shorter:
        out["shorter"] = None                # 手数が長く、短い詰みがないかは調べない
    hand = b.pieces_in_hand[shogi.BLACK]
    out["extra_piece"] = sum(hand.values()) > 0
    return out



# ---------------------------------------------------------------- 収録DBをまとめて流す
def classify(steps, db_line, res):
    """棋慧に入っている作意の手数・手順と、修復後の結果を見比べて、分類を返す。"""
    if res["state"] != "mate" or not res.get("line"):
        return "×詰みを返さず" if res["state"] != "broken" else "×途中で逃れられた"
    n = res["n"]
    if n == steps:
        if not db_line:
            return "○手数一致（作意の手順なし）"
        return "◎手数・手順とも一致" if list(res["line"]) == list(db_line) else "○手数一致（手順は別）"
    return "△修復後が短い" if n < steps else "△修復後が長い"


def _ref_len(sfen, max_n, sec):
    """棋慧のエンジンだけで解いた詰み手数（無駄合を除く）。分からなければ '?'。"""
    b = shogi.Board(sfen)
    old = N.TIMEOUT
    N.TIMEOUT = max(1.0, sec)
    try:
        N._run("clear")
        for n in range(1, max_n + 1, 2):
            if N.can_mate(b, n):
                return n
        return "?"
    except ValueError:
        return "?"
    finally:
        N.TIMEOUT = old


def run_batch(a, ask, here):
    import csv
    import json
    import os
    import time
    import tsume_verify as V
    path = a.db or os.path.join(here, "tsume_db.jsonl")
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    want = set(x.strip() for x in a.ids.split(",")) if a.ids else None
    rows = [r for r in rows if (want is None or r["id"] in want)
            and a.min_steps <= int(r["steps"]) <= a.max_steps]
    if a.sample and len(rows) > a.sample:
        import random
        rows = random.Random(a.seed).sample(rows, a.sample)    # 手数の偏りなく、無作為に選ぶ（同じ種なら同じ問題）
    if a.limit:
        rows = rows[:a.limit]
    N.TIMEOUT = max(1.0, a.judge_sec)            # 棋慧エンジンの1回の判定の制限時間（無駄合の判定など）
    out_path = a.out or os.path.join(here, "kh_repair_batch.csv")
    print("対象: %d問（%d〜%d手） → 結果は %s に書きます" % (len(rows), a.min_steps, a.max_steps, out_path), flush=True)
    summary = {}
    t_all = time.time()
    with open(out_path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "題", "作意の手数", "Komoringの手数", "修復後の手数", "棋慧単独の手数", "分類", "手順は変更", "問い合わせ回数", "Komoring秒", "全体秒", "注記", "柿木の判定メモ"])
        for i, r in enumerate(rows, 1):
            sfen, steps, db_line = r["sfen"], int(r["steps"]), r["line"]
            asker = Asker(ask)
            t0 = time.time()
            try:
                t1 = time.time()
                first = ask(sfen, a.root_ms) if hasattr(ask, "close") else ask(sfen)
                asker.seed(sfen, first, time.time() - t1)
                rp = Repair(asker, max_asks=a.max_asks, time_limit=a.time_limit)
                res = rp.run(sfen)
            except Exception as e:                       # 1問の失敗で全体を止めない
                res = {"state": "error", "n": None, "line": [], "komoring_n": 0, "asks": asker.count, "changed": False,
                       "notes": [], "incomplete": [str(e)]}
                rp = None
            cls = classify(steps, db_line, res)
            ref = ""
            if a.ref and steps <= a.ref_max:
                ref = _ref_len(sfen, min(a.ref_max, steps + 2), a.ref_sec)
                if res["state"] == "mate" and ref not in ("", "?"):
                    cls += "／棋慧単独と一致" if ref == res["n"] else "／棋慧単独と不一致"
            if res["state"] == "mate":
                chk = check(sfen, res["line"])
                if chk.get("shorter"):
                    cls += "／短い詰みあり"
                if chk.get("extra_piece"):
                    cls += "／駒余り"
            summary[cls] = summary.get(cls, 0) + 1
            sec = time.time() - t0
            note = "；".join(res.get("incomplete", [])[:2])
            w.writerow([r["id"], r["title"], steps, res.get("komoring_n"), res.get("n"), ref, cls,
                        "はい" if res.get("changed") else "いいえ", res.get("asks"), "%.1f" % asker.sec, "%.1f" % sec, note, r.get("memo", "")])
            fh.flush()
            print("[%d/%d] %s %d手  Komoring %s手 → 修復後 %s手%s  %s  (問い合わせ%s回・%.1f秒)%s" % (
                i, len(rows), r["id"], steps, res.get("komoring_n"), res.get("n"),
                ("（棋慧単独 %s手）" % ref) if ref != "" else "", cls, res.get("asks"), sec,
                ("  ※" + r["memo"].split("※")[-1]) if "柿木" in r.get("memo", "") else ""), flush=True)
            if note:
                print("      理由:", note[:200], flush=True)
    print()
    print("まとめ（%d問・%.0f秒）" % (len(rows), time.time() - t_all))
    for k, v in sorted(summary.items(), key=lambda x: -x[1]):
        print("  %-24s %d問" % (k, v))
    print("詳しくは", out_path, "（Excelで開けます）")


# ---------------------------------------------------------------- 試験用の起動（python tsume_kh_repair.py）
DEMOS = {
    1: "9/9/6ppn/7k1/5G2P/9/9/9/9 b RGN2b2g4s2n4l15p 1",              # 27飛打に26角合のある11手詰（柿木の解は26角合を含む）
    2: "7n1/5p2l/5b1kN/5+RP2/9/9/9/9/9 b BNr4g4sn3l16p 1",             # 33歩成から始まる15手詰（Komoringは無駄合を3回含む19手を出す）
}
DEMO_SFEN = DEMOS[1]


def main(argv=None):
    import argparse
    import os
    import sys
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="Komoringの手順の無駄合を、問い合わせで直す（試験版）")
    ap.add_argument("--sfen", default=None, help="攻方番の局面のSFEN（省略すると --demo の問題）")
    ap.add_argument("--demo", type=int, default=1, choices=sorted(DEMOS), help="試験用の問題：1=27飛打に26角合の11手詰 / 2=33歩成から始まる15手詰")
    default_exe = os.path.join(here, "user-normal-g++-avx2.exe")
    try:                                   # 棋慧の設定（詰将棋専用エンジンの場所）があれば、それを使う
        import json
        with open(os.path.join(here, "config.json"), encoding="utf-8") as fh:
            p = json.load(fh).get("tsume_engine_path", "")
        if p and os.path.exists(p):
            default_exe = p
    except Exception:
        pass
    ap.add_argument("--exe", default=default_exe, help="KomoringHeightsのexe（省略すると、棋慧の設定にある詰将棋専用エンジン）")
    ap.add_argument("--ms", type=int, default=3000, help="1回の問い合わせの制限時間(ミリ秒)")
    ap.add_argument("--max-asks", type=int, default=800, help="問い合わせ回数の上限")
    ap.add_argument("--batch", action="store_true", help="収録DB（tsume_db.jsonl）の問題を、まとめて流して作意と見比べる")
    ap.add_argument("--db", default=None, help="DBのファイル（省略すると、このフォルダの tsume_db.jsonl）")
    ap.add_argument("--min-steps", type=int, default=1, help="まとめて流すときの手数の下限")
    ap.add_argument("--max-steps", type=int, default=19, help="まとめて流すときの手数の上限")
    ap.add_argument("--ids", default="", help="まとめて流す問題のid（カンマ区切り。例: zukou-002,musou-010）")
    ap.add_argument("--limit", type=int, default=0, help="まとめて流す問題数の上限（0=制限なし）")
    ap.add_argument("--sample", type=int, default=0, help="条件に合う問題から、無作為にこの数だけ選ぶ（0=全部）")
    ap.add_argument("--seed", type=int, default=1, help="--sample の無作為の種（同じ数なら同じ問題が選ばれる）")
    ap.add_argument("--root-ms", type=int, default=20000, help="まとめて流すとき、問題そのものを聞く制限時間(ミリ秒)")
    ap.add_argument("--time-limit", type=float, default=120.0, help="まとめて流すとき、1問あたりの制限時間(秒)")
    ap.add_argument("--out", default=None, help="まとめて流した結果のCSV（省略すると kh_repair_batch.csv）")
    ap.add_argument("--ref", action="store_true", help="棋慧のエンジンだけで解いた手数も出して、見比べる（13手くらいまで）")
    ap.add_argument("--judge-sec", type=float, default=15.0, help="棋慧エンジンの1回の判定（無駄合かどうか等）の制限時間(秒)")
    ap.add_argument("--ref-max", type=int, default=15, help="--ref のとき、棋慧単独で調べる手数の上限（これより長い問題は調べない）")
    ap.add_argument("--ref-sec", type=float, default=40.0, help="--ref のとき、1問あたりの制限時間(秒)")
    a = ap.parse_args(argv)
    sfen = a.sfen or DEMOS[a.demo]
    if a.batch:
        ask = komoring_fn(a.exe, a.ms)
        try:
            run_batch(a, ask, here)
        except KeyboardInterrupt:
            print("\n中断しました（ここまでの結果はCSVに残っています）")
        finally:
            ask.close()
        return 0
    if not os.path.exists(a.exe):
        print("KomoringHeightsが見つかりません:", a.exe)
        print("--exe で exe の場所を指定してください。")
        return 1
    import tsume_verify as V
    print("局面:", sfen)
    ask = komoring_fn(a.exe, a.ms)
    try:
        rp = Repair(ask, log=lambda s: print("  ・", s, flush=True), max_asks=a.max_asks)
        res = rp.run(sfen)
    finally:
        ask.close()
    print()
    print("Komoringの手順 (%d手):" % res["komoring_n"], V.line_ja(sfen, res["komoring_pv"]) if res["komoring_pv"] else "（なし）")
    if res["state"] not in ("mate",):
        print("結果:", res["state"], "（Komoringが詰みを返さなかった、または途中で詰みでない応手が見つかりました）")
    else:
        print("修復後の手順 (%d手):" % res["n"], V.line_ja(sfen, res["line"]))
        print("手順は", "取り替わりました" if res["changed"] else "そのままです")
        print("確認:", check(sfen, res["line"]))
    for n in res["notes"]:
        print(" *", n)
    for n in res["incomplete"]:
        print(" !", n)
    print("問い合わせ: %d回 / Komoringの合計時間 %.1f秒 / 全体 %.1f秒" % (res["asks"], rp.ask.sec, res["sec"]))
    print("  内訳:", {k: (v[0], round(v[1], 1)) for k, v in rp.ask.by_state.items()})
    if a.ref:
        import time
        t = time.time()
        b = shogi.Board(sfen)
        found = None
        for n in range(1, 14, 2):
            try:
                if N.can_mate(b, n):
                    found = n
                    break
            except ValueError:
                break
        print("棋慧のエンジンだけで解くと:", ("%d手詰" % found) if found else "13手以内には見つからず", "（%.1f秒）" % (time.time() - t))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
