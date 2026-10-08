# -*- coding: utf-8 -*-
"""꿈 사운드 생성기 — 3팀 (스토리보드 + 배경 사진 + 오브제 그림 → 장면별 창발적 사운드)

  (저장소 어디서든)
  python team3/sound/generate_sound.py                 ← 장면마다 75초 · 4장면이면 5분 · 3분 안에 끝나게
  python team3/sound/generate_sound.py --mux 꿈.mp4    ← output/ 의 소리를 영상에 붙인다 (몇 초)

네 단계 (단계마다 파일 하나 — dreamsound/)
  1 읽기  read.py    ① 이야기 문장 → 소리가 날 시각   ② 그림 수치 → 음색   ③ 그림 인식 → 무슨 소리인지 (vision.py)
  2 재료  pieces.py  1~5초 짧은 소리 조각을 자체 합성
  3 진화  evolve.py  조각을 어떻게 배치·혼합할지 MAP-Elites 로 — 품질 = 듣기 좋은 정도
  4 렌더  render.py  75초 배치 → 배경 분위기에 맞춘 작곡 → 꿈의 변형 → 공간 → WAV 48kHz
  + 해설(sound_guide.html · cue_sheet.csv) · 출처(provenance.json)

결과: team3/sound/output/ 바로 아래 (깃에 안 올라간다). 새로 만들면 이전 결과는 새 것으로 바뀐다.
      만드는 동안은 output/_building/ 에 쓰고, 끝까지 성공했을 때만 갈아 끼운다 — 중간에 멈춰도 이전 결과는 남는다.
"""
import argparse
import json
import os
import re
import shutil
import sys
import time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np  # noqa: E402

from dreamsound import composition, evolve, guide, paths, pieces, provenance, read, render, timing  # noqa: E402

FINAL_SR = 48000          # 영상 표준 표본율 — 영상에 붙일 때 다시 표본화하지 않는다


def log(*a):
    print(*a, flush=True)


def parse():
    ap = argparse.ArgumentParser(description='꿈 사운드 생성기 (3팀)')
    g = ap.add_argument_group('입력')
    g.add_argument('--scenes', help='스토리보드 json (기본: team3/background/input/storyboard/ 의 가장 최근 json)')
    g.add_argument('--backgrounds', help='배경 사진 폴더 (기본: 스토리보드와 같은 폴더의 scene_NN.png)')
    g.add_argument('--objects', help='오브제 폴더 (기본: team3/object — output_objects/ 또는 dataset/ 자동)')
    g = ap.add_argument_group('생성')
    g.add_argument('--seconds', type=float, default=timing.DEFAULT_SEC, help='장면 길이(초) — 기본 75 고정')
    g.add_argument('--vision', choices=['auto', 'on', 'off'], default='auto',
                   help='1단계 ③ 그림 인식 — auto(기본): torch·transformers 가 있으면 사용 · on: 꼭 사용 · off: 안 씀')
    g.add_argument('--time-budget', type=float, default=170,
                   help='전체 목표 시간(초, 기본 170 = 3분 안). 진화가 이 안에서 끝나도록 스스로 멈춘다. 0 = 제한 없음')
    g.add_argument('--iters', type=int, default=600, help='장면당 진화 평가 상한 (시간 예산이 먼저 닿으면 거기서 멈춤)')
    g.add_argument('--workers', type=int, default=0, help='동시에 돌릴 장면 수 (기본: CPU 코어 수와 장면 수 중 작은 값)')
    g.add_argument('--max-events', type=int, default=6, help='장면당 조각으로 만들 이야기 사건 종류 수')
    g.add_argument('--seed', type=int, default=0, help='같은 시드 = 같은 조각·같은 탐색 출발점')
    g = ap.add_argument_group('출력')
    g.add_argument('--out', help='결과 폴더 (기본: team3/sound/output — 이전 결과를 새 것으로 바꾼다)')
    g.add_argument('--mp3', action='store_true', help='미리듣기용 mp3 도 만든다 (영상에 붙이는 데는 WAV 를 쓴다)')
    g.add_argument('--install', action='store_true',
                   help='scene_NN.wav 를 배경 엔진 입력 폴더(team3/background/input/storyboard/)에도 복사')
    g.add_argument('--mux', metavar='VIDEO', help='새로 만들지 않고, 결과 폴더(--run, 기본 output/)의 소리를 이 영상에 붙인다')
    g.add_argument('--run', help='--mux 에 쓸 결과 폴더 (기본 output/)')
    return ap.parse_args()


# 결과 폴더에 이 프로그램이 만드는 것들 — 갈아 끼울 때 이것만 지운다 (사용자가 넣어 둔 다른 파일은 건드리지 않음)
RESULT_FILES = ('dream_sound.wav', 'dream_sound.mp3', 'sound_guide.html', 'cue_sheet.csv', 'provenance.json',
                'report.json', 'scores.json', 'archive_maps.txt')
RESULT_RE = re.compile(r'^(scene_\d+\.(wav|mp3)|.+_with_sound\.mp4|length_eval.*)$')
OLD_RUN_RE = re.compile(r'^\d{6}_\d{6}$')          # 예전 방식의 output/<날짜_시각>/ 폴더
BUILD = '_building'


def latest_run():
    d = paths.OUTPUT_DIR
    return d if os.path.exists(os.path.join(d, 'dream_sound.wav')) else None


def replace_results(build, final):
    """build 폴더의 새 결과로 final 의 이전 결과를 바꾼다 (output/<날짜_시각>/ 옛 폴더도 정리)."""
    for n in os.listdir(final):
        p = os.path.join(final, n)
        if n == BUILD:
            continue
        if n in RESULT_FILES or RESULT_RE.match(n):
            os.remove(p)
        elif os.path.isdir(p) and (n == 'pieces' or (final == paths.OUTPUT_DIR and OLD_RUN_RE.match(n))):
            shutil.rmtree(p)
    for n in os.listdir(build):
        shutil.move(os.path.join(build, n), os.path.join(final, n))
    shutil.rmtree(build, ignore_errors=True)


def do_mux(args):
    run = os.path.abspath(args.run) if args.run else latest_run()
    if not run:
        raise SystemExit('붙일 소리가 없습니다 — 먼저 generate_sound.py 를 실행하세요')
    wav = os.path.join(run, 'dream_sound.wav')
    vd, ad = timing.media_duration(args.mux), timing.media_duration(wav)
    out = os.path.join(run, os.path.splitext(os.path.basename(args.mux))[0] + '_with_sound.mp4')
    timing.mux(args.mux, wav, out)
    log('mp4: %s (영상 %.2f초 · 소리 %.2f초%s)' % (paths.rel(out), vd, ad,
        '' if abs(vd - ad) < 0.1 else ' — ⚠ 길이가 다릅니다. 짧은 쪽에서 끝나거나 뒤가 무음이 됩니다'))


def main():
    args = parse()
    if args.mux:
        return do_mux(args)
    T0 = time.time()
    budget = args.time_budget if args.time_budget and args.time_budget > 0 else None
    final_dir = os.path.abspath(args.out or paths.OUTPUT_DIR)
    run_dir = os.path.join(final_dir, BUILD)               # 다 만들고 나서 final_dir 로 옮긴다
    shutil.rmtree(run_dir, ignore_errors=True)
    os.makedirs(run_dir, exist_ok=True)
    stamp = {}

    # ── 1 읽기 ──────────────────────────────────────────────────────────
    log('[1] 읽기 — ① 이야기 → 시각 · ② 그림 수치 → 음색 · ③ 그림 인식 → 무슨 소리')
    scenes, notes, vis = read.read(args.scenes, args.backgrounds, args.objects, args.vision, log=lambda m: log('  ' + m))
    for n in notes:
        log('  ' + n)
    for s in scenes:
        log('  장면 %d [%s] %s · 사건 %s · 법칙 %s · 오브제 %d · 분위기 정서가 %+.2f 각성 %+.2f' % (
            s['num'], s['stage'], s['title'], '/'.join(read.EVENT_NAME[k] for k in s['events']) or '없음',
            '/'.join(l['name'] for l in s['laws']) or '없음', len(s['objects']),
            s['mood']['valence'], s['mood']['arousal']))
    music = composition.plan(scenes)           # 4단계 작곡이 쓸 꿈 전체의 조성·동기 (장면들이 공유)
    stamp['1 읽기'] = time.time() - T0

    # ── 2 재료 · 3 진화 — 장면마다 별도 프로세스에서 동시에 ──────────────────────
    acts, acts_src = render.audio_acts()
    workers = args.workers or max(1, min(len(scenes), os.cpu_count() or 1))
    rounds = -(-len(scenes) // workers)
    reserve = 30                                   # 4단계 렌더·해설 몫
    limit = max(15.0, (budget - (time.time() - T0) - reserve - 3 * rounds) / rounds) if budget else None
    log('[2] 재료 · [3] 진화 — 장면 %d개를 %d개 프로세스로%s' % (
        len(scenes), workers, (' · 장면당 최대 %.0f초' % limit) if limit else ''))
    t = time.time()
    jobs = [{'scene': s, 'run_dir': run_dir, 'acts': acts, 'iters': args.iters, 'seed': args.seed,
             'max_events': args.max_events, 'time_limit': limit} for s in scenes]
    if workers > 1:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(evolve.scene_job, jobs))
    else:
        results = [evolve.scene_job(j) for j in jobs]
    for r in results:
        for m in r['logs']:
            log(m)
    chosen, picks = [], []
    for s, r in zip(scenes, results):
        s['pieces'] = r['pieces']
        (c, q, g, f, det, rank), nov = evolve.choose(r['archive'], chosen)
        chosen.append(evolve.novelty_vec(f))
        picks.append({'params': evolve.decode(g), 'genome': [round(float(x), 5) for x in g], 'quality': q,
                      'listen': det, 'features': f, 'cell': list(c), 'rank': rank, 'novelty': nov})
        log('  장면 %d: 평가 %d회 · 칸 %d/%d · 듣기 좋은 정도 %.2f (%s) · %.0f초' % (
            r['num'], r['evals'], r['cells'], evolve.BINS ** 2, q,
            ' · '.join('%s %.2f' % (evolve.LISTEN_KO[k], v) for k, v in det.items()), r['sec']))
    stamp['2 재료·3 진화'] = time.time() - t
    json.dump([{'scene': r['num'], **p, 'target_brightness': r['target'], 'evals': r['evals'], 'view': r['view']}
               for r, p in zip(results, picks)],
              open(os.path.join(run_dir, 'scores.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    open(os.path.join(run_dir, 'archive_maps.txt'), 'w', encoding='utf-8').write(
        'MAP-Elites 아카이브 (칸 값 = 듣기 좋은 정도 · 세로 = 스펙트럼 밝기 · 가로 = 초당 사건 수)\n\n' + '\n\n'.join(
            '장면 %d [%s] %s\n%s' % (s['num'], s['stage'], s['title'], r['archive_map']) for s, r in zip(scenes, results)))

    # ── 4 렌더 ──────────────────────────────────────────────────────────
    t = time.time()
    durs = [float(args.seconds)] * len(scenes)
    log('[4] 렌더 — 배치 → 작곡(으뜸음 %s · 동기 %s) → 꿈의 변형 → 공간 · 장면당 %g초 × %d = %s' % (
        music['root'], music['motif'], args.seconds, len(durs), guide.mmss(sum(durs))))
    parts, cue_scenes = [], []
    starts = np.cumsum([0] + durs[:-1])
    for s, r, p, (st, L, pre, post), s0 in zip(scenes, results, picks, timing.plan(durs), starts):
        sc = r['view']
        mats = pieces.load_all(sc, run_dir, FINAL_SR)
        cues = []
        parts.append(render.render(sc, p['params'], mats, L, FINAL_SR, args.seed, cues=cues))
        arcinfo = cues.pop() if cues and 'arc' in cues[-1] else {}
        loc = []
        for cu in cues:
            cu = dict(cu)
            cu['t'] = round(cu['t'] - pre, 3)
            if cu['layer'] in ('bed', 'drone', 'space'):
                cu['t'], cu['dur'] = 0.0, args.seconds
            if -0.5 <= cu['t'] <= args.seconds + 0.5:
                if cu.get('sentence_u') is not None:   # 근거 문장 위치는 '겹침 포함 길이' 기준 → 장면 기준으로
                    cu['sentence_u'] = round(max(0.0, min(1.0, (cu['sentence_u'] * L - pre) / args.seconds)), 3)
                loc.append(cu)
        log('  장면 %d [%s] %s 선법 · 소리 %d개' % (s['num'], s['stage'], composition.MODE_KO[s['music']['mode']], len(loc)))
        cue_scenes.append({'num': s['num'], 'stage': s['stage'], 'title': s['title'], 'D': args.seconds,
                           'start': float(s0), 'cues': loc, 'arc': arcinfo.get('arc'), 'bg': sc['bg'],
                           'bg_path': (s.get('background') or {}).get('path'), 'emotion': s['emotion'], 'mood': s['mood'],
                           'law_src': sc['law_src'], 'story_sents': sc['story_sents'],
                           'objects_info': [{'name': o['name'], 'name_en': o.get('name_en'), 'features': o['features'],
                                             'identity': o.get('identity'), 'caption': o.get('caption')}
                                            for o in s['objects']],
                           'evals': r['evals'], 'quality': p['quality'], 'listen': p['listen'],
                           'vision': s.get('vision'),
                           'object_materials': {o['name']: o.get('material_rank') for o in s['objects']}})
    full = timing.assemble(parts, durs, FINAL_SR)
    files = []
    for s, s0, D in zip(scenes, starts, durs):
        a, b = int(round(s0 * FINAL_SR)), int(round((s0 + D) * FINAL_SR))
        w = os.path.join(run_dir, 'scene_%02d.wav' % s['num'])
        timing.write_wav(w, full[a:b], FINAL_SR)
        files.append(w)
    fw = os.path.join(run_dir, 'dream_sound.wav')
    timing.write_wav(fw, full, FINAL_SR)
    if args.mp3:
        for w in files + [fw]:
            timing.to_mp3(w, w[:-4] + '.mp3')
    if args.install:
        for w in files:
            shutil.copy2(w, os.path.join(paths.STORYBOARD_DIR, os.path.basename(w)))
        log('  배경 엔진 입력에 복사: %s/scene_NN.wav' % paths.rel(paths.STORYBOARD_DIR))
    stamp['4 렌더'] = time.time() - t

    # ── 해설 · 출처 ──────────────────────────────────────────────────────
    t = time.time()
    prov = provenance.build(run_dir, scenes, vis, notes)
    guide.write_csv(os.path.join(run_dir, 'cue_sheet.csv'), cue_scenes)
    elapsed = time.time() - T0
    guide.write_html(os.path.join(run_dir, 'sound_guide.html'), cue_scenes,
                     {'storyboard': notes[0], 'elapsed': '%.0f' % elapsed, 'verdict': prov['verdict'], 'vision': vis})
    stamp['해설·출처'] = time.time() - t
    elapsed = time.time() - T0
    report = {'created': time.strftime('%Y-%m-%d %H:%M:%S'), 'run_dir': paths.rel(final_dir), 'notes': notes,
              'vision': vis, 'acts_prior': acts_src, 'workers': workers, 'music_plan': music,
              'seconds_per_scene': args.seconds, 'total_sec': round(len(full) / FINAL_SR, 4), 'sample_rate': FINAL_SR,
              'elapsed_sec': round(elapsed, 1), 'time_budget_sec': budget,
              'stage_sec': {k: round(v, 1) for k, v in stamp.items()}, 'verdict': prov['verdict'], 'args': vars(args),
              'scenes': [{'num': s['num'], 'stage': s['stage'], 'title': s['title'], 'emotion': s['emotion'],
                          'mood': s['mood'], 'events': s['events'], 'laws': s['laws'], 'background': s['background'],
                          'vision': s.get('vision'), 'seen': s.get('seen'),
                          'objects': [{k: o.get(k) for k in ('name', 'name_en', 'positions', 'features', 'identity', 'caption')}
                                      | {'path': paths.rel(o['path'])} for o in s['objects']],
                          'music': s['music'], 'chosen': {**p, 'params': {k: round(v, 3) for k, v in p['params'].items()}},
                          'archive': {'cells': r['cells'], 'of': evolve.BINS ** 2, 'evals': r['evals'],
                                      'history_best': r['hist'][::10]}}
                         for s, r, p in zip(scenes, results, picks)]}
    json.dump(report, open(os.path.join(run_dir, 'report.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1,
              default=str)
    replace_results(run_dir, final_dir)
    log('\n완료 %.0f초%s — %s (이전 결과는 새 것으로 바뀜)' % (
        elapsed, ('' if not budget or elapsed <= 180 else ' (⚠ 3분 초과)'), paths.rel(final_dir)))
    log('  단계별: ' + ' · '.join('%s %.0f초' % (k, v) for k, v in stamp.items()))
    log('  dream_sound.wav · scene_01~%02d.wav (48kHz) · sound_guide.html(해설) · cue_sheet.csv · provenance.json(출처)'
        % len(scenes))
    log('  저작권: ' + prov['verdict'][:60] + '…')
    log('  영상에 붙이기: python team3/sound/generate_sound.py --mux <영상.mp4>')


if __name__ == '__main__':
    main()
