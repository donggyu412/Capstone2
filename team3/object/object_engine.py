#!/usr/bin/env python3
"""
꿈 오브제 창발 엔진 — 시도 A (파티클)
캡스톤 디자인2 · 3팀 · 시스템 II (꿈 오브제)

오브제 PNG 를 그대로 띄우지 않는다. 투명 PNG 의 픽셀을 수천 개의 입자로 쪼개고,
입자들이 기승전결의 힘을 받으며 제자리를 찾아 '맺히고', 스토리의 물리 법칙대로 움직이다가 '풀린다'.

  무엇이 움직임을 정하나 (난수로 흐름을 정하지 않는다 — 스토리 기반)
    장면 순서        → 기·승·전·결 : 입자에 걸리는 힘의 종류 (ACTS)
    physics_laws    → 오브제별 동작 : 오브제가 주어인 법칙만 옮긴다 (LAW_RULES · GROUPS)
                      배경·소리 법칙은 배경 엔진·사운드 몫이라 건너뛰고 law_map.json 에 이유를 남긴다
    objects 순서    → 등장 순서 (스토리에 나오는 순서)
    main_emotion    → 색·난류에 얇게 곱한다 (EMOTIONS)
    입자 초기 배치  → 스토리 글로 만든 시드 — 같은 스토리면 같은 영상, 스토리가 바뀌면 바뀐다

  두 가지 출력
    오브제만     python object_engine.py
    배경과 통합  python object_engine.py --bg dream.mp4 --bg-json video.json --out integrated.mp4

  두 가지 그리기 방식 (--style)
    analog   부드러운 빛 입자 · 번짐 · 안개 — 아날로그 꿈 (기본)
    digital  격자에 맞물리는 사각 블록 · 평평한 색 · 통통 튀는 조립 — 로봇의 꿈 (추상·기하·단순·원초적)
    python object_engine.py --style digital

  빠른 미리보기 (장면당 10초 · 절반 해상도)
    python object_engine.py --scene-sec 10 --scale 0.5 --out preview.mp4
    ※ 등장·반전은 75초 기준으로 맞춘 움직임이라, 짧은 미리보기에서는 실제보다 급하게 보인다

  10/15 반영 (교수님 10/8 검토)
    점에서 시작하는 등장 (--emerge point · 기본)
      오브제마다 한 점에서 출발 — 앞 장면 잔해 중 그 자리에 가장 가까운 한 점에서 태어난다.
      격자 8칸 → 4칸 → 2칸 → 1칸 간격 입자 순서로 태어나 '점 → 성긴 윤곽 → 촘촘한 전체'로 약 16초에 걸쳐 드러난다.
      오브제 사이 간격 7.5초 · 원본 윤곽은 거의 다 드러난 뒤에야 옅게 깔린다. 예전 방식은 --emerge cloud.
    전(轉) 장면 반전 (--reversal 0.6 · 기본 = 전 장면 시작 후 45초 · 4장면 5분이면 전체 3:15)
      모였던 오브제 전부가 한순간에 터지듯 흩어졌다가(약 1초), 위아래가 뒤집히고 1.15배 커지고
      감정 색조의 반대색으로 바뀐 채 약 3초 안에 다시 모인다. 반전 시각은 결과 json 의 "reversal" 에 적힌다
      (배경·사운드를 이 시각에 맞춘다). 끄려면 --no-reversal.
    밝은·색 배경 대비 (--contrast · 통합이면 기본 1, 오브제만이면 0)
      배경이 밝은 자리일수록 오브제 몸통 둘레에 부드러운 어두운 받침을 깔고(어두운 자리에는 거의 없음),
      오브제 밝기가 바로 뒤 배경 밝기와 일정 이상 벌어지도록 색은 지킨 채 밝기만 맞춘다. 번짐 빛도 밝은 배경에서는 줄인다.
    병렬 렌더 (--jobs auto · 기본)
      장면마다 따로 동시에 렌더해 이어 붙인다. 각 장면은 앞 장면을 그리지 않고 계산만 빨리 감은 뒤 시작해서,
      한 줄로 돌린 것과 화소 단위로 같은 결과가 나온다(무손실 비교로 확인). 한 줄로 돌리려면 --jobs 1.

필요 패키지: pip install numpy pillow opencv-python imageio-ffmpeg
"""
import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# ─────────────────────────────────────────────────────────────
# 1. 기승전결 — 막마다 입자에 걸리는 힘의 종류
#    settle 제자리로 끌리는 힘 · fric 마찰(1에 가까울수록 미끄럽다) · turb 난류
#    swirl 오브제 중심을 도는 힘 · glow 번짐 빛 · ghost 원본 윤곽(옅게) · fog 안개
#    dissolve 풀리기 시작하는 시점(장면 안 비율)
# ─────────────────────────────────────────────────────────────
ACT_NAMES = ['기', '승', '전', '결']
RELEASE_SPAN = 0.10  # 풀리기 시작해서 마지막 입자가 놓일 때까지 (장면 안 비율)
ACTS = {
    '기': dict(settle=0.022, fric=0.90, turb=1.00, swirl=0.00, glow=0.80, ghost=0.07, fog=0.10, spread=1.00, dissolve=0.79),
    '승': dict(settle=0.060, fric=0.86, turb=0.22, swirl=0.00, glow=1.00, ghost=0.16, fog=0.04, spread=0.60, dissolve=0.79),
    '전': dict(settle=0.034, fric=0.90, turb=0.45, swirl=0.55, glow=1.55, ghost=0.10, fog=0.04, spread=0.80, dissolve=0.79),
    '결': dict(settle=0.026, fric=0.92, turb=0.30, swirl=0.00, glow=0.70, ghost=0.20, fog=0.35, spread=0.90, dissolve=0.78),
}

# 감정 — 1팀 7종. 값은 1.0 근처에서 얇게 곱한다 (intensity 만큼만 중립에서 밀어낸다)
EMOTIONS = {
    '기쁨': dict(sat=1.12, warm=+0.10, turb=0.90, glow=1.10),
    '슬픔': dict(sat=0.85, warm=-0.10, turb=0.85, glow=0.90),
    '분노': dict(sat=1.12, warm=+0.12, turb=1.20, glow=1.10),
    '공포': dict(sat=0.88, warm=-0.08, turb=1.22, glow=0.92),
    '놀람': dict(sat=1.05, warm=+0.02, turb=1.12, glow=1.15),
    '혐오': dict(sat=0.85, warm=-0.06, turb=0.95, glow=0.88),
    '중립': dict(sat=1.00, warm=0.00, turb=1.00, glow=1.00),
}

# 전(轉) 반전 때 오브제가 바뀌는 색 — 배경 감정 색조(기쁨 금빛 · 슬픔 파랑 · 분노 붉음 · 공포 남보라 · 놀람 자홍 · 혐오 풀빛)의 반대색
REVERSAL_TINT = {
    '기쁨': (0.35, 0.75, 1.00), '슬픔': (1.00, 0.68, 0.30), '분노': (0.30, 0.90, 0.90),
    '공포': (1.00, 0.72, 0.30), '놀람': (0.60, 1.00, 0.40), '혐오': (1.00, 0.42, 0.80), '중립': (1.00, 0.72, 0.30),
}

# ─────────────────────────────────────────────────────────────
# 2. 법칙 → 오브제 동작
#    GROUPS : 오브제 이름에 이 말이 있으면 그 무리. 법칙 문장에 무리의 낱말이 있으면 그 오브제가 주어/대상
#    LAW_RULES : 법칙 문장의 낱말 → 동작
# ─────────────────────────────────────────────────────────────
GROUPS = {
    '서류철': ['서류철', '서류', '책장', '페이지', '표지'],
    '종이': ['종이', '글자', '글씨'],
    '항해일지': ['항해일지', '일지', '마지막 장', '얼룩'],
    '그림자': ['그림자', '형상', '팔이', '팔은'],
    '웅덩이': ['웅덩이', '냉동액'],
    '물방울': ['물방울'],
    '타일': ['타일', '균열', '금이', '금은', '바닥의 금'],
    '손': ['손', '손끝'],
}
LAW_RULES = [
    ('float',      ['떠', '부유', '공중', '닿지 않']),
    ('glide',      ['미끄러지듯']),
    ('weightless', ['무게가 사라', '가벼워', '무게를 잃']),
    ('heavy',      ['무거워']),
    ('rotate',     ['회전']),
    ('ash',        ['바스러', '재처럼', '부서']),
    ('vanish',     ['사라짐', '사라지', '지워', '없어']),
    ('stretch',    ['늘어', '길게', '비율']),
    ('flutter',    ['팔락', '넘어가', '넘어감']),
    ('crack',      ['균열', '금이', '벌어']),
    ('precede',    ['먼저', '앞서', '역전', '닿기도 전', '닿기 전']),
    ('flicker',    ['나타나고 사라', '있다가 없다가', '임의로 변']),
    ('still',      ['변하지 않', '흔들리지 않', '잔물결 하나']),
    ('recede',     ['멀어', '좁혀지지 않']),
]
# 먼저 보고 지우는 표현 — 이 말 안의 낱말이 다른 동작으로 두 번 잡히지 않게
PRIORITY = ['flicker', 'weightless', 'precede']
BEHAVIOR_KO = {
    'float': '부유', 'glide': '미끄러짐', 'weightless': '무게 잃음', 'heavy': '무거워짐', 'rotate': '회전',
    'ash': '재처럼 바스러짐', 'vanish': '지워짐', 'stretch': '늘어남', 'flutter': '팔락임', 'crack': '갈라짐',
    'precede': '인과 역전(결과가 먼저)', 'flicker': '있다 없다 함', 'still': '미동 없음', 'recede': '멀어짐',
}


def object_groups(name):
    return [g for g, words in GROUPS.items() if g in name or any(w in name for w in words)]


def analyze_scene(sc):
    """physics_laws 를 오브제별 동작 세기(0~1)로 옮긴다. 옮긴 근거를 log 로 남긴다."""
    objs = sc.get('objects') or []
    groups = [object_groups(o) for o in objs]
    beh = [dict() for _ in objs]
    log = []
    for law in sc.get('physics_laws') or []:
        hits = [i for i, gs in enumerate(groups) if any(any(w in law for w in GROUPS[g]) for g in gs)]
        found, rest = [], law
        for b in PRIORITY + [r for r, _ in LAW_RULES if r not in PRIORITY]:
            words = dict(LAW_RULES)[b]
            hit = [w for w in words if w in rest]
            if hit:
                found.append(b)
                if b in PRIORITY:  # '무게가 사라지고' 의 '사라' 가 지워짐으로 다시 잡히지 않게
                    for w in hit:
                        rest = rest.replace(w, ' ')
        if not hits:
            reason = '사운드 몫' if '소리' in law else '배경 몫 (오브제가 주어가 아님)'
            log.append({'law': law, 'applied': False, 'reason': reason})
            continue
        if not found:
            log.append({'law': law, 'applied': False, 'objects': [objs[i] for i in hits], 'reason': '옮길 동작 낱말 없음'})
            continue
        applied = {}
        for b in found:
            targets = hits
            if b == 'crack':  # 갈라짐은 타일 무리에만 — 없으면 걸린 오브제 전부
                tile = [i for i in hits if '타일' in groups[i]]
                targets = tile or hits
            if b == 'weightless':
                for i in targets:
                    beh[i]['float'] = min(1.0, beh[i].get('float', 0) + 0.6)
            for i in targets:
                beh[i][b] = min(1.0, beh[i].get(b, 0) + 1.0)
            applied[BEHAVIOR_KO[b]] = [objs[i] for i in targets]
        log.append({'law': law, 'applied': True, 'behaviors': applied})
    return beh, log


# ─────────────────────────────────────────────────────────────
# 3. 도우미
# ─────────────────────────────────────────────────────────────
def smoothstep(a, b, x):
    t = np.clip((x - a) / np.maximum(b - a, 1e-6), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def find_font(size):
    for p in ['C:/Windows/Fonts/malgun.ttf', 'C:/Windows/Fonts/malgunbd.ttf',
              '/System/Library/Fonts/AppleSDGothicNeo.ttc',
              '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
              '/usr/share/fonts/truetype/nanum/NanumGothic.ttf']:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                pass
    return None


def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return 'ffmpeg'


def load_objects_index(obj_dir, scene_no, names):
    """output_objects/scene_NN/obj_i_이름.png — 없으면 경고하고 건너뛴다"""
    d = Path(obj_dir) / f'scene_{scene_no:02d}'
    files = []
    for i, n in enumerate(names, 1):
        p = d / f"obj_{i}_{n.replace(' ', '_')}.png"
        if not p.exists():
            cand = sorted(d.glob(f'obj_{i}_*.png'))
            p = cand[0] if cand else None
        if p is None:
            print(f'  ! 장면 {scene_no} 오브제 {i} ({n}) PNG 가 없어 건너뜀')
        files.append(p)
    return files


# ─────────────────────────────────────────────────────────────
# 4. 장면 하나 — 입자를 만들고 매 프레임 움직인다
# ─────────────────────────────────────────────────────────────
class Scene:
    def __init__(self, sc, idx, n_scenes, files, W, H, prev_cloud, rng, style='analog', cell=12,
                 emerge='point', reversal=0.6, quiet=False, seed_glow=1.0, dissolve_shift=0.0):
        self.W, self.H = W, H
        self.style, self.cell = style, cell
        digital = style == 'digital'
        # 디지털 — 더 세게 끌리고 덜 미끄러워 제자리를 지나쳤다 돌아온다(통통 튄다) · 블록이 커서 난류도 크게
        self.k_mul, self.fric_off, self.noise_mul = (1.8, -0.08, 1.6) if digital else (1.0, 0.0, 1.0)
        self.sc = sc
        self.act = ACT_NAMES[min(3, idx * 4 // max(1, n_scenes))]
        self.A = ACTS[self.act]
        me = sc.get('main_emotion') or {}
        e = EMOTIONS.get(me.get('label'), EMOTIONS['중립'])
        k = float(me.get('intensity') or 0.0)
        self.emo = {key: 1 + (val - 1) * k if key != 'warm' else val * k for key, val in e.items()}
        self.emo_label = me.get('label') or '중립'
        self.beh, self.law_log = analyze_scene(sc)
        names = sc.get('objects') or []
        keep = [i for i, f in enumerate(files) if f is not None]
        self.names = [names[i] for i in keep]
        beh = [self.beh[i] for i in keep]
        n = len(keep)
        self.n = n

        # 오브제 자리 — 가로로 고르게, 위아래로 살짝 어긋나게
        spacing = min(0.27, 0.80 / max(n, 1))
        box_h = H * (0.42 if n <= 3 else 0.36)
        box_w = W * spacing * 0.95
        anchors, sizes, ghosts = [], [], []
        P_local, P_col, P_alpha, P_obj, P_thr, P_grp, P_birth, P_spawn = [], [], [], [], [], [], [], []
        P_seed = []
        step = max(1, round(2 * H / 1080))
        for j, oi in enumerate(keep):
            img = Image.open(files[oi]).convert('RGBA')
            bb = img.getchannel('A').point(lambda a: 255 if a > 20 else 0).getbbox()
            if bb:
                img = img.crop(bb)
            s = min(box_w / img.width, box_h / img.height)
            dw, dh = max(8, int(img.width * s)), max(8, int(img.height * s))
            img = img.resize((dw, dh), Image.LANCZOS)
            arr = np.asarray(img).astype(np.float32) / 255.0
            ax = W * (0.5 + (j - (n - 1) / 2) * spacing)
            ay = H * (0.53 + (0.035 if j % 2 else -0.035))
            anchors.append((ax, ay))
            sizes.append((dw, dh))
            prem = arr.copy()
            prem[..., :3] *= prem[..., 3:4]
            ghosts.append(prem)

            if digital:
                # 블록 하나 = 입자 하나 — 오브제를 격자 칸으로 줄여 칸마다 평균 색을 뽑는다
                gw, gh = max(2, round(dw / (cell * 0.8))), max(2, round(dh / (cell * 0.8)))  # 칸보다 조금 촘촘히 — 구멍 방지
                small = np.asarray(img.resize((gw, gh), Image.BOX)).astype(np.float32) / 255.0
                ys, xs = np.mgrid[0:gh, 0:gw]
                a = small[ys, xs, 3]
                m = a > 0.45
                xs, ys = xs[m], ys[m]
                col = small[ys, xs, :3] / np.maximum(small[ys, xs, 3:4], 1e-3)
                a = np.ones(len(xs), np.float32)
                lx, ly = (xs + 0.5) * dw / gw - dw / 2, (ys + 0.5) * dh / gh - dh / 2
                gi, gj = xs, ys
            else:
                ys, xs = np.mgrid[0:dh:step, 0:dw:step]
                a = arr[ys, xs, 3]
                m = a > 0.25
                xs, ys, a = xs[m], ys[m], a[m]
                cap = 30000
                if len(xs) > cap:
                    sel = rng.choice(len(xs), cap, replace=False)
                    xs, ys, a = xs[sel], ys[sel], a[sel]
                col = arr[ys, xs, :3]
                gi, gj = xs // step, ys // step
                # 표본 격자가 무늬로 비치지 않게 칸 안에서 살짝 흔든다 (난수 대신 번호로 정해 결과가 매번 같다)
                hsh = np.arange(len(xs), dtype=np.float64)
                jx = (np.modf(np.sin(hsh * 12.9898) * 43758.5453)[0] % 1.0) - 0.5
                jy = (np.modf(np.sin(hsh * 78.233) * 12345.6789)[0] % 1.0) - 0.5
                lx, ly = xs - dw / 2 + jx * step * 0.9, ys - dh / 2 + jy * step * 0.9
            cnt = len(xs)
            # 점 → 성긴 윤곽 → 촘촘한 전체 : 격자 8칸 · 4칸 · 2칸 · 1칸 간격의 입자 순서로 태어난다
            lv = np.full(cnt, 3.0)
            lv[(gi % 2 == 0) & (gj % 2 == 0)] = 2
            lv[(gi % 4 == 0) & (gj % 4 == 0)] = 1
            lv[(gi % 8 == 0) & (gj % 8 == 0)] = 0
            b = beh[j]
            # 풀리는 순서 — 지워짐은 위에서부터(글자부터 지워진다) · 재처럼은 가장자리부터 · 그 밖은 흩어서
            r = np.sqrt((lx / (dw / 2)) ** 2 + (ly / (dh / 2)) ** 2)
            if b.get('vanish'):
                thr = 0.8 * ((ly + dh / 2) / dh) + 0.2 * rng.random(cnt)
            elif b.get('ash'):
                thr = 0.7 * (1 - np.clip(r, 0, 1)) + 0.3 * rng.random(cnt)
            else:
                thr = rng.random(cnt)
            # 태어나는 자리
            #   point : 한 점에서 시작한다 — 앞 장면 잔해 중 이 오브제 자리에 가장 가까운 한 점 (장면 사이가 이어진다)
            #           결과가 먼저(인과 역전)면 그 점이 오브제 위쪽에 있어 아래로 내려앉으며 드러난다
            #   cloud : 예전 방식 — 넓은 구름에서 모인다
            if emerge == 'point':
                if b.get('precede'):
                    seed_pt = np.array([ax, ay - H * 0.30])
                elif prev_cloud is not None and len(prev_cloud):
                    seed_pt = prev_cloud[np.argmin(((prev_cloud - [ax, ay]) ** 2).sum(1))]
                else:
                    seed_pt = np.array([ax, ay])
                sp = seed_pt + rng.normal(0, 1.5 * H / 1080, (cnt, 2))
                P_seed.append(seed_pt)
            elif b.get('precede'):
                sp = np.stack([ax + lx * 1.6 + rng.normal(0, dw * 0.25, cnt),
                               ay - H * (0.15 + 0.55 * rng.random(cnt))], 1)
            elif prev_cloud is not None and len(prev_cloud):
                sp = prev_cloud[rng.integers(0, len(prev_cloud), cnt)] + rng.normal(0, H * 0.03, (cnt, 2))
            else:
                rad = H * 0.55 * self.A['spread']
                ang = rng.random(cnt) * 2 * np.pi
                rr = rad * np.sqrt(rng.random(cnt))
                sp = np.stack([ax + rr * np.cos(ang), ay + rr * np.sin(ang)], 1)
            P_local.append(np.stack([lx, ly], 1)); P_col.append(col); P_alpha.append(a)
            P_obj.append(np.full(cnt, j)); P_thr.append(thr); P_grp.append(np.clip(((ly + dh / 2) / dh * 8).astype(int), 0, 7))  # 가로 띠 8장 — 책장처럼 한 장씩 있다 없다 한다
            P_birth.append((lv + rng.random(cnt)) / 4 if emerge == 'point' else rng.random(cnt)); P_spawn.append(sp)

        # 오브제별 시간표 (장면 안 비율 u)
        #   point : 점에서 시작해 약 16초(0.22)에 걸쳐 드러난다 · 오브제 사이 간격 0.10(7.5초)
        self.emerge = emerge
        if emerge == 'point':
            gap_e = min(0.10, 0.40 / max(n - 1, 1))
            self.enter = np.array([0.015 + gap_e * j for j in range(n)])  # 첫 점은 장면 시작 약 1초 뒤
            self.formed = self.enter + 0.22
        else:
            self.enter = np.array([0.04 + 0.13 * j for j in range(n)])
            self.formed = self.enter + 0.16
        base = self.A['dissolve'] + dissolve_shift
        dis = np.array([min(base + 0.015 * j, 0.86) for j in range(n)])
        pre = np.array([b.get('precede', 0) for b in beh])
        self.dissolve = np.maximum(dis - 0.08 * pre, self.formed + 0.08)  # 결과가 먼저면 조금 일찍 풀린다
        # 전(轉) 반전 — 모였던 형상이 한순간에 터지듯 흩어졌다가, 위아래가 뒤집히고 크기·색이 바뀐 채 다시 모인다
        self.rev = reversal if (reversal is not None and self.act == '전') else None
        if self.rev is not None:
            self.dissolve = np.maximum(self.dissolve, self.rev + 0.10)
        self.rev_fired = False
        # 시작점 빛 — 오브제가 드러나기 전, 그 자리에 은은하게 깜박이는 빛점 (점에서 시작함이 눈에 보이게)
        self.seed_glow_k = seed_glow if emerge == 'point' else 0.0
        self.seed_pts = np.array(P_seed, np.float32) if len(P_seed) == n else None
        self.beh_arr = {k2: np.array([b.get(k2, 0.0) for b in beh]) for k2, _ in LAW_RULES}
        self.anchors = np.array(anchors, np.float32)
        self.sizes = np.array(sizes, np.float32)
        self.ghosts = ghosts
        self.phase = rng.random(n) * 2 * np.pi
        self.crack_ang = rng.uniform(-0.5, 0.5, n)

        self.local = np.concatenate(P_local).astype(np.float32)
        col = np.concatenate(P_col)
        # 원래 색에서 밝기·채도를 먼저 잰다 (감정 색을 입힌 뒤에 재면 밤색이 무채색으로 오판된다)
        lum = col @ np.array([0.299, 0.587, 0.114])
        chroma = col.max(1) - col.min(1)
        # 감정 색 — 채도·난색 (얇게)
        g = col.mean(1, keepdims=True)
        col = g + (col - g) * self.emo['sat']
        col[:, 0] += self.emo['warm'] * 0.3
        col[:, 2] -= self.emo['warm'] * 0.3
        # 어두운 무채색(검은 그림자 등)은 어두운 배경에 묻히지 않게 차가운 테두리 빛을 얹고,
        # 어두운 유채색(밤색 표지 등)은 색을 지킨 채 밝기만 올린다
        vmax = np.concatenate(P_col).max(1)
        sat_hsv = chroma / np.maximum(vmax, 1e-3)
        achrom = (sat_hsv < 0.18) | (vmax < 0.06)
        lift = np.clip(0.30 - lum, 0, None) * achrom
        col += lift[:, None] * np.array([0.55, 0.70, 1.00])
        dark_col = (lum < 0.30) & ~achrom
        col[dark_col] *= ((0.30 / np.maximum(lum[dark_col], 0.03)) ** 0.7)[:, None]
        if digital:
            # 원초적 — 채도를 올리고 색을 5단계로 눌러 면을 평평하게 칠한다
            g = col.mean(1, keepdims=True)
            col = posterize_hsv(np.clip(g + (col - g) * 1.3, 0, 1))
        self.col = np.clip(col, 0, 1).astype(np.float32)
        oid = np.concatenate(P_obj)
        sc_col = []
        for j in range(n):
            m = self.col[oid == j].mean(0) if (oid == j).any() else np.ones(3, np.float32)
            m = 0.55 * m + 0.45  # 오브제 색을 띤 밝은 빛
            sc_col.append(m / max(float(m @ np.array([0.299, 0.587, 0.114])), 1e-3) * 0.95)
        self.seed_col = np.clip(np.array(sc_col, np.float32), 0, 1)
        tint = np.array(REVERSAL_TINT.get(self.emo_label, REVERSAL_TINT['중립']), np.float32)
        self.rev_tint = tint
        lum2 = self.col @ np.array([0.299, 0.587, 0.114], np.float32)
        rcol = np.clip(np.maximum(lum2, 0.25)[:, None] * tint * 1.25 + 0.12 * self.col, 0, 1)
        self.rev_col = (posterize_hsv(rcol) if digital else rcol).astype(np.float32)
        self.alpha = np.concatenate(P_alpha).astype(np.float32)
        self.obj = np.concatenate(P_obj)
        self.thr = np.concatenate(P_thr).astype(np.float32)
        self.grp = np.concatenate(P_grp)
        stagger = np.where(np.array([b.get('precede', 0) for b in beh])[self.obj] > 0, 0.14, 0.06)
        if emerge == 'point':
            stagger = np.full(len(self.obj), 0.16)  # 태어나는 데 12초 — 점이 먼저, 촘촘한 입자가 나중
        self.birth = self.enter[self.obj] + stagger * np.concatenate(P_birth)  # 결과가 먼저면 비처럼 오래 내려앉는다
        self.pos = np.concatenate(P_spawn).astype(np.float32)
        self.vel = np.zeros_like(self.pos)
        self.released = np.zeros(len(self.pos), bool)
        if not quiet:
            rv = f' · 반전 {self.rev:.2f}' if self.rev is not None else ''
            print(f'  장면 {sc.get("scene")} · {self.act} · {self.emo_label} · 오브제 {n}개 · 입자 {len(self.pos):,}{rv}')

    def rev_phase(self, u):
        """반전 진행 — (뒤집힘 0/1, 끌림 배율, 색 섞임)"""
        if self.rev is None or u < self.rev:
            return 0.0, 1.0, 0.0
        # 약 1초 흩어졌다가 3초 안에 다시 모인다 — 다시 모일 때는 평소보다 2배 세게 끌어 형태를 빨리 세운다
        pull = float(smoothstep(self.rev + 0.012, self.rev + 0.05, u)) * (1 + float(smoothstep(self.rev + 0.012, self.rev + 0.03, u)) * (1 - float(smoothstep(self.rev + 0.08, self.rev + 0.12, u))))
        return 1.0, pull, float(smoothstep(self.rev, self.rev + 0.03, u))

    # 오브제 하나의 '지금 모양' — 동작 세기 × 시간
    def transforms(self, u, t):
        H, W, B = self.H, self.W, self.beh_arr
        F = smoothstep(self.enter, self.formed, u)
        hold = smoothstep(self.formed, self.dissolve, u)
        dy = -B['float'] * (0.06 * H * F + 0.012 * H * np.sin(2 * np.pi * t / 6.5 + self.phase))
        dy -= B['weightless'] * 0.05 * H * hold
        dy += B['heavy'] * 0.04 * H * hold
        dx = B['glide'] * 0.08 * W * np.sin(2 * np.pi * t / 22 + self.phase)
        ang = B['rotate'] * 2 * np.pi * t / 10
        sx = np.cos(ang)
        sx = np.where(np.abs(sx) < 0.12, np.sign(sx + 1e-9) * 0.12, sx)
        sx = np.where(B['rotate'] > 0, sx, 1.0)
        tilt = B['rotate'] * 0.25 * np.sin(t / 4 + self.phase)
        scale = 1 - B['recede'] * 0.4 * u
        stretch = B['stretch'] * (0.7 * hold + 0.05 * np.sin(t / 3 + self.phase))
        c0 = np.where(B['precede'] > 0, self.enter, self.formed)
        steps = 4 * smoothstep(c0, self.dissolve, u)
        stair = np.floor(steps) + smoothstep(0.0, 0.25, steps - np.floor(steps))  # 한 뼘씩 벌어진다
        gap = B['crack'] * 0.012 * H * stair
        burst = np.maximum(0, np.sin(2 * np.pi * t / 4.5 + self.phase)) ** 3
        flut = B['flutter'] * 0.035 * H * burst
        flip, _, _ = self.rev_phase(u)
        if flip:
            tilt = tilt + np.pi  # 위아래가 뒤집힌 채 다시 모인다
            scale = scale * 1.15
        return F, dx, dy, sx, tilt, scale, stretch, gap, flut

    def step(self, u, t):
        self.u_now, self.t_now = u, t
        A, emo = self.A, self.emo
        F, dx, dy, sx, tilt, scale, stretch, gap, flut = self.transforms(u, t)
        o = self.obj
        half = self.sizes / 2
        lx, ly = self.local[:, 0].copy(), self.local[:, 1].copy()
        # 늘어남 — 아래로 갈수록 더 (팔이 바닥까지 늘어진다)
        ly = np.where(ly > 0, ly * (1 + stretch[o]), ly * (1 + 0.15 * stretch[o]))
        # 팔락임 — 가장자리일수록 크게 물결친다
        lx = lx + flut[o] * np.sin(ly / half[o, 1] * np.pi * 1.5 + 6 * t) * np.abs(lx) / half[o, 0]
        # 갈라짐 — 비스듬한 선을 사이에 두고 두 쪽이 벌어진다
        nx, ny = np.cos(self.crack_ang)[o], np.sin(self.crack_ang)[o]
        side = np.sign(lx * nx + ly * ny + 1e-6)
        lx = lx + side * nx * gap[o] / 2
        ly = ly + side * ny * gap[o] / 2
        # 회전(뒤집힘) · 기울기 · 멀어짐
        lx = lx * sx[o] * scale[o]
        ly = ly * scale[o]
        ct, st = np.cos(tilt)[o], np.sin(tilt)[o]
        hx = self.anchors[o, 0] + dx[o] + lx * ct - ly * st
        hy = self.anchors[o, 1] + dy[o] + lx * st + ly * ct
        home = np.stack([hx, hy], 1)

        born = u >= self.birth
        rel_u = self.dissolve[o] + RELEASE_SPAN * self.thr
        self.released |= u >= rel_u
        Fi = F[o]
        still = self.beh_arr['still'][o]
        k = A['settle'] * Fi * (1 + 0.5 * still) * self.k_mul
        k = np.where(self.released, 0.0, k)
        flip, pull, cmix = self.rev_phase(u)
        if flip and not self.rev_fired:  # 반전 순간 — 모든 입자를 바깥으로 한 번에 터뜨린다
            self.rev_fired = True
            live = born & ~self.released
            d = self.pos - self.anchors[o]
            d = d / (np.linalg.norm(d, axis=1, keepdims=True) + 1.0)
            spd = self.H * 0.022 * (0.6 + 0.8 * self.thr)
            self.vel[live] += d[live] * spd[live, None]
        k = k * pull
        # 난류 — 위치마다 세기·방향이 다른 결 (형태가 서기 전일수록 거세다)
        p = self.pos
        T = t * 0.8
        nxf = np.sin(p[:, 1] * 0.011 + T * 0.7 + 1.3) + 0.5 * np.sin(p[:, 0] * 0.023 - T * 1.1 + 0.4)
        nyf = np.cos(p[:, 0] * 0.013 + T * 0.9 + 2.1) + 0.5 * np.cos(p[:, 1] * 0.019 + T * 0.6 + 0.7)
        noise = np.stack([nxf, nyf], 1).astype(np.float32)
        turb = A['turb'] * emo['turb'] * (1 - 0.9 * still) * (0.35 + 0.65 * (1 - Fi))
        acc = (home - p) * k[:, None] + noise * (0.55 * self.noise_mul * turb)[:, None]
        if A['swirl'] > 0:
            rv = p - self.anchors[o]
            r = np.linalg.norm(rv, axis=1, keepdims=True) + 1.0
            tang = np.stack([-rv[:, 1], rv[:, 0]], 1) / r
            acc += tang * (A['swirl'] * 0.35) * (~self.released)[:, None]
        # 풀린 입자 — 재처럼은 위로 날리고 · 지워짐은 제자리에서 꺼지고 · 그 밖은 안개처럼 번진다
        ash, van = self.beh_arr['ash'][o], self.beh_arr['vanish'][o]
        rel = self.released
        up = np.where(ash > 0, -0.06, -0.012)
        acc[rel, 1] += up[rel]
        acc[rel] += noise[rel] * np.where(van[rel] > 0, 0.15, np.where(ash[rel] > 0, 0.9, 0.5))[:, None]
        fric = np.where(rel, 0.96, A['fric'] + 0.06 * still + self.fric_off).astype(np.float32)
        acc[~born] = 0
        self.vel = self.vel * fric[:, None] + acc
        self.vel[~born] = 0
        self.pos = (p + self.vel).astype(np.float32)

        # 보이는 정도
        v = self.alpha * smoothstep(0, 0.03, u - self.birth)
        if self.emerge == 'point':  # 막 태어난 성긴 입자는 더 밝게 — 형태가 서기 전에도 무엇이 자라고 있는지 보이게
            v = v * (1 + 1.2 * (1 - F[o]))
        v = v * (1 - smoothstep(rel_u, rel_u + 0.05, u))
        fl = self.beh_arr['flicker'][o]
        if fl.any():  # 있다 없다 — 무리마다 1.4초에 한 번씩 켜지고 꺼진다 (페이지 수가 변한다)
            tick = int(t / 1.4)
            on = ((self.grp * 2654435761 + tick * 40503 + o * 97) % 7) > 2
            v = v * (1 - fl * (~on) * 0.85)
        if self.style == 'digital':
            v = np.round(v * 2) / 2  # 디지털 — 서서히 꺼지지 않고 켜짐·반·꺼짐 세 단계로 깜박인다
        ash_col = np.where((ash > 0) & rel, 1, 0)[:, None]
        base_col = self.col if cmix == 0 else self.col * (1 - cmix) + self.rev_col * cmix
        col = base_col * (1 - 0.6 * ash_col) + 0.55 * ash_col * np.array([0.75, 0.72, 0.70], np.float32)
        return v.astype(np.float32), col.astype(np.float32), F, dx, dy, sx, tilt, scale, gap

    def seed_lights(self, u, t):
        """시작점 빛 — (위치, 세기, 색). 오브제가 태어나기 1.5초 전부터 깜박이다가 형태가 서면서 사라진다"""
        if self.seed_pts is None or self.seed_glow_k <= 0:
            return None
        on = smoothstep(self.enter - 0.02, self.enter, u) * (1 - smoothstep(self.enter + 0.10, self.enter + 0.20, u))
        pulse = 0.75 + 0.25 * np.sin(2 * np.pi * t / 1.6 + self.phase)
        k = on * pulse * self.seed_glow_k
        if not (k > 0.01).any():
            return None
        return self.seed_pts, k, self.seed_col

    def ghost_layer(self, u, F, dx, dy, sx, tilt, scale, gap, canvas_rgb, canvas_a):
        """원본 PNG 를 아주 옅게 — 입자가 흩어져도 무엇인지 읽히도록 윤곽을 받친다"""
        W, H = self.W, self.H
        D = smoothstep(self.dissolve, self.dissolve + 0.10, u)
        GF = F ** 3 if self.emerge == 'point' else F
        flip, pull, _ = self.rev_phase(u)
        rev_k = pull if flip else 1.0
        for j in range(self.n):
            g = self.A['ghost'] * GF[j] * rev_k * (1 - D[j]) * (1 + 0.8 * self.beh_arr['still'][j]) * (1 - 0.6 * min(1, gap[j] / (0.05 * H + 1e-6)))
            if g < 0.004:
                continue
            img = self.ghosts[j]
            h, w = img.shape[:2]
            a, b_ = sx[j] * scale[j], scale[j]
            c, s = math.cos(tilt[j]), math.sin(tilt[j])
            M = np.array([[a * c, -b_ * s, 0], [a * s, b_ * c, 0]], np.float32)
            M[:, 2] = np.array([self.anchors[j, 0] + dx[j], self.anchors[j, 1] + dy[j]]) - M[:, :2] @ np.array([w / 2, h / 2])
            corners = np.array([[0, 0], [w, 0], [0, h], [w, h]], np.float32) @ M[:, :2].T + M[:, 2]
            x0, y0 = np.floor(corners.min(0)).astype(int)
            x1, y1 = np.ceil(corners.max(0)).astype(int)
            x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
            if x1 <= x0 or y1 <= y0:
                continue
            M2 = M.copy(); M2[:, 2] -= [x0, y0]
            roi = cv2.warpAffine(img, M2, (x1 - x0, y1 - y0), flags=cv2.INTER_LINEAR, borderValue=0)
            rgb = roi[..., :3]
            if flip:  # 반전 뒤에는 원본 윤곽도 반대색으로 — 흰 원본이 비쳐 하얗게 번지지 않게
                rgb = (rgb @ LUMW)[..., None] * self.rev_tint * 1.25
            canvas_rgb[y0:y1, x0:x1] += rgb * g
            canvas_a[y0:y1, x0:x1] += roi[..., 3] * g

    def cloud(self):
        return self.pos.copy()


# ─────────────────────────────────────────────────────────────
# 5. 배경 — 오브제만일 때는 어두운 바탕, 통합일 때는 배경 영상
# ─────────────────────────────────────────────────────────────
class Background:
    def __init__(self, W, H, path=None, json_path=None, n_scenes=4, scene_sec=75.0):
        self.W, self.H = W, H
        self.cap = None
        if path:
            self.cap = cv2.VideoCapture(str(path))
            if not self.cap.isOpened():
                sys.exit(f'배경 영상을 열 수 없습니다: {path}')
            self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 60
            self.total = self.cap.get(cv2.CAP_PROP_FRAME_COUNT) / self.fps
            starts = None
            if json_path and Path(json_path).exists():
                vj = json.load(open(json_path, encoding='utf-8'))
                starts = [float(s.get('start_sec', 0)) for s in vj.get('scenes', [])]
            if not starts or len(starts) < n_scenes:
                starts = [self.total * k / n_scenes for k in range(n_scenes)]
            self.starts = starts[:n_scenes] + [self.total]
            self.idx = -1
            self.frame = None
            print(f'  배경 영상 {path} · {self.total:.1f}초 · {self.fps:.0f}fps · 장면 시작 {[round(s, 1) for s in self.starts[:-1]]}')
        else:
            yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
            r = np.sqrt(((xx - W / 2) / W) ** 2 + ((yy - H * 0.52) / H) ** 2)
            k = np.clip(1 - r * 1.6, 0, 1)[..., None]
            self.dark = (np.array([0.016, 0.016, 0.026]) * (1 - k) + np.array([0.060, 0.064, 0.090]) * k).astype(np.float32)
        self.scene_sec = scene_sec

    def get(self, scene_i, tau):
        if self.cap is None:
            return self.dark.copy()
        a, b = self.starts[scene_i], self.starts[scene_i + 1]
        bt = a + (b - a) * min(tau / self.scene_sec, 0.9999)
        j = int(bt * self.fps)
        if j < self.idx or j > self.idx + 240:  # 뒤로 가거나 많이 건너뛸 때만 탐색
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, j)
            self.idx = j - 1
        while self.idx < j:
            ok = self.cap.grab()
            if not ok:
                break
            self.idx += 1
            if self.idx == j:
                ok, fr = self.cap.retrieve()
                if ok:
                    fr = cv2.resize(fr, (self.W, self.H), interpolation=cv2.INTER_AREA)
                    self.frame = cv2.cvtColor(fr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        if self.frame is None:
            return np.zeros((self.H, self.W, 3), np.float32)
        return self.frame.copy()


# ─────────────────────────────────────────────────────────────
# 6. 그리기
# ─────────────────────────────────────────────────────────────
def splat(pos, v, col, W, H):
    x = np.round(pos[:, 0]).astype(np.int64)
    y = np.round(pos[:, 1]).astype(np.int64)
    m = (v > 0.003) & (x >= 0) & (x < W) & (y >= 0) & (y < H)
    idx = y[m] * W + x[m]
    w = v[m]
    out = np.empty((H, W, 4), np.float32)
    out[..., 3] = np.bincount(idx, weights=w, minlength=W * H).reshape(H, W)
    for c in range(3):
        out[..., c] = np.bincount(idx, weights=w * col[m, c], minlength=W * H).reshape(H, W)
    return out


def posterize_hsv(rgb):
    """색을 몇 단계로 누른다 — 색상 15° · 채도 4단계 · 밝기 6단계 (밤색이 회색으로 뭉개지지 않게 색상은 지킨다)"""
    shp = rgb.shape
    hsv = cv2.cvtColor(np.clip(rgb, 0, 1).reshape(-1, 1, 3).astype(np.float32), cv2.COLOR_RGB2HSV)
    hsv[..., 0] = (np.round(hsv[..., 0] / 15) * 15) % 360
    hsv[..., 1] = np.round(hsv[..., 1] * 3) / 3
    hsv[..., 2] = np.round(hsv[..., 2] * 5) / 5
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB).reshape(shp)


def render_digital(pos, v, col, W, H, cell):
    """디지털 — 입자를 화면 격자 칸에 떨어뜨려 칸마다 하나의 평평한 색 블록으로 칠한다"""
    Wg, Hg = -(-W // cell), -(-H // cell)
    gx = np.floor(pos[:, 0] / cell).astype(np.int64)
    gy = np.floor(pos[:, 1] / cell).astype(np.int64)
    m = (v > 0.01) & (gx >= 0) & (gx < Wg) & (gy >= 0) & (gy < Hg)
    idx = gy[m] * Wg + gx[m]
    w = v[m]
    ws = np.bincount(idx, weights=w, minlength=Wg * Hg)
    c = np.stack([np.bincount(idx, weights=w * col[m, k], minlength=Wg * Hg) for k in range(3)], 1) / (ws[:, None] + 1e-6)
    a = 1 - np.exp(-ws * 2.0)
    a = np.where(a > 0.55, 1.0, np.where(a > 0.2, 0.5, 0.0))
    c = posterize_hsv(c)
    up = lambda x: np.repeat(np.repeat(x.reshape(Hg, Wg, -1), cell, 0), cell, 1)[:H, :W]
    return up(c).astype(np.float32), up(a)[..., 0].astype(np.float32)


LUMW = np.array([0.299, 0.587, 0.114], np.float32)


def contrast_prepare(bg, objA, strength, H, W):
    """밝거나 색이 짙은 배경 위에서도 오브제가 드러나게 — 배경 쪽 손질
    오브제 둘레에 부드러운 어두운 받침을 깐다. 받침은 배경이 밝은 자리일수록 짙고, 어두운 자리에서는 거의 없다.
    돌려주는 것: 손질된 배경 · 오브제 자리의 배경 밝기(흐림) · 번짐 빛 배율"""
    qw, qh = max(8, W // 4), max(8, H // 4)
    # 흩어진 입자·옅은 연기 자국은 빼고 촘촘한 몸통에만 받침을 깐다 (받침이 옅은 연기를 드러내 하얀 테두리처럼 보이지 않게)
    occ = cv2.resize(smoothstep(0.25, 0.65, objA).astype(np.float32), (qw, qh), interpolation=cv2.INTER_AREA)
    halo = np.clip(cv2.GaussianBlur(occ, (0, 0), 4.0 * H / 1080 + 1.0) * 2.4, 0, 1)
    lb = cv2.GaussianBlur(cv2.resize(bg, (qw, qh), interpolation=cv2.INTER_AREA) @ LUMW, (0, 0), 3.0 * H / 1080 + 0.5)
    shade = strength * 0.78 * halo * smoothstep(0.12, 0.55, lb)
    bg = bg * (1 - cv2.resize(shade, (W, H), interpolation=cv2.INTER_LINEAR)[..., None])
    lb_after = cv2.resize(lb * (1 - shade), (W, H), interpolation=cv2.INTER_LINEAR)
    glow_k = 1 - 0.75 * smoothstep(0.30, 0.75, lb_after)
    return bg, lb_after, glow_k


def contrast_object(objC, objA, lb, strength, min_gap=0.30):
    """오브제 쪽 손질 — 오브제 밝기가 바로 뒤 배경 밝기와 min_gap 이상 벌어지게 (색은 지킨 채 밝기만)
    입자가 촘촘히 모인 몸통에만 건다 — 흩어진 입자까지 밝히면 오브제 둘레가 하얗게 번진다"""
    lo = objC @ LUMW
    target = np.where(lb < 0.5, np.maximum(lo, lb + min_gap), np.minimum(lo, lb - min_gap))
    ratio = np.clip(target / np.maximum(lo, 0.03), 0.35, 2.6)
    ratio = 1 + (ratio - 1) * strength * smoothstep(0.35, 0.75, objA)
    return np.clip(objC * ratio[..., None], 0, 1)


_SPRITES = {}


def _sprite(H, digital=False, cell=12):
    key = (H, digital, cell)
    if key not in _SPRITES:
        if digital:  # 디지털 — 가운데 한 칸이 가장 밝은 3×3 블록 점
            k = np.array([[0.25, 0.55, 0.25], [0.55, 1.0, 0.55], [0.25, 0.55, 0.25]], np.float32)
            _SPRITES[key] = np.kron(k, np.ones((cell, cell), np.float32))
        else:  # 아날로그 — 작은 심 + 넓은 번짐
            r = int(40 * H / 1080) + 4
            yy, xx = np.mgrid[-r:r + 1, -r:r + 1].astype(np.float32)
            d2 = xx ** 2 + yy ** 2
            sc, sh = 3.5 * H / 1080 + 0.8, 16 * H / 1080 + 2
            _SPRITES[key] = np.exp(-d2 / (2 * sc ** 2)) * 1.1 + np.exp(-d2 / (2 * sh ** 2)) * 0.55
    return _SPRITES[key]


def draw_seed_lights(frame, lights, H, W, digital=False, cell=12):
    if lights is None:
        return frame
    pts, ks, cols = lights
    sp = _sprite(H, digital, cell)
    h, w = sp.shape
    for (x, y), k, c in zip(pts, ks, cols):
        if k <= 0.01:
            continue
        if digital:
            x, y = (int(x // cell) - 1) * cell, (int(y // cell) - 1) * cell
        else:
            x, y = int(round(x)) - w // 2, int(round(y)) - h // 2
        x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
        if x1 <= x0 or y1 <= y0:
            continue
        patch = sp[y0 - y:y1 - y, x0 - x:x1 - x][..., None] * (c * k)
        frame[y0:y1, x0:x1] = frame[y0:y1, x0:x1] + patch
    return frame


def compose_analog(S, frame, out, u, composite, contrast, fog_col):
    v, col, F, dx, dy, sx, tilt, scale, gap = out
    W, H = S.W, S.H
    acc = splat(S.pos, v, col, W, H)
    acc = cv2.GaussianBlur(acc, (0, 0), 0.7 * H / 1080 + 0.3)
    aw = acc[..., 3]
    objA = 1 - np.exp(-aw * 1.6)
    objC = acc[..., :3] / (aw[..., None] + 1e-6)
    small = cv2.resize(acc[..., :3], (W // 4, H // 4), interpolation=cv2.INTER_AREA)
    glow = cv2.resize(cv2.GaussianBlur(small, (0, 0), 6 * H / 1080 + 1), (W, H), interpolation=cv2.INTER_LINEAR)
    gr = np.zeros((H, W, 3), np.float32); ga = np.zeros((H, W), np.float32)
    S.ghost_layer(u, F, dx, dy, sx, tilt, scale, gap, gr, ga)
    glow_k = 1.0
    if contrast > 0:
        frame, lb, glow_k = contrast_prepare(frame, np.clip(objA + ga, 0, 1), contrast, H, W)
        objC = contrast_object(objC, objA, lb, contrast)
        glow_k = glow_k[..., None]
    frame = frame * (1 - np.clip(ga, 0, 1)[..., None]) + gr
    frame = frame * (1 - objA[..., None]) + objC * objA[..., None]
    frame += glow * (0.35 * S.A['glow'] * S.emo['glow']) * glow_k
    frame = draw_seed_lights(frame, S.seed_lights(u, S.t_now), H, W)
    if not composite:
        frame = frame * (1 - S.A['fog'] * 0.25) + fog_col * (S.A['fog'] * 0.25)
    return frame


def compose_digital(S, frame, out, contrast, cell, gap_mask):
    v, col = out[0], out[1]
    W, H = S.W, S.H
    objC, objA = render_digital(S.pos, v, col, W, H, cell)
    if contrast > 0:
        frame, lb, _ = contrast_prepare(frame, objA, contrast, H, W)
        objC = contrast_object(objC, objA, lb, contrast)
    frame = frame * (1 - objA[..., None]) + objC * gap_mask * objA[..., None]
    return draw_seed_lights(frame, S.seed_lights(S.u_now, S.t_now), H, W, True, cell)


def label_overlay(sc_obj, W, H):
    font = find_font(max(12, int(H * 0.022)))
    small = find_font(max(10, int(H * 0.017)))
    if font is None:
        return None
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x, y = int(W * 0.035), int(H * 0.86)
    d.text((x, y), f'{sc_obj.act}  ·  장면 {sc_obj.sc.get("scene")}  ·  {sc_obj.emo_label}', font=font, fill=(220, 220, 230, 200))
    d.text((x, y + int(H * 0.035)), '   '.join(sc_obj.names), font=small, fill=(170, 175, 190, 170))
    a = np.asarray(img).astype(np.float32) / 255.0
    return a


def run_parallel(args, jobs):
    """장면마다 따로 렌더해(동시에 jobs 개) 이어 붙인다 — 결과는 한 줄로 돌린 것과 같다"""
    import time
    story = json.load(open(args.story, encoding='utf-8'))
    scenes = story['scenes'] if isinstance(story, dict) else story
    nums = sorted(s.get('scene', i + 1) for i, s in enumerate(scenes))
    out = Path(args.out).resolve()
    tmp = out.parent / f'{out.stem}_parts'
    tmp.mkdir(exist_ok=True)
    threads = max(1, (os.cpu_count() or 2) // jobs)
    base = [sys.executable, str(Path(__file__).resolve()), '--story', str(Path(args.story).resolve()),
            '--objects', str(Path(args.objects).resolve()), '--scene-sec', str(args.scene_sec), '--fps', str(args.fps),
            '--size', args.size, '--scale', str(args.scale), '--style', args.style, '--block', str(args.block),
            '--crf', str(args.crf), '--emerge', args.emerge, '--reversal', str(args.reversal), '--worker',
            '--contrast', str(args.contrast), '--seed-glow', str(args.seed_glow), '--dissolve-shift', str(args.dissolve_shift),
            '--threads', str(threads)]
    if args.bg: base += ['--bg', str(Path(args.bg).resolve())]
    if args.bg_json: base += ['--bg-json', str(Path(args.bg_json).resolve())]
    if args.no_label: base += ['--no-label']
    if args.no_reversal: base += ['--no-reversal']
    per = int(round(args.scene_sec * args.fps))
    total = per * len(nums)
    print(f'병렬 렌더 · 장면 {len(nums)}개를 동시에 {jobs}개씩 (프로세스당 스레드 {threads}) → {out.name}')
    waiting, running, parts = list(nums), {}, {}
    t0 = time.time()
    while waiting or running:
        while waiting and len(running) < jobs:
            k = waiting.pop(0)
            part, pf = tmp / f'part_{k:02d}.mp4', tmp / f'part_{k:02d}.progress'
            pf.write_text('0')
            log = open(tmp / f'part_{k:02d}.log', 'w', encoding='utf-8')
            env = dict(os.environ, PYTHONIOENCODING='utf-8')
            running[k] = (subprocess.Popen(base + ['--scenes', str(k), '--out', str(part), '--progress-file', str(pf)],
                                           stdout=log, stderr=subprocess.STDOUT, env=env), log)
            parts[k] = part
        time.sleep(2)
        for k in list(running):
            p, log = running[k]
            if p.poll() is not None:
                log.close()
                if p.returncode != 0:
                    sys.exit(f'장면 {k} 렌더 실패 — {tmp / f"part_{k:02d}.log"} 를 확인하세요')
                (tmp / f'part_{k:02d}.progress').write_text(str(per))
                del running[k]
        done = sum(int((tmp / f'part_{k:02d}.progress').read_text() or 0) for k in parts)
        el = time.time() - t0
        eta = el / done * (total - done) if done else 0
        print(f'\r  {done}/{total} 프레임 · {el:.0f}초 경과 · 남은 시간 약 {eta:.0f}초   ', end='', flush=True)
    print()
    lst = tmp / 'concat.txt'
    lst.write_text(''.join(f"file '{parts[k].as_posix()}'\n" for k in nums), encoding='utf-8')
    subprocess.run([ffmpeg_exe(), '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', str(lst),
                    '-c', 'copy', '-movflags', '+faststart', str(out)], check=True)
    metas = [json.load(open(parts[k].with_suffix('.json'), encoding='utf-8')) for k in nums]
    meta = dict(metas[0])
    meta['video'] = out.name
    meta['scenes'], meta['law_map'], meta['reversal'] = [], [], []
    for i, m in enumerate(metas):
        off = i * per
        for mk in m['scenes']:
            meta['scenes'].append(dict(mk, start_frame=mk['start_frame'] + off, start_sec=round((mk['start_frame'] + off) / args.fps, 2)))
        meta['law_map'] += m['law_map']
        for r in m.get('reversal', []):
            meta['reversal'].append(dict(r, global_sec=round(r['global_sec'] + off / args.fps, 2)))
    json.dump(meta, open(out.with_suffix('.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    shutil.rmtree(tmp, ignore_errors=True)
    for r in meta['reversal']:
        g = r['global_sec']
        print(f'  ★ 반전: 장면 {r["scene"]} 시작 후 {r["local_sec"]}초 = 전체 {int(g // 60)}:{g % 60:04.1f}')
    print(f'완료 → {out}  ·  {time.time() - t0:.0f}초  ·  장면 시각·법칙 대응표 → {out.with_suffix(".json")}')


def main():
    ap = argparse.ArgumentParser(description='꿈 오브제 창발 엔진 (시도 A · 파티클)')
    ap.add_argument('--story', default='dream_scenes.json', help='2팀 스토리보드 json')
    ap.add_argument('--objects', default='output_objects', help='장면별 투명 PNG 폴더 (scene_NN/obj_i_이름.png)')
    ap.add_argument('--out', default='object_emergence.mp4')
    ap.add_argument('--scene-sec', type=float, default=75.0, help='장면 길이(초) — 4장면 × 75초 = 5분')
    ap.add_argument('--fps', type=int, default=30)
    ap.add_argument('--size', default='1920x1080')
    ap.add_argument('--scale', type=float, default=1.0, help='미리보기용 해상도 배율 (0.5 = 절반)')
    ap.add_argument('--scenes', default='', help='일부 장면만 (예: 1,3)')
    ap.add_argument('--bg', default='', help='배경 엔진 mp4 — 주면 통합 영상')
    ap.add_argument('--bg-json', default='', help='배경 엔진 video.json (장면 시작 시각)')
    ap.add_argument('--no-label', action='store_true', help='좌하단 서사 표지 끄기')
    ap.add_argument('--style', choices=['analog', 'digital'], default='analog', help='analog: 빛 입자 · digital: 사각 블록')
    ap.add_argument('--block', type=int, default=12, help='digital 블록 크기(1080p 기준 픽셀)')
    ap.add_argument('--crf', type=int, default=18)
    ap.add_argument('--emerge', choices=['point', 'cloud'], default='point', help='point: 한 점에서 서서히 드러남 · cloud: 예전 방식')
    ap.add_argument('--reversal', type=float, default=0.6, help='전(轉) 장면 반전 시점 (장면 안 비율 · 0.6 = 75초 중 45초)')
    ap.add_argument('--no-reversal', action='store_true', help='반전 끄기')
    ap.add_argument('--seed-glow', type=float, default=1.0, help='오브제가 드러나기 전 시작점 빛의 세기 (0 = 끔)')
    ap.add_argument('--dissolve-shift', type=float, default=0.0, help='오브제가 풀리는 시점 앞뒤 조정 (장면 비율 · +0.02 = 1.5초 늦게)')
    ap.add_argument('--contrast', type=float, default=-1, help='밝은·색 배경 대비 보정 세기 0~1 (기본: 통합이면 1, 오브제만이면 0)')
    ap.add_argument('--jobs', default='auto', help='동시에 렌더할 장면 수 (auto = CPU 에 맞춰 최대 4 · 1 = 한 줄로)')
    ap.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    ap.add_argument('--progress-file', default='', help=argparse.SUPPRESS)
    ap.add_argument('--threads', type=int, default=0, help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.threads:
        cv2.setNumThreads(args.threads)
    reversal = None if args.no_reversal else args.reversal

    W, H = [int(int(v) * args.scale) // 2 * 2 for v in args.size.lower().split('x')]
    digital = args.style == 'digital'
    cell = max(4, round(args.block * H / 1080))
    if digital and args.out == 'object_emergence.mp4':
        args.out = 'object_emergence_digital.mp4'
    if not args.worker and not args.scenes:
        jobs = (min(4, max(1, (os.cpu_count() or 2) // 2)) if args.jobs == 'auto' else int(args.jobs))
        if jobs > 1:
            return run_parallel(args, jobs)
    story = json.load(open(args.story, encoding='utf-8'))
    scenes = story['scenes'] if isinstance(story, dict) else story
    scenes = sorted(scenes, key=lambda s: s.get('scene', 0))
    order = list(range(len(scenes)))
    if args.scenes:
        want = {int(s) for s in args.scenes.split(',')}
        order = [i for i in order if scenes[i].get('scene') in want]
    n_all = len(scenes)
    composite = bool(args.bg)
    contrast = (1.0 if composite else 0.0) if args.contrast < 0 else args.contrast
    seed = int(hashlib.sha1(json.dumps(scenes, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    print(f'꿈 오브제 창발 엔진 · {args.style} · {W}x{H} · {args.fps}fps · 장면당 {args.scene_sec:g}초 · {"통합" if composite else "오브제만"} · 시드 {seed}')

    bg = Background(W, H, args.bg or None, args.bg_json or None, n_all, args.scene_sec)
    if digital:
        if not composite:  # 디지털 바탕 — 평평한 어둠 위에 아주 옅은 격자
            bg.dark = np.full((H, W, 3), [0.035, 0.037, 0.050], np.float32)
            bg.dark[::cell * 4, :] += 0.018
            bg.dark[:, ::cell * 4] += 0.018
        gap_mask = np.ones((H, W, 1), np.float32)  # 블록 사이 가는 틈 — 타일처럼 보이게
        gap_mask[::cell] = 0.72
        gap_mask[:, ::cell] = 0.72
    out = Path(args.out)
    cmd = [ffmpeg_exe(), '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}',
           '-r', str(args.fps), '-i', '-', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', str(args.crf),
           '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(out)]
    enc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    law_map, marks = [], []
    prev_cloud = None
    frames_per_scene = int(round(args.scene_sec * args.fps))
    total = frames_per_scene * len(order)
    last = max(order) if order else -1
    fog_col = np.array([0.10, 0.11, 0.14], np.float32)
    done = 0
    import time
    t0 = time.time()
    reversals = []
    for si in range(last + 1):
        sc = scenes[si]
        files = load_objects_index(args.objects, sc.get('scene', si + 1), sc.get('objects') or [])
        if si not in order:
            # 앞 장면 빨리 감기 — 그리지 않고 입자 계산만 한다. 다음 장면이 앞 장면 잔해에서 태어나므로,
            # 장면을 나눠 렌더해도 한 번에 돌린 것과 같은 결과가 나오게 한다.
            S = Scene(sc, si, n_all, files, W, H, prev_cloud, rng, args.style, cell, args.emerge, reversal, quiet=True,
                      seed_glow=args.seed_glow, dissolve_shift=args.dissolve_shift)
            for f in range(frames_per_scene):
                S.step(f / frames_per_scene, f / args.fps)
            prev_cloud = S.cloud()
            print(f'  장면 {sc.get("scene")} 빨리 감기 완료')
            continue
        S = Scene(sc, si, n_all, files, W, H, prev_cloud, rng, args.style, cell, args.emerge, reversal,
                  seed_glow=args.seed_glow, dissolve_shift=args.dissolve_shift)
        if S.rev is not None:
            loc = S.rev * args.scene_sec
            g = done / args.fps + loc
            reversals.append({'scene': sc.get('scene'), 'local_sec': round(loc, 2), 'global_sec': round(g, 2)})
            print(f'    ★ 반전: 장면 {sc.get("scene")} 시작 후 {loc:.1f}초 (이 영상의 {int(g // 60)}:{g % 60:04.1f})')
        law_map.append({'scene': sc.get('scene'), 'act': S.act, 'emotion': S.emo_label,
                        'objects': S.names, 'laws': S.law_log})
        for e in S.law_log:
            if e['applied']:
                print('    ✓', e['law'], '→', '; '.join(f'{k}: {", ".join(v)}' for k, v in e['behaviors'].items()))
            else:
                print('    ·', e['law'], '→', e['reason'])
        marks.append({'scene': sc.get('scene'), 'act': S.act, 'start_frame': done, 'start_sec': round(done / args.fps, 2)})
        label = None if (args.no_label or composite) else label_overlay(S, W, H)
        for f in range(frames_per_scene):
            tau = f / args.fps
            u = f / frames_per_scene
            step_out = S.step(u, tau)
            if digital:
                frame = compose_digital(S, bg.get(si, tau), step_out, contrast, cell, gap_mask)
                edge = min(1.0, tau / 1.0, (args.scene_sec - tau) / 1.0) if not composite else 1.0
                if label is not None:
                    la = label[..., 3:4] * edge
                    frame = frame * (1 - la) + label[..., :3] * la
                enc.stdin.write((np.clip(frame, 0, 1) * 255).astype(np.uint8).tobytes())
                done += 1
                if args.progress_file and done % 30 == 0:
                    Path(args.progress_file).write_text(str(done))
                if done % (args.fps * 5) == 0 or done == total:
                    el = time.time() - t0
                    print(f'\r  {done}/{total} 프레임 · {el:.0f}초 경과 · 남은 시간 약 {el / done * (total - done):.0f}초   ', end='', flush=True)
                continue
            frame = compose_analog(S, bg.get(si, tau), step_out, u, composite, contrast, fog_col)
            # 장면 경계 — 들어오고 나갈 때 1초씩 부드럽게
            edge = min(1.0, tau / 1.0, (args.scene_sec - tau) / 1.0) if not composite else 1.0
            if label is not None:
                la = label[..., 3:4] * edge
                frame = frame * (1 - la) + label[..., :3] * la
            enc.stdin.write((np.clip(frame, 0, 1) * 255).astype(np.uint8).tobytes())
            done += 1
            if args.progress_file and done % 30 == 0:
                Path(args.progress_file).write_text(str(done))
            if done % (args.fps * 5) == 0 or done == total:
                el = time.time() - t0
                print(f'\r  {done}/{total} 프레임 · {el:.0f}초 경과 · 남은 시간 약 {el / done * (total - done):.0f}초   ', end='', flush=True)
        prev_cloud = S.cloud()
        print()
    enc.stdin.close()
    enc.wait()
    meta = {'video': out.name, 'fps': args.fps, 'size': [W, H], 'scene_sec': args.scene_sec, 'seed': seed,
            'mode': 'integrated' if composite else 'objects_only', 'style': args.style, 'emerge': args.emerge,
            'reversal': reversals, 'scenes': marks, 'law_map': law_map}
    json.dump(meta, open(out.with_suffix('.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print(f'완료 → {out}  ·  장면 시각·법칙 대응표 → {out.with_suffix(".json")}')


if __name__ == '__main__':
    main()
