# -*- coding: utf-8 -*-
"""참조 DB 갤러리 — 네 작가 DB 에 무엇이 들어갔고 무엇이 빠졌는지 한 페이지로 본다 (2026-09-27)

  python db/build_gallery.py      → db/db_gallery.html (더블클릭으로 연다 · 서버 불필요)

왜 만들었나:
  예전엔 폴더와 밀착 인화(_contact_*.jpg)로 봤다. 아피찻퐁 폴더에는 실제로 쓴 51장과 뺀 117장이
  표시 없이 섞여 있었고, 밀착 인화는 파일명이 잘리고 제외 이유·통계가 없었다.
  이 페이지는 작가마다 ① 쓴 것/뺀 것과 뺀 이유 ② 작가 평균 지표 ③ 구도 지도를 함께 보여준다.
※ 로컬 전용 파일이다. 이미지는 작가 저작물이라 외부에 올리지 않는다.
"""
import sys
sys.dont_write_bytecode = True   # 도구끼리 import 해도 __pycache__ 가 쌓이지 않게 (09-27 폴더 정리)
import os, sys, json, html

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from build_apichatpong_db import CURATED, KEYS, KEY_DESC
from build_artist_db import ARTISTS, EXCLUDE, excluded

OUT = os.path.join(HERE, 'db_gallery.html')

# 제외 이유 — build_artist_db.EXCLUDE 의 주석과 같은 내용
REASON = [
    ('digalakis', 'ephemera__', '글자가 박힌 매거진·책 표지'),
    ('digalakis', 'in-praise-of-shadows__', '성당 실내·촛불·인물 — 배경 풍경이 아님'),
    ('digalakis', '', '유튜브 썸네일(제목 글자·재생바)'),
    ('fontana', 'dallalto_', '도시·인파 항공사진 — 사람·사물이 주인공'),
    ('fontana', 'paesaggi_18_', '드로잉에 가까움'),
    ('fontana', 'paesaggi_44_', 'paesaggi_12 와 중복'),
]


def reason(artist, name):
    for a, pre, why in REASON:
        if a == artist and name.startswith(pre):
            return why
    return '제외'


def heat(grid):
    """12x8 구도 지도 → 칸 색. 1.0 = 평균, 밝을수록 그 작가가 빛을 두는 자리."""
    mx = max(max(r) for r in grid) or 1
    cells = ''.join('<i style="background:rgba(232,214,170,%.2f)"></i>' % (v / mx) for r in grid for v in r)
    return '<div class="heat" style="grid-template-columns:repeat(%d,1fr)">%s</div>' % (len(grid[0]), cells)


def stats_row(label, d):
    return '<tr><th>%s</th>%s</tr>' % (html.escape(label), ''.join('<td>%.3f</td>' % d[k] for k in KEYS))


def card(src, name, used, why=''):
    cls = 'used' if used else 'ex'
    tag = '' if used else '<b>%s</b>' % html.escape(why)
    return ('<figure class="%s"><img loading="lazy" src="%s"><figcaption>%s%s</figcaption></figure>'
            % (cls, html.escape(src), html.escape(name), tag))


def main():
    ap = json.load(open(os.path.join(HERE, 'apichatpong_db.json'), encoding='utf-8'))
    ar = json.load(open(os.path.join(HERE, 'artist_db.json'), encoding='utf-8'))['작가']
    head = '<tr><th></th>%s</tr>' % ''.join('<th title="%s">%s</th>' % (html.escape(KEY_DESC[k]), k) for k in KEYS)

    # 비교표 — 네 작가를 한눈에
    table = '<table>' + head + stats_row('아피찻퐁 (51)', ap['_전체평균'])
    for k, v in ar.items():
        table += stats_row('%s (%d)' % (v['이름'].split(' (')[0], v['표본수']), v['평균'])
    table += '</table>'

    sections = []
    # 아피찻퐁 — 막별 구도 지도 4개 + 쓴 51 / 뺀 나머지
    d = os.path.join(HERE, 'stills', 'apichatpong')
    names = sorted(n for n in os.listdir(d) if n.lower().endswith(('.jpg', '.png')))
    want = set(CURATED)
    used = [n for n in names if n.split('_', 1)[-1] in want]
    ex = [n for n in names if n not in used]
    maps = ''.join('<div><small>%s막</small>%s</div>' % (a, heat(ap['막'][a]['구도지도'])) for a in ['기', '승', '전', '결'])
    sections.append(('apichatpong', '아피찻퐁 위라세타쿤', ap['_출처'], '어둠 속 빛 · 몽환 — 기본 참조(늘 50% 이상)',
                     len(used), len(names), maps,
                     ''.join(card('stills/apichatpong/' + n, n, True) for n in used),
                     ''.join(card('stills/apichatpong/' + n, n, False, '선별 제외(포스터·표지·제품·인물·드로잉·현장 기록·중복)') for n in ex)))
    for key, a in ARTISTS.items():
        e = ar.get(key)
        d = os.path.join(HERE, 'stills', 'artist', key)
        names = sorted(n for n in os.listdir(d) if n.endswith('.jpg') and not n.startswith('_'))
        # measure() 가 200x150 미만은 재지 않는다 — 그런 그림은 '쓴 것'이 아니다(09-27: 폰타나 8장)
        from PIL import Image
        small = {n for n in names if (lambda s: s[0] < 200 or s[1] < 150)(Image.open(os.path.join(d, n)).size)}
        used = [n for n in names if not excluded(key, n) and n not in small]
        ex = [n for n in names if excluded(key, n) or n in small]
        sections.append((key, a['name'], a['source'], a['role'], e['표본수'] if e else 0, len(names),
                         '<div><small>전체</small>%s</div>' % heat(e['구도지도']) if e else '',
                         ''.join(card('stills/artist/%s/%s' % (key, n), n, True) for n in used),
                         ''.join(card('stills/artist/%s/%s' % (key, n), n, False,
                                      '200x150 미만 — 통계에서 제외' if n in small and not excluded(key, n) else reason(key, n))
                                 for n in ex)))

    nav = ''.join('<a href="#%s">%s <em>%d/%d</em></a>' % (k, html.escape(t.split(' (')[0]), u, n)
                  for k, t, _, _, u, n, _, _, _ in sections)
    body = ''
    for k, title, src, role, u, n, maps, used_html, ex_html in sections:
        body += ('<section id="%s"><h2>%s</h2><p>%s<br><span>%s</span></p>'
                 '<div class="maps">%s</div>'
                 '<h3>쓴 것 %d장</h3><div class="grid">%s</div>'
                 '<details><summary>뺀 것 %d장 — 이유 보기</summary><div class="grid">%s</div></details></section>'
                 % (k, html.escape(title), html.escape(role), html.escape(src), maps, u, used_html, n - u, ex_html))

    page = '''<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>참조 DB 갤러리</title>
<style>
:root{--bg:#0e0f11;--fg:#ddd;--mute:#8a8a8a;--line:#2a2b2e;--acc:#c9bb95}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 -apple-system,"Malgun Gothic",sans-serif}
header{position:sticky;top:0;background:#0e0f11ee;border-bottom:1px solid var(--line);padding:10px 16px;z-index:2}
header h1{font-size:16px;margin:0 0 6px;font-weight:600}
nav{display:flex;flex-wrap:wrap;gap:6px}nav a{color:var(--fg);text-decoration:none;border:1px solid var(--line);padding:3px 10px;border-radius:14px}
nav em{color:var(--mute);font-style:normal;font-size:12px}
main{padding:0 16px 40px;max-width:1400px;margin:auto}
table{border-collapse:collapse;margin:14px 0;font-variant-numeric:tabular-nums;overflow-x:auto;display:block}
th,td{border-bottom:1px solid var(--line);padding:4px 10px;text-align:right;white-space:nowrap}th{color:var(--acc);font-weight:500;text-align:left}
section{border-top:1px solid var(--line);padding-top:10px;margin-top:22px;scroll-margin-top:90px}
h2{font-size:18px;margin:6px 0}h3{font-size:14px;color:var(--mute);font-weight:500}p span{color:var(--mute);font-size:12px}
.maps{display:flex;gap:14px;flex-wrap:wrap}.maps small{color:var(--mute)}
.heat{display:grid;width:180px;aspect-ratio:12/8;gap:1px;background:#000;border:1px solid var(--line)}.heat i{display:block}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}
figure{margin:0;background:#16171a;border-radius:4px;overflow:hidden}
figure img{width:100%;aspect-ratio:1;object-fit:cover;display:block}
figcaption{font-size:11px;color:var(--mute);padding:4px 6px;word-break:break-all}
figure.ex{opacity:.55}
.note{color:var(--mute);font-size:12px}figcaption b{display:block;color:#c98b6a;font-weight:500}
details summary{cursor:pointer;color:var(--mute);margin:12px 0}
</style></head><body>
<header><h1>참조 DB 갤러리 — PDF 시스템 I 참조 작가 4명</h1><nav>@@NAV@@</nav></header>
<main>
<p style="color:var(--mute)">표본 수는 '쓴 것 / 받은 것'. 지표는 128px 로 줄여 잰 평균(마우스를 올리면 뜻). 구도 지도는 밝을수록 그 작가가 빛을 두는 자리.
※ 이 파일과 이미지는 로컬 전용 — 작가 저작물이라 외부에 올리지 않는다. 다시 만들기: <code>python db/build_gallery.py</code></p>
@@TABLE@@
@@BODY@@
</main></body></html>'''
    # CSS 에 % 가 많아 % 서식 대신 자리표시를 바꿔 넣는다
    page = page.replace('@@NAV@@', nav).replace('@@TABLE@@', table).replace('@@BODY@@', body)
    open(OUT, 'w', encoding='utf-8').write(page)
    print('저장:', OUT)


if __name__ == '__main__':
    main()
