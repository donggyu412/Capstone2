"""사운드 해설 자료 — '장면마다 어떤 소리가 몇 초에, 이야기의 어느 부분 때문에 나오는가'.

  cue_sheet.csv      소리 하나 = 한 줄 (엑셀에서 바로 열림 · UTF-8 BOM)
  sound_guide.html   장면별 타임라인 그림 + '이야기 문장 → 소리' 표 + 소리를 정한 이미지·감정·법칙 + 저작권 판정
렌더할 때 엔진이 실제로 놓은 소리를 그대로 적은 것이라(render.render 의 cues), 설명과 소리가 어긋나지 않는다.
"""
import base64
import csv
import html
import io
import os

from .read import EVENT_NAME, WORD_NAME

LAYER_KO = {'bed': '바닥(룸톤)', 'drone': '배경 지속음', 'space': '공간(잔향)', 'object': '오브제', 'event': '사건',
            'dream': '꿈의 변형', 'music': '음악(화성·동기)', 'silence': '정적', 'seen': '그림 인식 소리', 'word': '낱말 소리'}
DREAM_KO = {   # 꿈의 변형 4가지 — dreamfx.py
    '이질적 침입': '장면 분위기와 맞지 않는 소리가 갑자기 지나간다 (공포 장면의 오르골·새소리·풍경 소리)',
    '음색 치환': '이야기에 없는 생물의 몸짓을 장면 재질의 음색으로 연주한다 (녹슨 철판으로 우는 새)',
    '변신': '한 소리가 몇 초에 걸쳐 다른 오브제의 소리로 바뀐다 (배경 화면의 점진적 모핑과 같은 원리)',
    '데자뷔': '장면 앞에서 들린 소리가 뒤에서 느리게·거꾸로·멀리서 되돌아온다',
}
LAW_KO = {'reverse': '원인보다 먼저 오는 소리', 'accel': '빨라지는 간격', 'space_link': '소리와 공간의 연동',
          'swallow': '삼켜지는 소리', 'uneven': '매번 다른 크기', 'sink': '낮아지는 소리'}
STAGE_KO = {'기': '기 — 차오름', '승': '승 — 머묾', '전': '전 — 정점', '결': '결 — 사라짐'}
COLORS = ['#4C78A8', '#F58518', '#54A24B', '#E45756', '#72B7B2', '#B279A2', '#EECA3B', '#9D755D', '#FF9DA6', '#79706E',
          '#5778a4', '#e49444']


def mmss(t):
    t = max(0.0, t)
    return '%d:%04.1f' % (int(t // 60), t % 60)


def _thumb(path, w=360):
    if not path or not os.path.exists(path):
        return None
    try:
        from PIL import Image
        im = Image.open(path).convert('RGB')
        im.thumbnail((w, w))
        b = io.BytesIO()
        im.save(b, 'JPEG', quality=72)
        return 'data:image/jpeg;base64,' + base64.b64encode(b.getvalue()).decode()
    except Exception:
        return None


def write_csv(path, scenes):
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['장면', '막', '장면 기준 시각', '전체 기준 시각', '길이(초)', '층', '소리', '이야기 근거(문장)',
                    '근거 문장 위치(장면 기준)', '적용된 꿈의 법칙', '이유(꿈의 변형 등)', '소리 출처'])
        for sc in scenes:
            for c in sc['cues']:
                w.writerow([sc['num'], sc['stage'], mmss(c['t']), mmss(sc['start'] + c['t']), '%.2f' % c['dur'],
                            LAYER_KO.get(c['layer'], c['layer']), c['sound'], c['sentence'] or '(장면 전반 — 특정 문장 없음)',
                            mmss(c['sentence_u'] * sc['D']) if c.get('sentence_u') is not None else '',
                            c['law'] or '', c.get('reason') or '', c['src'] or ''])


def _lanes(cues):
    order = []
    for c in cues:
        key = (c['layer'], c['key'])
        if key not in order:
            order.append(key)
    rank = {'music': -1, 'bed': 0, 'drone': 1, 'space': 2, 'object': 3, 'event': 4, 'word': 4.2, 'seen': 4.5, 'dream': 5, 'silence': 6}
    return sorted(order, key=lambda k: (rank.get(k[0], 9), order.index(k)))


def _svg(sc):
    D, cues = sc['D'], sc['cues']
    lanes = _lanes(cues)
    W, L, R, top, lh = 1000, 150, 12, 46, 20
    H = top + lh * len(lanes) + 28
    x = lambda t: L + (W - L - R) * max(0.0, min(D, t)) / D
    o = ['<svg viewBox="0 0 %d %d" class="tl" role="img" aria-label="장면 %d 소리 타임라인">' % (W, H, sc['num'])]
    # 기승전결 음량 곡선
    arc = sc.get('arc') or []
    if arc:
        pts = ' '.join('%.1f,%.1f' % (x(D * i / (len(arc) - 1)), top - 8 - 26 * v) for i, v in enumerate(arc))
        o.append('<polyline points="%s" class="arc"/>' % pts)
        o.append('<text x="%d" y="%d" class="lbl">음량 곡선</text>' % (L - 6, top - 14))
    # 정적 띠
    for c in cues:
        if c['layer'] == 'silence':
            o.append('<rect x="%.1f" y="%d" width="%.1f" height="%d" class="sil"><title>%s %s — %s</title></rect>' % (
                x(c['t']), top - 4, x(c['t'] + c['dur']) - x(c['t']), lh * len(lanes) + 4, mmss(c['t']),
                html.escape(c['sound']), html.escape(c['sentence'] or '')))
    for i, (layer, key) in enumerate(lanes):
        y = top + i * lh
        name = LAYER_KO[layer] if layer in ('bed', 'drone', 'space', 'silence') else (
            EVENT_NAME.get(key, key) if layer == 'event' else ('✎ ' + WORD_NAME.get(key, key) if layer == 'word' else
                                                              '👁 ' + EVENT_NAME.get(key, key) if layer == 'seen' else
                                                              '★ ' + str(key) if layer == 'dream' else
                                                               ('♪ ' + str(key) if layer == 'music' else str(key))))
        if layer == 'silence':
            continue
        o.append('<text x="%d" y="%d" class="lbl">%s</text>' % (L - 6, y + 14, html.escape(name[:14])))
        o.append('<line x1="%d" x2="%d" y1="%d" y2="%d" class="grid"/>' % (L, W - R, y + 10, y + 10))
        col = COLORS[i % len(COLORS)]
        for c in cues:
            if (c['layer'], c['key']) != (layer, key):
                continue
            tip = '%s · %s%s%s%s' % (mmss(c['t']), c['sound'], (' — ' + c['sentence']) if c['sentence'] else '',
                                     (' [' + c['law'] + ']') if c['law'] else '', (' · ' + c['reason']) if c.get('reason') else '')
            if c['dur'] > 3 or layer in ('bed', 'drone', 'space', 'music'):
                o.append('<rect x="%.1f" y="%d" width="%.1f" height="12" rx="3" fill="%s" opacity=".45"><title>%s</title></rect>' % (
                    x(c['t']), y + 4, max(2, x(c['t'] + c['dur']) - x(c['t'])), col, html.escape(tip)))
            else:
                o.append('<rect x="%.1f" y="%d" width="3" height="14" fill="%s"%s><title>%s</title></rect>' % (
                    x(c['t']), y + 3, col, ' class="law"' if c['law'] else '', html.escape(tip)))
    # 시간 눈금
    yb = top + lh * len(lanes) + 6
    step = 15 if D > 40 else 5
    t = 0
    while t <= D + 1e-6:
        o.append('<line x1="%.1f" x2="%.1f" y1="%d" y2="%d" class="tick"/>' % (x(t), x(t), top - 4, yb))
        o.append('<text x="%.1f" y="%d" class="tk">%s</text>' % (x(t), yb + 14, mmss(sc['start'] + t)))
        t += step
    o.append('</svg>')
    return '\n'.join(o)


def _story_table(sc):
    """이야기 문장(순서대로) → 그 문장 때문에 놓인 소리."""
    D = sc['D']
    by_sent = {}
    loose = {}
    for c in sc['cues']:
        if c['layer'] in ('bed', 'drone', 'space'):
            continue
        if c['sentence'] and c.get('sentence_u') is not None:
            by_sent.setdefault(c['sentence'], []).append(c)
        else:
            loose.setdefault(c['sound'], []).append(c)
    rows = []
    for u, s in sc.get('story_sents') or []:
        cs = by_sent.get(s, [])
        if cs:
            grp, laws = {}, {}
            for c in cs:
                grp.setdefault(c['sound'], []).append(c['t'])
                for lw in (c['law'] or '').split(' · '):
                    if lw:
                        laws.setdefault(c['sound'], {}).setdefault(lw, 0)
                        laws[c['sound']][lw] += 1
            items = ''.join('<li><b>%s</b> · %d회 · %s%s</li>' % (
                html.escape(k), len(v), ', '.join(mmss(sc['start'] + t) for t in sorted(v)[:8]) + (' …' if len(v) > 8 else ''),
                ''.join(' <span class="law">%s %d회</span>' % (html.escape(lw), n) for lw, n in laws.get(k, {}).items()))
                for k, v in grp.items())
            rows.append('<tr><td class="t">%s</td><td>%s</td><td><ul>%s</ul></td></tr>' % (
                mmss(sc['start'] + u * D), html.escape(s), items))
        else:
            rows.append('<tr class="dim"><td class="t">%s</td><td>%s</td><td>—</td></tr>' % (
                mmss(sc['start'] + u * D), html.escape(s)))
    if loose:
        items = ''.join('<li><b>%s</b> · %d회 (글 속 위치와 떨어진 곳에 흩어 놓은 같은 종류의 소리 — 장면 분위기)</li>' % (
            html.escape(k), len(v)) for k, v in loose.items())
        rows.append('<tr><td class="t">전체</td><td><i>특정 문장 없이 장면 전반</i></td><td><ul>%s</ul></td></tr>' % items)
    return '<table class="story"><tr><th>문장 자리(전체 시각)</th><th>이야기 문장</th><th>그 문장 때문에 나는 소리 (시각)</th></tr>%s</table>' % ''.join(rows)


def _why_list(sc):
    li = []
    for c in sc['cues']:
        if c['layer'] in ('bed', 'drone', 'space'):
            li.append('<li><b>%s</b> — %s%s<br><span class="muted">%s</span></li>' % (
                LAYER_KO[c['layer']], html.escape(c['sound']), (' <span class="law">%s</span>' % html.escape(c['law'])) if c['law'] else '',
                html.escape(c['sentence'] or '')))
    bg = sc.get('bg') or {}
    if bg:
        li.append('<li><b>배경 사진 수치</b> — 밝기 %.2f · 대비 %.2f · 암부 %.0f%% · 윤곽 밀도 %.2f · 깊이 %.2f<br>'
                  '<span class="muted">밝을수록 밝은 소리, 대비가 클수록 큰 다이내믹스, 어두울수록 저역, 윤곽이 촘촘할수록 촘촘한 사건, '
                  '깊은 구도일수록 긴 잔향 (교차감각 대응 — PAPERS.md §2)</span></li>' % (
                      bg.get('luma', 0), bg.get('contrast', 0), 100 * bg.get('dark', 0), bg.get('edges', 0), bg.get('depth', 0)))
    v = sc.get('vision') or {}
    if v.get('place') or v.get('sources') or v.get('depth'):
        bits = []
        if v.get('place'):
            bits.append('장소 ' + ' · '.join('%s %.0f%%' % (html.escape(ko), 100 * p) for _, ko, p in v['place'][:3]))
        if v.get('depth'):
            bits.append('깊이 %.2f (밝기로 어림했던 값 %.2f)' % (v['depth']['depth'], bg.get('depth_luma', bg.get('depth', 0))))
        if v.get('bg_materials'):
            bits.append('보이는 재질 ' + ' · '.join('%s %.0f%%' % (html.escape(ko), 100 * p) for _, ko, p in v['bg_materials'][:2]))
        if v.get('sources'):
            bits.append('소리 낼 물체 ' + ' · '.join('%s→%s(%s)' % (
                html.escape(x['word']), html.escape(EVENT_NAME.get(x['event'], x['event'])),
                '왼쪽' if x['x'] < -0.33 else ('오른쪽' if x['x'] > 0.33 else '가운데')) for x in v['sources']))
        li.append('<li><b>👁 그림 인식</b> — %s<br><span class="muted">장소 → 잔향의 출발점 · 깊이 → 잔향 길이와 소리원 거리 · '
                  '보이는 재질 → 음색 치환의 재질 · 소리 낼 물체 → 그 자리(좌우)에서 낮게 나는 소리 (SigLIP 2 · Florence-2 · '
                  'Depth Anything V2-S — 소리는 만들지 않고 값만 정함)</span>%s</li>' % (
                      ' · '.join(bits), ('<br><span class="muted">그림 설명: "%s"</span>' % html.escape(v['caption'][:260]))
                      if v.get('caption') else ''))
    e = sc['emotion']
    li.append('<li><b>감정</b> — %s (세기 %.2f) → 정서가 %+.2f · 각성 %+.2f</li>' % (
        html.escape(e['label']), e['intensity'], e['valence'], e['arousal']))
    md = sc.get('mood')
    if md:
        li.append('<li><b>♪ 작곡의 분위기</b> — 정서가 %+.2f · 각성 %+.2f<br><span class="muted">%s</span></li>' % (
            md['valence'], md['arousal'], html.escape(md['src'])))
    if sc.get('listen'):
        from .evolve import LISTEN_KO
        li.append('<li><b>듣기 좋은 정도 %.2f</b> (진화 %d회 중 최고) — %s</li>' % (
            sc.get('quality', 0), sc.get('evals', 0),
            ' · '.join('%s %.2f' % (LISTEN_KO[k], v) for k, v in sc['listen'].items())))
    for k, src in (sc.get('law_src') or {}).items():
        li.append('<li><b>꿈의 법칙: %s</b> — <span class="muted">"%s"</span></li>' % (LAW_KO.get(k, k), html.escape(src)))
    for o in sc.get('objects_info') or []:
        f = o['features']
        mr = (sc.get('object_materials') or {}).get(o['name'])
        mat = (' · 👁 재질 %s' % ' / '.join('%s %.0f%%' % (html.escape(ko), 100 * p) for _, ko, p in mr)) if mr else ''
        idt = o.get('identity')
        if idt:
            mat += ' · 👁 정체 소리: %s ← %s' % (html.escape(EVENT_NAME.get(idt['event'], idt['event'])), html.escape(idt['src']))
        li.append('<li><b>오브제: %s</b> (%s) — 면적 %.2f · 밝기 %.2f · 각짐 %.2f · 대칭 %.2f%s → 모달 합성 음색</li>' % (
            html.escape(o['name']), html.escape(o.get('name_en') or ''), f.get('area', 0), f.get('luma', 0),
            f.get('angularity', 0), f.get('symmetry', 0), mat))
    return '<ul class="why">%s</ul>' % ''.join(li)


CSS = '''
:root{--bg:#fbfaf7;--fg:#1d1d1f;--muted:#6b6b70;--line:#e3e1db;--card:#fff;--accent:#7a4cc2;--sil:rgba(120,120,140,.14)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#17171a;--fg:#ececf0;--muted:#a0a0aa;--line:#33333a;--card:#1f1f24;--accent:#b79cff;--sil:rgba(200,200,220,.10)}}
body{background:var(--bg);color:var(--fg);font:15px/1.6 -apple-system,"Apple SD Gothic Neo","Malgun Gothic",sans-serif;margin:0;padding:24px 16px}
main{max-width:1080px;margin:auto} h1{font-size:24px;margin:0 0 4px} h2{font-size:19px;margin:0}
.muted{color:var(--muted)} .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px;margin:18px 0}
.head{display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap} .head img{width:220px;border-radius:8px}
.tl{width:100%;height:auto;margin-top:10px} .tl .lbl{font-size:11px;fill:var(--muted);text-anchor:end}
.tl .tk{font-size:10px;fill:var(--muted);text-anchor:middle} .tl .grid{stroke:var(--line)} .tl .tick{stroke:var(--line);stroke-dasharray:2 3}
.tl .arc{fill:none;stroke:var(--accent);stroke-width:2} .tl .sil{fill:var(--sil)} .tl .law{stroke:var(--fg);stroke-width:.8}
table{border-collapse:collapse;width:100%;font-size:13.5px} td,th{border-top:1px solid var(--line);padding:6px 8px;vertical-align:top;text-align:left}
td.t{white-space:nowrap;color:var(--muted);width:64px} tr.dim td{color:var(--muted);opacity:.65} ul{margin:0;padding-left:18px}
.law{display:inline-block;font-size:11.5px;border:1px solid var(--accent);color:var(--accent);border-radius:9px;padding:0 6px}
.verdict{border-left:4px solid var(--accent);padding:8px 12px} details{margin-top:10px} summary{cursor:pointer;color:var(--accent)}
.why li{margin-bottom:4px} @media (max-width:640px){.head img{width:100%}}
'''


def write_html(path, scenes, meta):
    parts = ['<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
             '<title>꿈 사운드 해설</title><style>%s</style></head><body><main>' % CSS]
    parts.append('<h1>꿈 사운드 해설</h1><p class="muted">%s · 장면 %d개 × %g초 = %s · 생성 %s초 · 소리 전부 자체 합성</p>' % (
        html.escape(meta['storyboard']), len(scenes), scenes[0]['D'] if scenes else 0, mmss(sum(s['D'] for s in scenes)),
        meta['elapsed']))
    parts.append('<div class="card"><b>만드는 과정</b><ol>'
                 '<li><b>읽기</b> — 이야기 문장이 소리가 날 <i>시각</i>을, 그림의 수치(밝기·실루엣)가 <i>음색</i>을, '
                 '그림 인식이 <i>무슨 소리</i>인지(배경에 보이는 물체 · 오브제의 정체)를 정합니다.</li>'
                 '<li><b>재료</b> — 그 소리들을 1~5초 조각으로 새로 합성합니다(녹음·외부 음원 없음).</li>'
                 '<li><b>진화</b> — 조각의 배치·혼합을 여러 번 바꿔 들어 보고 가장 듣기 좋은 구성을 고릅니다'
                 '(잡음 적음 · 날카롭지 않음 · 탁하지 않음 · 떨림 없음 · 붐비지 않음 · 층 균형 · 사건이 들림 · 그림 부합).</li>'
                 '<li><b>렌더</b> — 고른 구성으로 75초를 놓고, 배경 분위기에 맞춘 음악과 꿈의 변형을 얹습니다.</li></ol></div>')
    vis = meta.get('vision')
    parts.append('<p class="muted">그림 인식: %s</p>' % (
        ' · '.join('%s (%s)' % (html.escape(m['id']), html.escape(m['license'])) for m in vis['models'])
        if vis else '사용 안 함 — 그림의 모양·밝기 수치만 사용'))
    parts.append('<div class="card verdict"><b>저작권 · 상업 이용</b><br>%s<br><span class="muted">근거: provenance.json · '
                 'team3/sound/LICENSE_AUDIT.md</span></div>' % html.escape(meta['verdict']))
    parts.append('<div class="card"><b>읽는 법</b><ul><li>타임라인의 막대 하나 = 소리 하나. 마우스를 올리면 시각·소리·근거 문장이 보입니다.</li>'
                 '<li>테두리가 진한 막대 = 꿈의 법칙(빨라짐·삼켜짐·먼저 옴·매번 다른 크기·낮아짐)이 걸린 소리.</li>'
                 '<li>회색 띠 = 이야기의 정적 문장 때문에 소리를 비운 구간. 보라색 선 = 기승전결 음량 곡선.</li>'
                 '<li>사건 소리는 근거 문장이 이야기의 몇 %% 지점에 있는지를 장면 시간에 옮겨 그 둘레에 놓습니다(문장 위치 ±6초 안이면 "그 문장 때문").</li>'
                 '<li>시각은 전체 사운드 기준(장면 시작 + 장면 안 시각). 전체 목록은 cue_sheet.csv.</li>'
                 '<li><b>✎ 낱말 소리</b> — 사건 분류표에 없는 낱말도 그 낱말이 가리키는 소리로 냅니다(손 → 손 스침, 글씨 → 펜촉 긁힘, '
                 '가슴 → 박동, 가죽끈 → 천 스침). 그 낱말이 나오는 문장 자리에서 납니다.</li>'
                 '<li><b>👁 그림 인식 소리</b> — 배경 그림에 보이는 소리 낼 물체(형광등·창문·시계…)는 그림 속 좌우 위치·거리대로, '
                 '오브제는 그것이 무엇인지(책 → 종이 넘김)에 맞는 소리가 그 오브제가 나오는 문장 자리에서 납니다.</li>'
                 '<li><b>♪ 음악</b> — 배경 분위기(밝기·색온도·채도 + 이야기 감정)가 고른 선법의 화성 패드가 이야기 문장 경계에서 화음을 바꾸고, 꿈 전체를 관통하는 5음 동기가 '
                 '첫 오브제가 나오는 자리에서 막마다 모습을 바꿔(원형 → 반복 → 뒤집기 → 늘이기) 울립니다. 효과음과 룸톤은 지금 화음에 맞춘 '
                 '공명기를 지나 화음으로 울립니다.</li>'
                 '<li><b>★ 꿈의 변형</b> — 효과음을 그대로 들려주지 않고 꿈처럼 비튼 자리입니다:<ul>%s</ul></li></ul></div>' % ''.join(
                     '<li><b>%s</b> — %s</li>' % (html.escape(k), html.escape(v)) for k, v in DREAM_KO.items()))
    for sc in scenes:
        th = _thumb(sc.get('bg_path'))
        n_ev = sum(1 for c in sc['cues'] if c['layer'] in ('event', 'object'))
        parts.append('<section class="card"><div class="head">%s<div><h2>장면 %d · %s · %s</h2>'
                     '<p class="muted">%s – %s · 소리 %d개 놓임 · 진화 %d회 · 듣기 좋은 정도 %.2f</p>%s</div></div>' % (
                         ('<img src="%s" alt="장면 %d 배경">' % (th, sc['num'])) if th else '', sc['num'],
                         html.escape(STAGE_KO.get(sc['stage'], sc['stage'])), html.escape(sc['title']),
                         mmss(sc['start']), mmss(sc['start'] + sc['D']), n_ev, sc.get('evals', 0), sc.get('quality', 0),
                         _why_list(sc)))
        parts.append(_svg(sc))
        parts.append('<h3>이야기 → 소리</h3>' + _story_table(sc))
        mus = [c for c in sorted(sc['cues'], key=lambda c: c['t']) if c['layer'] == 'music']
        if mus:
            parts.append('<h3>♪ 음악 — 화성과 동기</h3><table class="story"><tr><th>시각</th><th>층</th>'
                         '<th>들리는 것</th><th>이유</th><th>이야기 문장</th></tr>%s</table>' % ''.join(
                             '<tr><td class="t">%s</td><td><b>%s</b></td><td>%s</td><td>%s</td><td>%s</td></tr>' % (
                                 mmss(sc['start'] + c['t']), html.escape(str(c['key'])), html.escape(c['sound']),
                                 html.escape(c.get('reason') or ''), html.escape(c['sentence'] or '—')) for c in mus))
        dream = [c for c in sorted(sc['cues'], key=lambda c: c['t']) if c['layer'] == 'dream']
        if dream:
            parts.append('<h3>★ 꿈의 변형 — 효과음을 그대로 두지 않은 자리</h3><table class="story"><tr><th>시각</th><th>변형</th>'
                         '<th>들리는 것</th><th>이유</th><th>이야기 문장</th></tr>%s</table>' % ''.join(
                             '<tr><td class="t">%s</td><td><b>%s</b></td><td>%s</td><td>%s</td><td>%s</td></tr>' % (
                                 mmss(sc['start'] + c['t']), html.escape(str(c['key'])), html.escape(c['sound']),
                                 html.escape(c.get('reason') or ''), html.escape(c['sentence'] or '—')) for c in dream))
        rows = ''.join('<tr><td class="t">%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (
            mmss(sc['start'] + c['t']), html.escape(LAYER_KO.get(c['layer'], c['layer'])), html.escape(c['sound']),
            html.escape(c['sentence'] or '—'), html.escape(c['law'] or c.get('reason') or '')) for c in sorted(sc['cues'], key=lambda c: c['t']))
        parts.append('<details><summary>이 장면의 소리 전체 목록 (%d줄)</summary><table><tr><th>시각</th><th>층</th><th>소리</th>'
                     '<th>근거 문장</th><th>법칙·이유</th></tr>%s</table></details></section>' % (len(sc['cues']), rows))
    parts.append('</main></body></html>')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(parts))
