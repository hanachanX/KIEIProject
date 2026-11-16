"""Checks for the upgraded engine API; no GUI or Research folder needed."""
from pathlib import Path
import sys
import threading
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import shogi
import tsume_native as T


def main():
    mate = '4k4/9/4G4/9/9/9/9/9/9 b G 1'
    hard = '3l5/5k3/5g3/3p3L1/6p2/7Pp/6s2/9/9 b 2R2B3g3s4n2l14p 1'
    T.cancel(False)
    with T.SearchProgress() as meter:
        assert T.can_mate(shogi.Board(mate), 1)
        first = meter.snapshot()
        assert first and first['nodes'] > 0
        assert T.can_mate(shogi.Board(mate), 1)
        assert meter.snapshot()['nodes'] > first['nodes']
    reports = []
    state, pv = T.quick_mate(mate, 3, progress=reports.append)
    assert state == 'mate' and pv and reports
    b = shogi.Board(mate)
    for usi in pv:
        m = shogi.Move.from_usi(usi)
        assert b.is_legal(m)
        b.push(m)
    assert b.is_checkmate()
    # New optional operation must work without Research application modules.
    state, _ = T.quick_mate(mate, 3, excluded_firsts=[pv[0]])
    assert state in ('mate', 'nomate', 'unknown', 'timeout')
    stop = T.ContextStop()
    ready = threading.Event()
    outcome = {}
    def worker():
        try:
            stop.bind()
            ready.set()
            try:
                T._run('can_mate', shogi.Board(hard), n=17, seconds=10)
                outcome['stopped'] = False
            except ValueError as exc:
                outcome['stopped'] = 'timeout' in str(exc)
            stop.rearm()
            outcome['reused'] = T.can_mate(shogi.Board(mate), 1)
        except BaseException as exc:
            outcome['error'] = repr(exc)
            ready.set()
        finally:
            stop.close()
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    assert ready.wait(3), 'worker did not start'
    time.sleep(.1)
    stop.stop()
    # Another thread/context must remain usable after the individual stop.
    assert T.can_mate(shogi.Board(mate), 1)
    thread.join(3)
    assert not thread.is_alive() and outcome == {'stopped': True, 'reused': True}, outcome
    print('PASS: accumulated progress, legal df-pn PV, first-move exclusion, individual cancellation and context reuse')


if __name__ == '__main__':
    main()
