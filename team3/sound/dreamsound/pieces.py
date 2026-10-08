"""2단계 · 재료 — 1~5초짜리 짧은 소리 조각을 만든다. 배치·길이·혼합은 3·4단계 몫이다.

  조각 종류                   어디서 왔나 (1단계)                      어떻게 만드나 (synth.py, 전부 자체 합성)
  바닥(룸톤) 2개              배경 사진 수치 (밝기·암부·윤곽)            갈색 잡음 + 공명대 → 방의 공기
  오브제 두드림 3개 + 문지름  오브제 실루엣 (+ 그림 인식 재질)           모달 합성 (공명기 묶음)
  이야기 사건 3개씩           이야기 문장의 사건 낱말 (물방울·종이…)      사건 합성기 24종
  낱말 소리 2개씩             분류표에 없던 낱말 (손·글씨·가슴…)         낱말 합성기 (손 스침·펜촉·박동…)
  오브제 정체 소리 2개씩      그림 인식: 오브제가 무엇인지 (책 → 종이)    같은 사건 합성기
  그림 속 소리원 2개씩        그림 인식: 배경에 보이는 형광등·창문·시계   같은 사건 합성기

외부 음원·생성 모델 출력이 없다 → 저작권 걱정 없이 상업 이용 가능 (LICENSE_AUDIT.md).
조각마다 출처(합성 함수 · 시드)를 적어 provenance.json 에 남긴다. 같은 시드 = 같은 조각.
"""
import os

import numpy as np
from scipy.io import wavfile

from . import synth

SR = synth.SR


def save(path, y, sr=SR):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    wavfile.write(path, sr, np.asarray(y, dtype=np.float32))


def load(path):
    sr, y = wavfile.read(path)
    if y.dtype.kind in 'iu':
        y = y.astype(np.float32) / float(np.iinfo(y.dtype).max)
    y = y.astype(np.float32)
    if y.ndim > 1:
        y = y.mean(axis=1)
    return sr, y


def build(s, run_dir, max_events=6, seed=0, log=print):
    """장면 하나의 조각들 → s['pieces'] = [{role, key, file, how, seed, ...}]."""
    d = os.path.join(run_dir, 'pieces', 'scene_%02d' % s['num'])
    out = s['pieces'] = []

    def add(role, key, y, name, sd, how, why):
        p = os.path.join(d, name + '.wav')
        save(p, y)
        out.append({'role': role, 'key': key, 'src': 'procedural', 'file': os.path.relpath(p, run_dir).replace('\\', '/'),
                    'seed': sd, 'how': how, 'why': why})

    def event_pieces(k, n, tag, why):
        sd = int(synth.rng_for(s['num'], tag, k, seed).integers(0, 1 << 30))
        rng = np.random.default_rng(sd)
        for j in range(n):
            add('event', k, synth.EVENT_SYNTH[k](SR, rng), '%s_%s_%d' % (tag, k, j), sd, 'synth.ev_' + k, why)

    # 바닥 — 배경 사진
    base = int(synth.rng_for(s['num'], s['title'], seed).integers(0, 1 << 30))
    bgf = (s.get('background') or {}).get('features')
    for j in range(2):
        add('bed', 'room', synth.room_bed(bgf, seed=base + j, dur=20 if j else 12), 'bed_%d' % j, base + j,
            'synth.room_bed', '배경 사진 수치')
    # 오브제 — 실루엣(+재질)
    for i, o in enumerate(s['objects']):
        f = o['features']
        if f.get('empty'):
            continue
        sd = int(synth.rng_for(s['num'], o['name'], seed).integers(0, 1 << 30))
        why = '오브제 실루엣' + (' + 재질(%s)' % f['material'] if f.get('material') else '')
        for v in range(3):
            add('object', i, synth.modal_strike(f, variant=v, seed=sd), 'obj%d_strike%d' % (i, v), sd, 'synth.modal_strike', why)
        add('drone', i, synth.modal_drone(f, seed=sd), 'obj%d_drone' % i, sd, 'synth.modal_drone', why)
    # 이야기 사건 — 많이 나온 것부터
    have = set()
    for k, e in sorted(s['events'].items(), key=lambda kv: -kv[1]['hits'])[:max_events]:
        event_pieces(k, 3, 'evt', '이야기 문장')
        have.add(k)
    # 낱말 소리 — 분류표에 없던 낱말(손 · 글씨 · 가슴 …)이 가리키는 소리 (read.WORD_SOUNDS)
    for k, w in (s.get('words') or {}).items():
        if k not in have and k in synth.EVENT_SYNTH:
            event_pieces(k, 2, 'word', '이야기 낱말 (%s)' % ' · '.join(w['words'][:3]))
            have.add(k)
    # 그림 인식 — 오브제 정체 소리 · 배경 속 소리원 (이미 만든 사건 소리면 같이 쓴다)
    for o in s['objects']:
        k = (o.get('identity') or {}).get('event')
        if k and k not in have and k in synth.EVENT_SYNTH:
            event_pieces(k, 2, 'idt', '오브제 정체 (%s)' % o['identity']['word'])
            have.add(k)
    for x in s.get('seen') or []:
        k = x['event']
        if k not in have and k in synth.EVENT_SYNTH:
            event_pieces(k, 2, 'seen', '배경 그림 속 %s' % x['word'])
            have.add(k)
    log('  장면 %d [%s] 조각 %d개 (바닥 %d · 오브제 %d · 사건 %d)' % (
        s['num'], s['stage'], len(out), sum(m['role'] == 'bed' for m in out),
        sum(m['role'] in ('object', 'drone') for m in out), sum(m['role'] == 'event' for m in out)))


def load_all(s, run_dir, sr):
    """조각 파일 → {'bed': [..], 'object': {i: [..]}, 'drone': {i: y}, 'event': {k: [..]}} (sr 로 맞춰서)."""
    import math
    from scipy import signal
    out = {'bed': [], 'object': {}, 'drone': {}, 'event': {}}
    for m in s['pieces']:
        msr, y = load(os.path.join(run_dir, m['file']))
        if msr != sr:
            g = math.gcd(msr, sr)
            y = signal.resample_poly(y, sr // g, msr // g).astype(np.float32)
        if m['role'] == 'bed':
            out['bed'].append(y)
        elif m['role'] == 'drone':
            out['drone'][m['key']] = y
        else:
            out[m['role']].setdefault(m['key'], []).append(y)
    return out
