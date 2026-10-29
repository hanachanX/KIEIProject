# 人間の定跡表（build_book.py で作った .npz）を引くための部品
import os
import numpy as np
import shogi


class Book:
    def __init__(self, path):
        d = np.load(path)
        self.h, self.m, self.n, self.w, self.l = d["h"], d["m"], d["n"], d["w"], d["l"]

    @staticmethod
    def dec(code):
        f, to, pr = int(code) >> 8, (int(code) >> 1) & 127, int(code) & 1
        if f >= 82:
            return shogi.Move(None, to, False, f - 81)
        return shogi.Move(f, to, bool(pr))

    def lookup(self, board):
        """局面の定跡手を [(usi, 回数, 勝ち, 負け)] で返す（多い順）。なければ空。"""
        key = np.uint64(board.zobrist_hash())
        lo = np.searchsorted(self.h, key, "left"); hi = np.searchsorted(self.h, key, "right")
        out = []
        for i in range(lo, hi):
            out.append((self.dec(self.m[i]).usi(), int(self.n[i]), int(self.w[i]), int(self.l[i])))
        out.sort(key=lambda x: -x[1])
        return out
