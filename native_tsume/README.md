# 棋慧の詰将棋エンジン（tsume.dll）

棋慧（KIEI）の詰将棋探索・手順検証・逆算生成を行う、C++17製のWindows x64向けDLLです。Pythonからは、リポジトリ直下の `tsume_native.py` を通して呼び出します。探索はC++内で実行し、通常の探索処理がPythonへ戻ることはありません。外部判定を登録するoracle機能は例外です。

2026年11月16日に、KIEIResearchで改良したエンジンを公開用プロジェクトへ移植しました。このREADMEは移植後の構成を説明します。

## 何ができるか

- 王手・応手の生成、指定手数以内の詰み探索。
- 詰み手数、本手順、唯一解・駒余りなどの検証に使う処理。
- 無駄合を玉方の抵抗から除くための判定、打ち歩詰めの判定。
- df-pnによる、手数を指定しない簡易な詰み問合せと候補手順の取得。
- 詰み上がりからの逆算、候補の前進照合、問題生成。
- 探索の進捗通知、スレッドごとに独立した探索と個別中断。

攻方は先手、玉方は後手です。主な対象は攻方玉なしの短編〜中編の詰将棋で、通常の将棋対局用エンジンではありません。長い作品や重い局面では、時間・メモリの制約に達することがあります。

### 指定手数の検証とdf-pnの違い

| 用途 | 使う処理 | 結果の読み方 |
| --- | --- | --- |
| 指定した手数で詰むか調べる | `can_mate`、`solve` など | 指定手数内での結果。詰まなくても、さらに長い手数で詰む可能性は残る |
| 手順や手数を検証する | `verify`、`principal_line` など | エンジンの無駄合・最終手別解などの設定に従う |
| まず詰み候補を探す | `quick_mate`（df-pn） | 簡易な詰み判定と手順の一例。最短手数・余詰・無駄合の検証完了を意味しない |

ここでいう厳密側の探索も、実装の正しさを全局面で証明したという意味ではありません。既知の比較結果と制限は [VALIDATION.md](VALIDATION.md) に記載しています。

## Research版から取り込んだ変更

### 盤面処理と探索の高速化

- ビットボードによる駒・占有升・利きの処理。
- 飛車・角・香の利きを表引きする仕組み（slider magic）。
- 升の間の集合や近接駒の利きの事前計算。
- 玉位置・歩の筋情報・局面ハッシュなどの管理の改善。
- 王手、応手、無駄合判定で不要な走査や盤面コピーを減らす処理。

Research側の保存記録では、固定した27問の通常探索で合計時間が約12〜13％短縮されています。比較条件と問題群に限った測定であり、公開版からの一律の高速化率や、すべての問題での改善を示すものではありません。

### 不具合修正

- 玉方の支え駒の利きを、正しい駒種と玉方の向きで判定するよう修正。
- 駒打ちで相手駒のある升へ置けてしまう条件を修正。盤上の駒による通常の駒取りは維持。

このため、不具合に関係する局面では旧版と判定が変わる場合があります。

### 探索制御・診断機能

- context単位の停止・再開準備。
- df-pn単独、および複数の探索呼び出しを通した訪問数の通知。
- df-pnの証明記録、探索表から独立した記録の点検。
- 省略した合駒を戻した再探索と、その記録の取り出し。
- 指定した初手を除外するdf-pn探索。
- 不詰候補について、玉方の逃れを後から点検するための記録。

**今回移植したのはエンジンとPython窓口です。** Research側の並行探索を制御するアプリ処理や、不詰記録を独立に点検して画面へ反映する処理は含みません。DLLを更新するだけで、それらの画面機能が追加されるわけではありません。

## ファイル構成

| ファイル | 役割 |
| --- | --- |
| `tsume.cpp` | 盤面、手生成、探索、検証、逆算生成、C API本体 |
| `tsume.h` | 公開するC APIの宣言 |
| `slider_magic.h` | 飛び駒の利きの表引き |
| `slider_magic_constants.h` | 表引きに必要な定数 |
| `dfpn_proof.h` | df-pnの証明記録・点検 |
| `dfpn_feedback.h` | 合駒を戻す再探索と記録の連携 |
| `build.bat`、`CMakeLists.txt` | ビルド設定 |
| `check_native.py`、`check_edges.py`、`check_upgrade.py` | 比較・回帰確認 |
| `../tsume_native.py` | Pythonから呼び出す窓口 |
| `VALIDATION.md` | 実施した確認と既知の不一致 |

`tsume.cpp` だけをコピーしてもビルドできません。上記のヘッダー5個も同じフォルダに置いてください。`native_tsume` 内に古いPythonファイルなどが手元に残っている場合も、利用する窓口はリポジトリ直下の `tsume_native.py` です。

## ビルドと更新

Windows x64、64bit版Python、Visual Studioの「C++によるデスクトップ開発」が必要です。リポジトリのルートで実行します。

```powershell
cmd /c native_tsume\build.bat
```

Visual Studioを自動検出し、C++17・`/O2`・`/MT`・x64でビルドします。検出できない場合は「x64 Native Tools Command Prompt」から実行してください。

完成品は `native_tsume\tsume.dll` です。DLL、オブジェクト、ライブラリなどの生成物はGit対象外のため、ソースを取得した利用者側でビルドします。更新時は棋慧を終了し、再ビルドしてから起動し直してください。実行中のアプリには、更新前のDLLが読み込まれたままになる場合があります。

CMakeでビルドする場合は、完成した `tsume.dll` を `native_tsume` 直下に配置してください。Python窓口はその場所から読み込みます。

## Pythonから使う

以下の例はすべて、リポジトリのルートで実行します。`python-shogi` など、プロジェクトの依存ライブラリを先に導入してください。

### 指定手数の探索

```python
import shogi
import tsume_native as solver

sfen = "4k4/9/4G4/9/9/9/9/9/9 b G 1"
board = shogi.Board(sfen)
print(solver.can_mate(board, 1))
print([move.usi() for move in solver.solve(board, 1)])
```

### df-pnによる詰み問合せ

```python
import tsume_native as solver

sfen = "4k4/9/4G4/9/9/9/9/9/9 b G 1"
try:
    state, moves = solver.quick_mate(sfen, seconds=10)
    print(state, moves)
except ValueError as exc:
    if "timeout" in str(exc):
        print("時間切れ：結論未確定")
    else:
        raise
```

戻り値の状態は `mate`、`nomate`、`unknown` です。時間切れは状態文字列ではなく `ValueError("timeout")` になります。`nomate` は簡易判定として扱い、厳密な不詰証明としてそのまま採用しないでください。

`quick_mate` には次の任意引数があります。

| 引数 | 用途 |
| --- | --- |
| `progress=callback` | `nodes`、`search_seconds`、`phase` を含む辞書を受け取る |
| `excluded_firsts=["USI", ...]` | 指定した初手を根だけで除外する。除外後の不詰は局面全体の不詰ではない |
| `nonmate_trace=True` | 後から逃れを点検するための記録を残す。初手除外を指定した場合は初手除外の操作が優先される |

### 複数呼び出しの探索数を合算する

```python
import shogi
import tsume_native as solver

board = shogi.Board("4k4/9/4G4/9/9/9/9/9/9 b G 1")
with solver.SearchProgress() as meter:
    solver.can_mate(board, 1)
    solver.solve(board, 1)
    print(meter.snapshot())
```

訪問数は、同じ局面への再訪やキャッシュ参照を含む探索関数の呼び出し数です。異なる局面の個数ではありません。`SearchProgress` の経過時間には、呼び出しの間のPython側の処理時間も含まれます。一方、`quick_mate` の進捗の `search_seconds` はdf-pn探索時間で、手順構築時間を含みません。

### 逆算生成

```python
import random
import tsume_native as solver

result = solver.generate(3, random.Random(42), budget=600, time_limit=10)
if result is not None:
    sfen, moves = result
    print(sfen, moves)
```

C++側は `mt19937_64` を使います。同じPythonのseedから、Python版と同じ作品が生成されることは保証しません。

## 互換性・スレッド・中断

従来のC公開関数の引数と既存の操作名は維持しています。`can_mate`、`solve`、`defenders_all_lose`、`mate_length_exact`、`principal_line`、`verify`、`gen_checks`、`gen_evasions` などのPython側の呼び出し形式も維持しています。ただし、不具合修正や手の列挙順の違いにより、結果の手順が旧版と変わる場合があります。

`Pos`、`pos_from_board`、`show`、定数などはPython版 `tsume.py` を再利用するため、DLLと窓口だけを単独で配置する構成ではありません。直接 `tsume_native` を呼んだ場合、DLLがなければエラーになります。Python版への切替は利用側の処理です。

各スレッドのcontextは探索表・キャッシュを独立して持ちます。`clear_cache()` は呼び出したスレッドのcontextを消去します。一つのcontextを複数スレッドから同時に探索へ使わないでください。

- `cancel(True)` は全体の停止要求、`cancel(False)` はその解除です。
- `ContextStop.bind()` は探索するworkerスレッドで呼びます。別スレッドから `stop()` を呼ぶと、そのcontextだけに停止を要求できます。
- 停止した探索が終了してから `rearm()` で停止要求を解除して再利用し、使い終わったハンドルは `close()` します。
- 進捗コールバックの登録・解除は、contextが探索していないときに行います。コールバックは探索スレッド上で実行され、同じcontextへの再入は禁止です。
- 旧DLLでは任意の進捗通知を省略する場合がありますが、個別停止や追加操作には新DLLが必要です。ソースとPython窓口を更新したらDLLも再ビルドしてください。

## 証明記録・合駒補修の診断API

| Python API | 用途 |
| --- | --- |
| `proof_report(sfen, ...)` | df-pnを実行し、上限付きで証明根拠を記録・点検する |
| `last_proof_report()` | 同じcontextに残る最後の診断記録を再点検する |
| `export_proof()` | 元の記録と、持駒違いに適用できた対象局面の記録を取り出す |
| `repair_defense(sfen, move, ...)` | 玉方局面で指定した合駒を省かず再探索する |
| `repair_pending(sfen, ...)` | 未確認の合駒を上限付きで問い合わせ、記録を再点検する |
| `export_feedback()` | 分離した再探索で得た記録を取り出す |

これらは診断用です。`certificate_complete` は記録の分岐を復元できたという意味で、最短手数・余詰・全無駄合規則の検証完了を意味しません。時間や記録容量が不足した場合は未確認のまま扱います。診断の結果を厳密側の確定キャッシュへ自動的に流用するものではなく、`repair_pending` の `strict_result_reused` は常に `False` です。

不詰の逃れ記録も、それだけで独立した不詰証明にはなりません。記録を取得した後の独立点検は、このDLLとは別の利用側の処理です。

## C API

宣言は `tsume.h` にあります。`tsume_create` → `tsume_run` → `tsume_destroy` の順で利用します。

`tsume_run` は結果文字列に必要なバイト数（終端NULを含む）を返します。エラー時は `-1` で、詳細は `tsume_error` から取得できます。出力バッファが不足した場合は書き込まず、結果をcontext内に保持します。`tsume_copy_result` で大きなバッファへコピーでき、探索や生成を再実行する必要はありません。

| 操作 | 主な結果 |
| --- | --- |
| `checks`、`evasions`、`solve`、`moves` | 空白区切りUSI |
| `can_mate`、`defenders`、`exact` | `1` / `0` |
| `line`、`verify` | 空白区切りUSI、不成立は `-` |
| `random`、`unmove`、`generate`、`search` | SFENや手順など。形式はPython窓口を参照 |
| `dfpn`、`dfpn_trace`、`dfpn_excluding` | `M`（詰み候補と手順）、`N`（不詰候補）、その他未確定 |
| `dfpn_proof`、`proof_report`、`proof_export` | 証明記録や点検結果のJSON |
| `repair_defense`、`feedback_export` | 合駒補修の結果・記録のJSON |
| `nonmate_trace` | 不詰候補の逃れ記録のJSON |
| `final_alt` | 最終手の別解を許すか設定 |
| `clear` | キャッシュ・診断記録などを消去 |

`tsume_cancel_context`、`tsume_set_progress`、`tsume_set_search_progress` が個別停止・進捗通知の追加C APIです。詳細な引数・コールバックの条件は `tsume.h` を参照してください。

SFENとUSIはASCII、colorは先手=0・後手=1、升番号はSFENの左上=0から行優先で80までです。複合入力や設定操作の形式は `tsume.cpp` の `run_inner` と `tsume_native.py` に定義されています。通常はPython窓口を使ってください。

## 検証方法と既知の制限

リポジトリのルートで実行します。

```powershell
python native_tsume\check_edges.py
python native_tsume\check_upgrade.py
python native_tsume\check_native.py --skip-corpus
```

- `check_edges.py`：107個の個別・ランダム盤面、合法性、逆算補助、入力・出力バッファなどのC APIを確認。
- `check_upgrade.py`：進捗の累積、df-pn手順の合法性と終端詰み、初手除外API、個別中断とcontext再利用を確認。
- `check_native.py --skip-corpus`：問題集全体の手生成比較を省き、終盤探索・逆算候補・生成などをPython版と比較。

全問題集の比較は `python native_tsume\check_native.py` です。ただし、現時点ではPython版とC++版の応手集合に既知の不一致が1件あり、その局面で停止します。旧DLLでも同じ不一致があり、今回の移植で導入された差ではありません。無駄合による除外の適否は未確定です。

移植時には、旧・新DLLの王手／応手が200問・1,507局面で一致し、別の既存抽出21問でも指定手数での詰み判定が一致しました。これは有限の回帰確認であり、全局面での正しさや高速化の保証ではありません。条件・実測結果・不一致の再現局面は [VALIDATION.md](VALIDATION.md) を参照してください。
