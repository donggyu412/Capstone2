# -*- coding: utf-8 -*-
"""길이 불변성 실험 — 같은 악보를 여러 길이로 렌더해 '성격이 유지되는가'를 잰다 (논문 실험용).

  python team3/sound/eval_lengths.py                       ← output/ 의 결과로 50 · 75 · 90초
  python team3/sound/eval_lengths.py --lengths 30 60 120

비교 대상(기준선): 75초로 한 번 만든 소리를 다른 길이로 '늘이고 줄이기'(재생 속도 변경 — 가장 흔한 맞추기 방식).
  · 우리 방식  render(악보, D)    → 초당 사건 수 · 밝기 · 평탄도가 길이와 무관해야 한다
  · 기준선     늘이기/줄이기      → 길이를 맞추면 음높이(밝기)와 사건 밀도가 함께 변한다
결과: output/length_eval.json · 표를 화면에 출력.
"""
import argparse
import json
import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402

from dreamsound import evolve, paths, pieces, render  # noqa: E402

SR = 22050
KEYS = ('centroid', 'onsets', 'flatness', 'dynamics', 'low')


def stretch(y, D):
    """기준선 — 길이 D 가 되도록 재생 속도를 바꾼다(테이프 늘이기)."""
    n = int(round(D * SR))
    return np.interp(np.linspace(0, len(y) - 1, n), np.arange(len(y)), y).astype(np.float32)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('run', nargs='?', default=None, help='결과 폴더 (기본 team3/sound/output)')
    ap.add_argument('--lengths', nargs='+', type=float, default=[50, 75, 90])
    ap.add_argument('--ref', type=float, default=75.0)
    a = ap.parse_args()
    run = os.path.abspath(a.run or paths.OUTPUT_DIR)
    scores = json.load(open(os.path.join(run, 'scores.json'), encoding='utf-8'))
    out = []
    for s in scores:
        sc = s['view']
        mats = pieces.load_all(sc, run, SR)
        ref = render.render(sc, s['params'], mats, a.ref, SR).mean(axis=1)
        rows = {}
        for D in a.lengths:
            ours = evolve.features(render.render(sc, s['params'], mats, D, SR).mean(axis=1), SR)
            base = evolve.features(stretch(ref, D), SR)
            rows[str(D)] = {'ours': {k: ours[k] for k in KEYS}, 'stretch': {k: base[k] for k in KEYS}}

        def spread(kind, k):
            v = [rows[str(D)][kind][k] for D in a.lengths]
            return round(float(np.std(v) / (abs(np.mean(v)) + 1e-9)), 4)    # 변동 계수 — 작을수록 길이에 무관
        cv = {kind: {k: spread(kind, k) for k in KEYS} for kind in ('ours', 'stretch')}
        out.append({'scene': sc['num'], 'stage': sc['stage'], 'by_length': rows, 'cv': cv})
        print('장면 %d [%s] — 변동 계수(길이 %s초 사이, 작을수록 성격 유지)' % (sc['num'], sc['stage'], a.lengths))
        print('   %-10s %8s %8s' % ('특징', '우리', '늘이기'))
        for k in KEYS:
            print('   %-10s %8.3f %8.3f' % (k, cv['ours'][k], cv['stretch'][k]))
    json.dump(out, open(os.path.join(run, 'length_eval.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('\n저장: length_eval.json')


if __name__ == '__main__':
    main()
