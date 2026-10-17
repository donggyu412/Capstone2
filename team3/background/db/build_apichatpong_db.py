# -*- coding: utf-8 -*-
"""아피찻퐁 참조 DB 생성기 — 오프라인 1회용 도구.

작품을 돌리는 데는 필요 없다. app.py / index.html 은 이 스크립트 없이 돌아간다.
결과물인 apichatpong_db.json(프로젝트 최상위)만 있으면 되고, 그 파일은 이미 있다.
DB 를 다시 만들거나 표본을 늘리고 싶을 때만 쓴다.

  pip install pillow numpy
  python db/build_apichatpong_db.py      (프로젝트 최상위에서)

하는 일:
  1) http://www.kickthemachine.com/ (아피찻퐁 위라세타쿤 공식 사이트) 내부
     페이지를 훑어 스틸 이미지를 받는다. (HTTPS 는 TLS 오류가 나므로 HTTP)
  2) 각 스틸을 128x128 로 줄여 색·명암 지표 7개를 뽑는다.
  3) z정규화 후 k-means(k=4)로 군집하고, 각 군집을 기승전결의 서사적 서명에
     1:1 로 배정해 막별 목표값·허용편차를 저장한다.

왜 이렇게 하나:
  교수님 지적 — 유전 알고리즘 적합도가 캡스톤1의 감정 기반 그대로라 이 작품이
  '아피찻퐁을 학습한 것'이 아니라 '감정을 필터로 쓴 것'에 머물러 있었다.
  적합도의 기준을 실제 아피찻퐁 화면 통계로 바꾸기 위한 근거 데이터다.
"""
import os, re, sys, json, time, itertools, urllib.request, urllib.parse
import numpy as np
from PIL import Image

BASE = 'http://www.kickthemachine.com/'
HERE = os.path.dirname(os.path.abspath(__file__))        # db/

STILLS = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, 'stills', 'apichatpong')   # 받은 스틸 보관(재실행 시 다시 안 받음)
OUT = os.path.join(HERE, 'apichatpong_db.json')                # app.py 가 db/ 에서 읽는다
MAX_PAGES = 200

KEYS = ['val', 'con', 'sat', 'dark', 'hi', 'hconc', 'warm']

# ── 구도(composition) — 2026-09-25 추가 ────────────────────
# 그동안 DB 는 색·명암 스칼라 7개뿐이었고, 그것이 닿는 곳은 안개 채도·파편 색온도·GA 적합도,
# 즉 '색'이 전부였다. 파티클이 어디에 앉을지(=형태·구도)는 100% 입력 이미지 밝기가 정했다.
# 그래서 DB 는 '참조'였을 뿐 이미지 생성에 관여하지 않았다 — 결과가 원본의 점묘화에 머물렀다.
#
# 이제 막마다 '빛이 화면의 어디에 오는가'를 지도로 뽑는다.
#   · 스틸을 GW x GH 격자로 줄여 휘도를 재고, **장마다 평균 1.0 으로 정규화**한다.
#     (밝기가 아니라 '분포'만 가져오기 위해서다. 안 하면 밝은 스틸이 지도를 지배한다)
#   · 같은 막 군집의 스틸들을 평균 → 그 막의 구도 지도.
#   · 값 1.0 = 평균적인 자리, >1 = 아피찻퐁이 빛을 두는 자리, <1 = 비워두는 자리.
# 프론트의 assignHomes() 가 이 지도를 입력 이미지 밝기에 곱해, 파편의 '제 자리'를
# 아피찻퐁 구도 쪽으로 끌어당긴다.
#
# ★ 군집(k-means)은 색 지표 7개로만 한다 — 09-13 에 확정한 막별 색 목표가 바뀌면 안 된다.
#   구도는 이미 갈린 군집 안에서 평균만 낸다(순수 추가).
GW, GH = 12, 8
COMP_KEYS = ['cx', 'cy', 'vign', 'hband']
COMP_DESC = {
    'cx':    '밝기 무게중심 가로 위치(0=왼쪽, 1=오른쪽)',
    'cy':    '밝기 무게중심 세로 위치(0=위, 1=아래)',
    'vign':  '중심부 밝기 / 주변부 밝기 (1보다 크면 가운데가 밝다)',
    'hband': '가장 밝은 가로 띠의 세로 위치(0=위, 1=아래) — 수평 구도의 지평선',
}
KEY_DESC = {
    'val':   '평균 명도(0~1)',
    'con':   '대비(명도 표준편차)',
    'sat':   '평균 채도',
    'dark':  '명도 0.20 미만 화소 비율(여백)',
    'hi':    '명도 0.80 초과 화소 비율',
    'hconc': '색상 집중도(1이면 한 색으로 몰림, 0이면 흩어짐)',
    'warm':  '난색(적·황) 화소 비율',
}

# ── 선별 목록 (2026-09-13, 수작업) ──────────────────────────
# 사이트 이미지 157장(200x150 이상) 중 '아피찻퐁의 화면'인 것만 남겼다.
#   남김  영화 스틸 / 작품이 화면을 채운 설치 이미지(어두운 방의 빛·영사)
#   제외  포스터·표지·타이포그래피 / 제품 사진(박스세트·음반·카메라) / 인물 프로필·행사 사진 /
#         드로잉·그래픽·도면·회화 / 관람객·촬영 장비가 찍힌 현장 기록 /
#         초록 원형 액자 레이아웃(액자 바탕이 색 통계를 왜곡) / 중복
# 처음 DB 는 157장을 다 썼는데, '전' 군집(명도 0.82·하이라이트 72%·채도 0.05)은
# 흰 바탕 포스터·드로잉이 만든 값이었다. 사진 한 장씩 보고 가른 목록이며, 키는 파일명(해시)이다.
# 비워 두면(CURATED = []) 예전처럼 전부 쓴다.
CURATED = [
    'stacks-image-5010786-550x416.jpg',
    'stacks-image-d33b3ca-550x520.jpg',
    'stacks-image-35c96bb.jpg',
    'stacks-image-09d53be.jpg',
    'stacks-image-f6d515c.jpg',
    'stacks-image-0b10564-1200x596.jpg',
    'stacks-image-c8c54c1.jpg',
    'stacks-image-e264b6d.jpg',
    'stacks-image-3460a31.jpg',
    'stacks-image-7a2665f.jpg',
    'stacks-image-91205f2-800x532.jpg',
    'stacks-image-621325d.png',
    'stacks-image-a87fb59.jpg',
    'stacks-image-aa0196d.png',
    'stacks-image-1b797ee.jpg',
    'stacks-image-c894ceb.jpg',
    'stacks-image-ad080e4.jpg',
    'stacks-image-6da821d.jpg',
    'stacks-image-16174ff.jpg',
    'stacks-image-7b5d0b5.jpg',
    'stacks-image-4eaf09e.jpg',
    'stacks-image-9a3e869-1198x632.jpg',
    'stacks-image-a40a5c7-1198x794.jpg',
    'stacks-image-65e2602.jpg',
    'stacks-image-82a803b.jpg',
    'stacks-image-92e6d19.jpg',
    'stacks-image-9e236ec.jpg',
    'stacks-image-d4d9f9a.jpg',
    'stacks-image-699f2cd.jpg',
    'stacks-image-77a0f43.jpg',
    'stacks-image-b15b122.jpg',
    'stacks-image-e6d4bb4.jpg',
    'stacks-image-fd1a016.jpg',
    'stacks-image-7826259.jpg',
    'stacks-image-984a0c5.jpg',
    'stacks-image-2f05dbf.jpg',
    'stacks-image-6a0096e.jpg',
    'stacks-image-b0ed514.jpg',
    'stacks-image-74d7f22.jpg',
    'stacks-image-4841338.jpg',
    'stacks-image-6b25e51.jpg',
    'stacks-image-88f99ba.jpg',
    'stacks-image-6d65dfa.jpg',
    'stacks-image-6207662.jpg',
    'stacks-image-d67ebe2.jpg',
    'stacks-image-b6b3b80.jpg',
    'stacks-image-65f4618-800x464.jpg',
    'stacks-image-396d285.jpg',
    'stacks-image-9bba00b.jpg',
    'stacks-image-a18bd38.jpg',
    'stacks-image-cfcbbb2-532x800.jpg',
]

# 이 사이트의 <img> 는 작은따옴표를 쓴다. 큰따옴표만 보면 스틸을 통째로 놓친다.
LINK_RE = re.compile(r'(?:href|src)\s*=\s*["\']([^"\']+)["\']', re.I)


# ── 1. 수집 ────────────────────────────────────────────────
def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (capstone research)'})
    return urllib.request.urlopen(req, timeout=timeout).read()


def crawl():
    """내부 페이지를 훑어 스틸을 받는다. 이미 받아둔 파일은 건너뛴다."""
    os.makedirs(STILLS, exist_ok=True)
    seen, queue, imgs = set(), [BASE], {}
    while queue and len(seen) < MAX_PAGES:
        u = queue.pop(0)
        if u in seen:
            continue
        seen.add(u)
        try:
            html = fetch(u).decode('utf-8', 'replace')
        except Exception as e:
            print('  페이지 실패', u, e)
            continue
        for m in LINK_RE.finditer(html):
            link = urllib.parse.urljoin(u, m.group(1))
            if not link.startswith(BASE):
                continue
            low = link.lower().split('?')[0]
            if low.endswith(('.jpg', '.jpeg', '.png')):
                imgs[link] = u
            elif low.endswith(('/', 'index.html')) and link not in seen:
                queue.append(link)
        time.sleep(0.15)
    print('페이지 %d개 / 이미지 후보 %d개' % (len(seen), len(imgs)))

    got = []
    for i, url in enumerate(sorted(imgs)):
        name = ('%03d_%s' % (i, re.sub(r'[^A-Za-z0-9_.-]', '_',
                urllib.parse.unquote(url.split('/')[-1]))))[:90]
        path = os.path.join(STILLS, name)
        if not os.path.exists(path):
            try:
                data = fetch(url)
                if len(data) < 6000:        # 아이콘·버튼류는 버린다
                    continue
                open(path, 'wb').write(data)
            except Exception as e:
                print('  이미지 실패', url, e)
                continue
            time.sleep(0.1)
        got.append(path)
    print('스틸 %d장 확보 (%s)' % (len(got), STILLS))
    return got


# ── 2. 지표 추출 ───────────────────────────────────────────
def measure(path):
    """스틸 한 장에서 색·명암 지표 7개. 너무 작은 그림(로고 등)은 None."""
    try:
        im = Image.open(path).convert('RGB')
    except Exception:
        return None
    if im.size[0] < 200 or im.size[1] < 150:
        return None
    a = np.asarray(im.resize((128, 128)), dtype=np.float32) / 255.0
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mx, mn = a.max(2), a.min(2)
    d = mx - mn
    sat = np.where(mx > 1e-6, d / np.maximum(mx, 1e-6), 0)
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b

    m = d > 1e-6                                  # 무채색 화소는 색상이 없다
    hue = np.zeros(int(m.sum()), dtype=np.float32)
    if m.any():
        rr, gg, bb, mxm, dm = r[m], g[m], b[m], mx[m], d[m]
        i1 = mxm == rr
        i2 = (mxm == gg) & ~i1
        i3 = ~i1 & ~i2
        hue[i1] = ((gg[i1] - bb[i1]) / dm[i1]) % 6
        hue[i2] = (bb[i2] - rr[i2]) / dm[i2] + 2
        hue[i3] = (rr[i3] - gg[i3]) / dm[i3] + 4
        hue *= 60.0
    # 색상은 각도라 그냥 평균내면 안 된다 — 채도로 가중한 원형 평균의 길이를 쓴다
    w = sat[m]
    if w.sum() > 1e-6:
        ang = np.deg2rad(hue)
        hconc = float(np.hypot((np.cos(ang) * w).sum() / w.sum(),
                               (np.sin(ang) * w).sum() / w.sum()))
        warm = float(((hue < 70) | (hue > 330)).mean())
    else:
        hconc, warm = 0.0, 0.0

    # ── 구도 — 밝기가 화면의 어디에 오는가 ──────────────────
    # 원본 비율 그대로 GW x GH 로 눌러 담는다(가로가 긴 스틸도 세로가 긴 스틸도 같은 격자로).
    gm = np.asarray(Image.open(path).convert('L').resize((GW, GH)), dtype=np.float64) / 255.0
    mean = gm.mean()
    gnorm = gm / mean if mean > 1e-6 else np.ones_like(gm)   # ★ 밝기가 아니라 분포만 가져온다

    ys, xs = np.mgrid[0:GH, 0:GW]
    tot = gm.sum() + 1e-9
    cx = float((gm * xs).sum() / tot / max(1, GW - 1))
    cy = float((gm * ys).sum() / tot / max(1, GH - 1))
    cy0, cy1 = GH // 4, GH - GH // 4                  # 가운데 절반
    cx0, cx1 = GW // 4, GW - GW // 4
    inner = gm[cy0:cy1, cx0:cx1].mean()
    outer = (gm.sum() - gm[cy0:cy1, cx0:cx1].sum()) / max(1, gm.size - (cy1 - cy0) * (cx1 - cx0))
    vign = float(inner / max(outer, 1e-6))
    hband = float(gm.mean(1).argmax() / max(1, GH - 1))

    return {
        'val': float(lum.mean()), 'con': float(lum.std()), 'sat': float(sat.mean()),
        'dark': float((lum < 0.20).mean()), 'hi': float((lum > 0.80).mean()),
        'hconc': hconc, 'warm': warm,
        'cx': cx, 'cy': cy, 'vign': vign, 'hband': hband,
        '_map': gnorm,
    }


# ── 3. 군집 → 막 배정 ──────────────────────────────────────
def kmeans4(Z):
    """씨앗 20개를 돌려 관성이 가장 작은 해를 쓴다. 매번 같은 결과가 나오도록 고정."""
    best = None
    for seed in range(20):
        rs = np.random.RandomState(seed)
        C = Z[rs.choice(len(Z), 4, replace=False)]
        lab = None
        for _ in range(120):
            lab = ((Z[:, None, :] - C[None]) ** 2).sum(2).argmin(1)
            newC = np.array([Z[lab == j].mean(0) if (lab == j).any() else C[j] for j in range(4)])
            if np.allclose(newC, C):
                break
            C = newC
        inertia = ((Z - C[lab]) ** 2).sum()
        if best is None or inertia < best[0]:
            best = (inertia, C.copy(), lab.copy())
    return best


# 막마다 '이런 화면이어야 한다'는 서사적 서명. 방향 +1 이면 클수록 그 막답고, 0 이면 중간일수록.
#   기 파편·카오스 → 어둡고 대비가 산다 / 승 안착·형태 → 중간 명도에 차분 /
#   전 빛·노출 → 밝고 하이라이트가 터진다 / 결 여백·소멸 → 어둡고 색이 빠진다
SIGNATURE = {
    '기': [('con', +1), ('dark', +1), ('hconc', -1)],
    '승': [('val', 0), ('sat', -1), ('con', -1)],
    '전': [('val', +1), ('hi', +1), ('warm', +1)],
    '결': [('dark', +1), ('sat', -1), ('hi', -1)],
}
ACTS = ['기', '승', '전', '결']


def main():
    paths = crawl()
    if CURATED:
        want = set(CURATED)
        paths = [p for p in paths if os.path.basename(p).split('_', 1)[-1] in want]
        print('선별 목록 적용: %d장' % len(paths))
    rows = [s for s in (measure(p) for p in paths) if s]
    if len(rows) < 20:
        print('표본이 너무 적습니다(%d장). 중단.' % len(rows))
        return
    print('지표 추출 %d장' % len(rows))

    X = np.array([[r[k] for k in KEYS] for r in rows], dtype=np.float64)
    mu, sd = X.mean(0), X.std(0) + 1e-9
    inertia, C, lab = kmeans4((X - mu) / sd)
    print('군집 관성 %.1f, 크기 %s' % (inertia, [int((lab == j).sum()) for j in range(4)]))

    def score(j, act):
        t = 0.0
        for k, dirn in SIGNATURE[act]:
            v = C[j][KEYS.index(k)]              # 군집 중심의 z 점수
            t += (-abs(v) if dirn == 0 else dirn * v)
        return t
    assign = max(itertools.permutations(range(4)),
                 key=lambda p: sum(score(p[i], ACTS[i]) for i in range(4)))

    db = {
        '_출처': BASE + ' (아피찻퐁 위라세타쿤 공식 사이트)',
        '_수집': ('내부 페이지를 훑어 받은 이미지 중 영화 스틸·설치 이미지만 수작업 선별해 %d장 사용 '
                 '(포스터·표지·제품·인물 프로필·드로잉·현장 기록 제외)' % len(rows)) if CURATED
                else '내부 페이지를 훑어 스틸을 받고, 200x150 미만을 걸러 %d장 사용' % len(rows),
        '_방법': '128x128 로 줄여 지표 7개를 뽑고 z정규화 후 k-means(k=4). '
                 '군집을 기승전결의 서사적 서명에 1:1 배정',
        '_표본수': len(rows),
        '_지표': KEY_DESC,
        '_구도지표': COMP_DESC,
        '_구도격자': [GW, GH],
        '_구도방법': ('스틸을 %dx%d 격자로 줄여 휘도를 재고 장마다 평균 1.0 으로 정규화(밝기가 아니라 분포만 '
                    '가져오기 위해). 같은 막 군집끼리 평균. 1.0=평균적인 자리, >1=빛을 두는 자리, <1=비워두는 자리. '
                    '군집은 색 지표 7개로만 하고 구도는 그 안에서 평균만 낸다.' % (GW, GH)),
        '_전체평균': {k: round(float(X[:, KEYS.index(k)].mean()), 4) for k in KEYS},
        '_전체편차': {k: round(float(X[:, KEYS.index(k)].std()), 4) for k in KEYS},
        '_생성': time.strftime('%Y-%m-%d'),
        '막': {},
    }
    for i, act in enumerate(ACTS):
        m = (lab == assign[i])
        sel = X[m]
        picked = [r for r, keep in zip(rows, m) if keep]
        # 구도 지도 — 같은 막 군집의 정규화 지도를 평균낸다
        cmap = np.mean([r['_map'] for r in picked], axis=0)
        cmap = cmap / max(cmap.mean(), 1e-6)          # 평균 1.0 으로 다시 맞춘다
        db['막'][act] = {
            '표본수': int(len(sel)),
            '목표': {k: round(float(sel[:, KEYS.index(k)].mean()), 4) for k in KEYS},
            # 허용편차가 0 에 가까우면 적합도가 절벽이 된다 — 하한 0.03
            '허용편차': {k: round(float(max(sel[:, KEYS.index(k)].std(), 0.03)), 4) for k in KEYS},
            '구도': {k: round(float(np.mean([r[k] for r in picked])), 4) for k in COMP_KEYS},
            '구도편차': {k: round(float(np.std([r[k] for r in picked])), 4) for k in COMP_KEYS},
            # 행 우선(위→아래), 각 행은 왼→오른. 프론트가 그대로 읽는다.
            '구도지도': [[round(float(v), 3) for v in row] for row in cmap],
        }
        t = db['막'][act]['목표']
        print('  %s n=%3d  ' % (act, len(sel)) + '  '.join('%s %.3f' % (k, t[k]) for k in KEYS))
        cc = db['막'][act]['구도']
        print('      구도  무게중심(%.2f, %.2f)  중심/주변 %.2f  밝은띠 %.2f  |  지도 %.2f~%.2f'
              % (cc['cx'], cc['cy'], cc['vign'], cc['hband'], cmap.min(), cmap.max()))

    json.dump(db, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('저장:', OUT)


if __name__ == '__main__':
    main()
