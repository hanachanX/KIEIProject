# 詰将棋 C++ DLL（tsume.dll）

棋慧の詰将棋エンジンです。もともとPythonで書いていた `tsume.py`（盤面処理、王手・応手の生成、詰み探索、唯一解・駒余りの検証、逆算生成）を、速くするためにC++17へ移したもので、Windows x64向けの単体DLLになっています。DLLの中でPythonが動くわけではありません。

棋慧はこのDLLがあれば自動で使い（`tsume_native.py` 経由）、無ければ従来の `tsume.py` に切り替わります。比較用にPython版も残しています。

## このDLLの特徴

一番の売りは、**無駄合を応手に数えない**ことです。柿木の定義に沿って、無駄な合駒は玉方の抵抗として扱いません。KomoringHeightsなどの一般的な詰将棋ソルバーは無駄合を区別しないので、そのせいで見逃される余詰を、このDLLは拾えます。

得意なこと・苦手なことの目安は次のとおりです。

- **作意の手順がわかっていて、検証したい場合は速い。** 17手の作品でも、十数秒で余詰の有無まで確かめられます。
- **厳密な手数・余詰の確認とは別に、df-pnによる簡易な詰み問合せを備えます。** df-pnの候補手順は、無駄合を含んだり最短手数より長くなったりするため、厳密な検証結果とは区別してください。
- **何十手、何百手の長編は対象外。** そういう用途には、脊尾氏のプログラムのような専用ソフトのほうが向いています。

あくまで「短編〜中編を、厳しく検査する道具」です。通常の将棋対局用エンジンではありません。

## 使われているところ

- 棋慧の詰将棋モード（解く、手順検証、余詰・不完全の検査）
- 「実戦から詰将棋を取り出す」機能
- 詰将棋ビルダーの判定サーバー（別フォルダの `dll_server.py` が、このDLLを呼びます）

## ビルド

Visual Studioの「C++によるデスクトップ開発」が必要です。PowerShellで、このリポジトリのルートから次を実行します。

```powershell
cmd /c native_tsume\build.bat
```

通常はインストール済みのVisual Studioを自動検出します。検出できない場合は「x64 Native Tools Command Prompt」で `native_tsume\build.bat` を実行してください。

完成品は **`native_tsume\tsume.dll`** です（`.gitignore` で除外しているので、リポジトリには入っていません。使う人が自分でビルドしてください）。Release相当の最適化 `/O2` と、静的C++ランタイム `/MT` を指定しています。64bit版Pythonを使ってください。

Visual Studioの通常のDLLプロジェクトでビルドする場合は、`tsume.cpp` と `tsume.h` を追加し、C++17・x64・プリコンパイル済みヘッダー「使用しない」を設定します。付属のCMake設定も利用できます。

## Pythonから試す

リポジトリのルートで実行します。

```python
import shogi
import tsume_native as solver

# 頭金の1手詰。
board = shogi.Board("4k4/9/4G4/9/9/9/9/9/9 b G 1")
print(solver.can_mate(board, 1))
print([move.usi() for move in solver.solve(board, 1)])
```

生成も探索全体をDLL内で行います。

```python
import random
import tsume_native as solver

result = solver.generate(3, random.Random(42), budget=600, time_limit=10)
if result is not None:
    sfen, moves = result
    print(solver.show(sfen))
    print(sfen, moves)
```

既存の利用側を切り替える場合は `import tsume as solver` を `import tsume_native as solver` に変更します。`tsume_jissen.py` 内の `import tsume as _t` も別の呼び出し先なので、アプリ全体を切り替える際はそちらも確認してください。

## 移植範囲と互換性

- `can_mate`、`solve`、`defenders_all_lose`、`mate_length_exact`、`principal_line`、`verify`、`gen_checks`、`gen_evasions`、`clear_cache` はPython版と同じ引数・戻り値の形式です。
- 逆算候補生成、前進照合、生成途中の健全性判定、乱数による詰み上がり生成、逆算探索もC++にあります。Pythonの `_try_unmove`、`_forward_matches`、`_node_ok`、`random_mate_position`、`_search` にも窓口を用意しています。
- `Pos`、`pos_from_board`、`show`、定数はPython版を再利用します。Python側の盤面表示とデータ変換のためのもので、DLL内部の探索からPythonへ戻ることはありません。
- 攻方は先手、玉方は後手。主な対象は元のコード同様、攻方玉なしの詰将棋です。通常の将棋対局用エンジンではありません。
- 無駄合は、玉方の応手に数えません（柿木の定義）。打ち歩詰めも判定します。ただし、将棋のルールに対して「完全に正しい」と証明されたものではなく、実戦で確かめながら直している段階です。
- 乱数生成器はC++標準の `mt19937_64` を使用します。同じPythonのseedから、Python版と同じ作品が出ることは保証しません。
- 手の集合が同じでも、SFENからの復元や逆算時の列挙順の違いにより、同長の抵抗手の選択や生成結果は変わる場合があります。
- Python版 `principal_line` が不成功時に入力盤面を変更する場合がありますが、DLL版は成功・失敗とも呼び出し元の盤面を変更しません。
- キャッシュはスレッドごとです。`clear_cache()` は呼び出したスレッドのキャッシュを消します。DLL呼び出し中はctypesがGILを解放します。
- 生成の時間制限は探索内部でも確認します。従来版の「外側のループだけで確認する」動作とは異なり、途中の探索も打ち切ります。
- `_CACHE_A` など内部のPython辞書を外から直接操作するAPIは提供しません。

## 比較検証

実施済みの結果は [VALIDATION.md](VALIDATION.md) にまとめています。

```powershell
python native_tsume\check_native.py
python native_tsume\check_edges.py
```

`check_native.py` は付属問題集の初形・途中・終盤の王手／応手をPython版と比較し、浅い探索、逆算候補、生成問題、並行呼び出しを検証します。最後に両実装の小規模な速度比較を表示します。`check_edges.py` は成り・二歩・打ち歩詰め・合駒・入力エラー・出力バッファを確認します。

## C API

`tsume.h` の `tsume_create` でコンテキストを作り、`tsume_run` を呼び、最後に `tsume_destroy` で解放します。一つのコンテキストを複数スレッドで同時に使わないでください。

`tsume_run` は結果文字列に必要なバイト数（終端NULを含む）を返します。エラーは `-1` で、詳細は `tsume_error` から取得します。バッファが不足した場合は書き込まず、直前の結果をコンテキスト内に保持します。`tsume_copy_result` で大きなバッファにコピーできます。生成を再実行する必要はありません。

主なoperation:

| operation | 主な入力 | 文字列の結果 |
|---|---|---|
| `checks`, `evasions`, `solve`, `moves` | SFEN、必要に応じてn/color | 空白区切りUSI |
| `can_mate`, `defenders`, `exact` | SFEN、n | `1` / `0` |
| `line`, `verify` | SFEN、n | 空白区切りUSI、不成立は `-` |
| `unmove` | SFEN、color | `SFEN<TAB>USI` の行一覧 |
| `dead`, `node` | SFEN、必要に応じてn/color | `1` / `0` |
| `random` | seed | SFEN、不成立は空文字 |
| `generate` | n、seed、budget、seconds | `SFEN`＋改行＋USI列、時間切れは空文字 |
| `search` | SFEN、残り逆算数n、color、seed、budget | SFEN（不成立は `-`）＋改行＋残予算 |
| `forward` | `QのSFEN`＋改行＋`PのSFEN`＋改行＋USI、color | `1` / `0` |
| `futile` | SFEN＋改行＋合駒USI、n=王手駒のマス番号 | `1` / `0` |
| `final_alt` | n（0=最終手の別解を許さない、0以外=許す） | 空文字。以後の判定で、最後の1手だけは複数の詰み手を許す |
| `clear` | なし | 空文字 |

SFENとUSIはASCII。colorは先手=0・後手=1、マス番号はSFENの左上=0から行優先で80までです。通常はPythonの窓口経由で利用してください。

ここに載せていない操作（`legal`、`pseudo`、`oracle_min`、`oracle_stats` など）は、`tsume.cpp` の `run_inner` 付近を見てください。


## エンジンの更新（2026-11-16）

Research版のC++エンジンとルートの `tsume_native.py` を移植しました。画面、詰将棋DB、`tsume_verify.py` は今回変更していません。Research側の並行探索・不詰証明の画面連携は含みません。

### ビルドに必要なソース

`tsume.cpp`、`tsume.h` に加え、同じフォルダの次の4ファイルが必要です。

- `slider_magic.h`
- `slider_magic_constants.h`
- `dfpn_proof.h`
- `dfpn_feedback.h`

既存の `build.bat` とCMake設定でビルドできます。配布元から更新した場合はDLLを再ビルドし、棋慧を再起動してください。DLL・中間生成物はGitの対象外です。

### 主な変更

- ビットボードと飛び駒の利きの表引き、盤面・利きのキャッシュを導入。
- 玉方の支え駒の向きの判定を修正。相手駒がある升への駒打ちを拒否。
- 既存のC APIの引数と操作名を維持。
- context単位の停止、df-pnと厳密探索の進捗通知を追加。
- df-pnの証明記録・点検、省略した合駒の再探索、初手除外、不詰の逃れ記録を追加。

### 追加APIと判定の限界

`tsume_native.py` の `ContextStop` は独立したcontextの探索を停止します。`SearchProgress` は同じスレッドで行った探索の訪問数を合算します。`quick_mate` は任意の `progress`、`excluded_firsts`、`nonmate_trace` 引数を受け取ります。従来の引数による呼び出しも維持しています。

C APIの `tsume_cancel_context` は対象contextだけを停止します。`tsume_set_progress` と `tsume_set_search_progress` は探索スレッドから通知します。コールバックの登録・解除はcontextが停止中に行い、コールバック内から同じcontextを再び呼ばないでください。

診断の `certificate_complete` は、記録した分岐の証明を復元できたという意味です。最短手数・余詰・全無駄合規則の検証完了を意味しません。初手を除外した探索の不詰は、局面全体の不詰を意味しません。不詰トレースも独立に点検するための資料で、取得だけでは不詰証明になりません。

すべての問題での高速化や判定の完全性を保証するものではありません。今回の確認内容は [VALIDATION.md](VALIDATION.md) を参照してください。
