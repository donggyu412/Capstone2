# -*- coding: utf-8 -*-
"""참조 작가 3명 DB 생성기 — 오프라인 도구 (2026-09-27)

PDF 시스템 I 의 참조 작가는 4명이다: 조지 디갈라카스 · 마에다 신조 · 프랑코 폰타나 · 아피찻퐁.
그동안 DB 는 아피찻퐁 1명뿐이었다(apichatpong_db.json). 나머지 3명을 **같은 지표**로 잰다.

  pip install pillow numpy
  python db/build_artist_db.py            받기 + DB 저장 (그다음 python db/build_gallery.py 로 갤러리 갱신)
  python db/build_artist_db.py --sheets   선별용 밀착 인화(_contact_*.jpg)만 만든다

하는 일:
  1) 작가 공식 사이트에서 **풍경·배경 계열 시리즈만** 받는다 (인물·오브제·상점·도서 페이지 제외).
     받은 이미지는 db/stills/artist/<작가>/ 에 긴 변 800px JPEG 로 보관(재실행 시 다시 안 받음).
  2) 작가마다 밀착 인화(_contact_N.jpg)를 만든다 — 한 장씩 보고 '작가의 화면'이 아닌 것을 EXCLUDE 에 적는다.
     (아피찻퐁 때 포스터·드로잉이 섞여 '전' 군집이 오염된 전례가 있다. 수작업 선별은 생략하지 않는다)
  3) build_apichatpong_db.measure() 로 색·명암 7지표 + 12x8 구도 지도를 뽑아 artist_db.json 에 저장.

왜 아피찻퐁 DB 에 섞지 않는가:
  apichatpong_db.json 의 막별 목표값은 09-13 확정값이다. 표본을 합쳐 다시 군집하면 그 값이 바뀐다.
  그래서 작가별로 따로 두고, 엔진에 어떻게 섞을지는 수치를 본 뒤 정한다.

저작권: 이미지를 재배포하거나 학습시키지 않는다. 통계(평균·분포)만 뽑고, 원본 캐시는 로컬에만 둔다.
"""
import sys
sys.dont_write_bytecode = True   # 도구끼리 import 해도 __pycache__ 가 쌓이지 않게 (09-27 폴더 정리)
import os, re, sys, json, time, html, urllib.request
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(HERE, 'stills', 'artist')
OUT = os.path.join(HERE, 'artist_db.json')
sys.path.insert(0, HERE)
from build_apichatpong_db import measure, KEYS, KEY_DESC, COMP_KEYS, GW, GH   # 아피찻퐁과 똑같은 잣대

UA = {'User-Agent': 'Mozilla/5.0'}


def get(url, timeout=30):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()


# ── 작가별 출처 ───────────────────────────────────────────────
# 시리즈는 '배경'이 될 수 있는 것만 고른다. 우리 시스템은 인간의 꿈 = 배경이다(오브제·인물은 다른 몫).
ARTISTS = {
    'digalakis': {
        'name': '조지 디갈라카스 (George Digalakis)',
        'source': 'https://digalakisphotography.com/ (작가 공식 사이트, Portfoliobox)',
        'role': '단순 · 여백 — 흑백 장노출 미니멀 풍경(물·바위·나무·안개)',
        'series': ['Winter', 'Silent Monoliths', 'Kensho', 'Whispers of Silence', 'Silent Waters', 'Ephemera',
                   'Iceland', 'The Sound of Silence', 'Whispers of the Earth', 'The Shape of Rocks',
                   'Tales of Water', 'Water Stories', 'Life of a Treee', 'In Praise Of Shadows'],
        # 제외: Store · License · Bookstore · Prints(상품) / About · Portfolio(표지) / Inspirations(타 작가 가능성)
        #       Birds of Paradise(새 = 오브제) · Urban Encounters(도시·인물)
    },
    'fontana': {
        'name': '프랑코 폰타나 (Franco Fontana)',
        'source': 'https://francofontanaphotographer.com/ (작가 공식 사이트, Adobe Portfolio)',
        'role': '빛 · 색 — 색면으로 단순화한 풍경(들판·바다·하늘)',
        'series': ['paesaggi', 'mari', 'nuvole', 'dallalto'],
        # 제외: gente(인물) · nudo · copia-di-franco-fontana(도서) · urbani·eur·asfalti·autostrada·piscina(도시·인공물)
        #       ※ francofontana.it 는 동명의 회계 사무소다 — 쓰지 않는다(09-27 확인)
    },
    'maeda': {
        'name': '마에다 신조 (前田真三)',
        'source': 'https://www.hilltohill.jp/print (생誕100년 공식 프로젝트 「SHINZO MAEDA 100 COLLECTION」)',
        'role': '여백 · 안개 · 빛 — 비에이 구릉의 아날로그 풍경(아침 안개·설원·노을)',
        'series': ['print'],
        'trim': True,   # 흰 매트 위 프린트 목업 — 매트를 걷어내고 잰다(걷어내면 25점 모두 정확히 40% 남음)
        # 같은 사이트의 다른 이미지는 전시장·프로필·도서·아들/손자 작품이 섞여 있어 쓰지 않는다.
        # 프린트 25점은 페이지에 No.·제목·연도(1977~1991)가 모두 명기된 본인 작품이다.
    },
}

# 밀착 인화를 보고 '작가의 화면'이 아닌 것을 적는다 (2026-09-27, 한 장씩 보고 가름).
# 파일명이거나, '*' 로 끝나면 접두어(시리즈 통째).
EXCLUDE = {
    'digalakis': [
        'ephemera__*',                 # 13장 — 글자가 박힌 매거진·책 표지
        'in-praise-of-shadows__*',     # 18장 — 성당 실내·촛불·인물. 배경 풍경이 아니다
        # 유튜브 썸네일(제목 글자·재생바가 찍힘)
        'iceland__1-5c5102.jpg',
        'silent-monoliths__bnw-profusion-the-shape-of-rocks-7fa285.jpg',
        'silent-waters__bnw-profusion-water-stories-2176d0.jpg',
        'tales-of-water__bnw-profusion-breaking-the-waves-bb9e1a.jpg',
        'whispers-of-silence__bnw-profusion-the-sound-of-silence-8486b1.jpg',
        'whispers-of-the-earth__bnw-profusion-on-the-land-a8d77e.jpg',
    ],
    'fontana': [
        'dallalto_*',                  # 9장 — 도시 횡단보도·택시·인파 가득한 해변의 항공 사진. 사람·사물이 주인공
        'paesaggi_18_117b874a.jpg',    # 흰 바탕 풀 선묘 — 사진이라기보다 드로잉에 가깝다
        'paesaggi_44_0ebcc440.jpg',    # paesaggi_12 와 같은 사진(중복)
    ],
    'maeda': [],                       # 25점 모두 비에이 풍경 — 제외 없음
}


def excluded(artist, name):
    for e in EXCLUDE.get(artist, []):
        if (e.endswith('*') and name.startswith(e[:-1])) or name == e:
            return True
    return False


# ── 1. 수집 ──────────────────────────────────────────────────
def list_digalakis():
    s = get('https://digalakisphotography.com/').decode('utf-8', 'ignore').replace('\\/', '/')
    marks = [(m.start(), m.group(1)) for m in re.finditer(r'"Url":"/[^"]*","Title":"([^"]*)"', s)]
    want = set(ARTISTS['digalakis']['series'])
    out = {}
    for m in re.finditer(r'"Src":"(https://[^"]+/000_clients/144188/page/([^"]+))","Height":\d+,"Width":\d+', s):
        owner = [t for p, t in marks if p < m.start()]
        if owner and owner[-1] in want:
            out.setdefault(m.group(2), (m.group(1), owner[-1]))   # 같은 사진이 여러 시리즈에 있으면 처음 것
    slug = lambda t: re.sub(r'[^a-z0-9]+', '-', t.lower()).strip('-')
    return [('%s__%s' % (slug(ser), name.lstrip('-')), url, ser) for name, (url, ser) in out.items()]


def list_fontana():
    out = {}
    for ser in ARTISTS['fontana']['series']:
        s = get('https://francofontanaphotographer.com/' + ser).decode('utf-8', 'ignore')
        # ★ 주소 끝의 ?h= 는 서명이다 — 떼면 CDN 이 400 을 돌려준다(09-27 첫 실행에서 88장 전부 실패)
        order = []
        for m in re.finditer(r'https://cdn\.myportfolio\.com/[0-9a-f\-]+/([0-9a-f\-]{36})_rw_(\d+)\.\w+\?h=[0-9a-f]+', s):
            uid, w = m.group(1), int(m.group(2))
            if uid not in out:
                order.append(uid)
            if uid not in out or w > out[uid][1]:
                out[uid] = (m.group(0), w, ser)
        for k, uid in enumerate(order):
            out[uid] = out[uid] + ('%s_%02d_%s.jpg' % (ser, k + 1, uid[:8]),)
    return [(name, url, ser) for uid, (url, w, ser, name) in out.items()]


def list_maeda():
    s = get('https://www.hilltohill.jp/print').decode('utf-8', 'ignore')
    titles = dict(re.findall(r'No\.(\d{3})\s*([^<\n]+?\d{4})', html.unescape(re.sub(r'<[^>]+>', '\n', s))))
    best = {}
    for m in re.finditer(r'(https://format\.creatorcdn\.com/[^"\s]+?/0,0,\d+,\d+,(\d+),\d+/0-0-0/[0-9a-f\-]{36}/1/\d+/'
                         r'sm100_print_(\d{3})_format\.jpg\?[^"\s]+)', s):
        url, w, no = m.group(1), int(m.group(2)), m.group(3)
        if no not in best or w > best[no][1]:
            best[no] = (html.unescape(url), w)
    def nm(no):
        t = re.sub(r'[\s　]+', '_', titles.get(no, '').strip())
        return '%s_%s.jpg' % (no, t) if t else 'print_%s.jpg' % no
    return [(nm(no), url, titles.get(no, '').strip()) for no, (url, w) in sorted(best.items())]


LISTERS = {'digalakis': list_digalakis, 'fontana': list_fontana, 'maeda': list_maeda}


def download(artist):
    d = os.path.join(CACHE, artist)
    os.makedirs(d, exist_ok=True)
    meta_path = os.path.join(d, '_meta.json')
    meta = json.load(open(meta_path, encoding='utf-8')) if os.path.exists(meta_path) else {}
    items = LISTERS[artist]()
    print('%s: 목록 %d장' % (artist, len(items)))
    by_url = {v['url']: k for k, v in meta.items()}          # 이름 규칙이 바뀌어도 다시 받지 않는다
    meta = {}
    for name, url, tag in items:
        stem = os.path.splitext(name)[0] + '.jpg'
        dst = os.path.join(d, stem)
        meta[stem] = {'url': url, 'series': tag}
        old = by_url.get(url)
        if old and old != stem and os.path.exists(os.path.join(d, old)) and not os.path.exists(dst):
            os.rename(os.path.join(d, old), dst)
        if os.path.exists(dst):
            continue
        try:
            im = Image.open(__import__('io').BytesIO(get(url))).convert('RGB')
            im.thumbnail((800, 800))                    # 통계는 128px 로 재므로 800px 이면 충분하다
            im.save(dst, quality=90)
            time.sleep(0.2)                             # 작가 사이트에 부담을 주지 않는다
        except Exception as e:
            print('   받기 실패 %s: %s' % (name, e))
            meta.pop(stem, None)
    json.dump(meta, open(meta_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return meta


# ── 2. 밀착 인화 (선별용) ────────────────────────────────────
def contact_sheets(artist, per=48, cols=8, cell=180):
    d = os.path.join(CACHE, artist)
    for n in os.listdir(d):
        if n.startswith('_contact_'):
            os.remove(os.path.join(d, n))
    names = sorted(n for n in os.listdir(d) if n.endswith('.jpg') and not n.startswith('_'))
    from PIL import ImageDraw
    for k in range(0, len(names), per):
        chunk = names[k:k + per]
        rows = (len(chunk) + cols - 1) // cols
        sheet = Image.new('RGB', (cols * cell, rows * (cell + 16)), (30, 30, 30))
        dr = ImageDraw.Draw(sheet)
        for i, n in enumerate(chunk):
            im = Image.open(os.path.join(d, n)); im.thumbnail((cell - 6, cell - 6))
            x, y = (i % cols) * cell, (i // cols) * (cell + 16)
            sheet.paste(im, (x + 3, y + 3))
            dr.text((x + 3, y + cell), '%d %s' % (k + i, n[:22]), fill=(220, 220, 220))
        sheet.save(os.path.join(d, '_contact_%d.jpg' % (k // per + 1)), quality=85)
    return names


# ── 3. 측정 · 저장 ───────────────────────────────────────────
def trim_border(im, tol=14):
    """균일한 테두리(액자 여백·매트)를 걷어낸다.

       마에다 신조 프린트 25점은 흰 매트 위에 사진이 놓인 목업이라, 그대로 재면 밝은 화소가 63% 로 나왔다
       (사진이 아니라 매트를 잰 것). 아피찻퐁 DB 에서 초록 원형 액자가 색 통계를 왜곡한 것과 같은 문제다.
       네 모서리 색과 tol 이상 다른 화소의 외곽 사각형만 남긴다. 테두리가 없으면 원본 그대로."""
    a = np.asarray(im, dtype=np.int16)
    corner = np.median(np.array([a[0, 0], a[0, -1], a[-1, 0], a[-1, -1]]), axis=0)
    diff = np.abs(a - corner).max(2) > tol
    rows, cols = np.where(diff.any(1))[0], np.where(diff.any(0))[0]
    if len(rows) == 0 or len(cols) == 0:
        return im
    y0, y1, x0, x1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
    h, w = a.shape[:2]
    if (y1 - y0) * (x1 - x0) > 0.97 * h * w:       # 걷어낼 테두리가 사실상 없다
        return im
    return im.crop((x0, y0, x1, y1))


def build(artist, meta):
    d = os.path.join(CACHE, artist)
    ex = sorted(n for n in meta if excluded(artist, n))
    rows, trimmed = [], []
    for n in sorted(meta):
        if excluded(artist, n):
            continue
        src = os.path.join(d, n)
        im = Image.open(src).convert('RGB')
        # 테두리 걷기는 매트가 확인된 작가만. 디갈라카스·폰타나에 걸면 사진 자체의 검은 하늘·바위를
        # 테두리로 오인해 잘랐다(09-27 실측: 'the-tunnel' 가로 29% 잘림) — 구도 통계가 틀어진다.
        t = trim_border(im) if ARTISTS[artist].get('trim') else im
        if t is not im:                                 # measure() 는 경로를 받으므로 걷어낸 사본을 잠깐 쓴다
            src = os.path.join(d, '_trim.jpg'); t.save(src, quality=95)
            trimmed.append(n)
        r = measure(src)
        if r:
            r['_series'] = meta[n]['series']
            rows.append(r)
    tmp = os.path.join(d, '_trim.jpg')
    if os.path.exists(tmp):
        os.remove(tmp)
    if trimmed:
        print('   테두리 걷어냄 %d장' % len(trimmed))
    if not rows:
        return None                                   # 하나도 못 받았으면 DB 에 넣지 않는다(빈 평균은 거짓 값이다)
    X = np.array([[r[k] for k in KEYS] for r in rows])
    cmap = np.mean([r['_map'] for r in rows], axis=0)
    cmap = cmap / max(cmap.mean(), 1e-6)
    a = ARTISTS[artist]
    return {
        '이름': a['name'], '출처': a['source'], '역할': a['role'],
        '표본수': len(rows), '받은수': len(meta), '제외수': len(ex), '제외': ex, '테두리걷어냄': len(trimmed),
        '시리즈별': {s: sum(1 for r in rows if r['_series'] == s) for s in sorted(set(r['_series'] for r in rows))},
        '평균': {k: round(float(X[:, i].mean()), 4) for i, k in enumerate(KEYS)},
        '편차': {k: round(float(max(X[:, i].std(), 0.03)), 4) for i, k in enumerate(KEYS)},
        '구도': {k: round(float(np.mean([r[k] for r in rows])), 4) for k in COMP_KEYS},
        '구도지도': [[round(float(v), 3) for v in row] for row in cmap],
    }


def main():
    only_sheets = '--sheets' in sys.argv
    db = {'_설명': 'PDF 시스템 I 참조 작가 3명 — 아피찻퐁 DB(apichatpong_db.json)와 같은 지표·같은 구도 격자',
          '_지표': KEY_DESC, '_구도격자': [GW, GH], '_생성': time.strftime('%Y-%m-%d'), '작가': {}}
    for artist in ARTISTS:
        meta_path = os.path.join(CACHE, artist, '_meta.json')
        meta = json.load(open(meta_path, encoding='utf-8')) if only_sheets and os.path.exists(meta_path) else download(artist)
        # 밀착 인화는 선별할 때만 (--sheets). 평소 보기는 db/db_gallery.html (build_gallery.py) 로 한다.
        if only_sheets:
            names = contact_sheets(artist)
            print('   밀착 인화 %d장 → db/stills/artist/%s/_contact_*.jpg' % (len(names), artist))
        if not only_sheets:
            e = build(artist, meta)
            if not e:
                print('   ⚠ 표본 0장 — DB 에서 뺀다'); continue
            db['작가'][artist] = e
            print('   표본 %d장 · ' % e['표본수'] + '  '.join('%s %.3f' % (k, e['평균'][k]) for k in KEYS))
    if not only_sheets:
        json.dump(db, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('저장:', OUT)


if __name__ == '__main__':
    main()
