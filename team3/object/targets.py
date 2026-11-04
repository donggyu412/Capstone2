"""
진화 목표 선화 만들기 (11/05 교수님 피드백)
  "아피찻퐁 사이트 이미지를 오브제로 놓고 Claude AI 로 기하학적 형상으로 변환한 이미지를 진화 목표로 삼아,
   처음에는 랜덤 위치의 점에서 시작해 진화 과정을 통해 목표 이미지를 향해 가도록.
   크기는 적절히, 얼굴 표정은 꿈 스토리 감정과 일치, 오브제는 동물 · 자동차 등 다양하게"

  오브제마다 Claude 가 (장면 이야기를 읽고) 그릴 대상을 정하고 — 사람 · 동물 · 탈것 · 사물을 고루 —
  교수님 예시와 같은 기하학적 선화(흰 윤곽 · 어긋난 색 선 · 몸을 따라 휘는 그물망)를 '선 목록'으로 그린다.
  대상에 얼굴이 있으면 표정을 그 장면의 감정에 맞춘다.
  참고 사진(아피찻퐁 이미지 등)이 있으면 --ref 폴더에 obj 이름으로 넣어 두면 Claude 가 그 사진을 보고 그린다.

  python targets.py --story dream_scenes.json --out output_objects            (모든 오브제)
  python targets.py --story dream_scenes.json --out output_objects --ref refs (참고 사진 함께)

  결과: targets.json (엔진이 읽음) · targets_preview/장면_번호.png (미리보기) · object_story.md (설명서)
  필요: 루트 .env 의 ANTHROPIC_API_KEY
"""
import argparse
import base64
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODEL = 'claude-sonnet-5'   # 2팀 이야기 생성과 같은 모델

EXPRESSION = {   # 멀리서도 한눈에 읽히게 과장한다
    '기쁨': '활짝 웃음 — 반달 모양으로 감긴 눈 · 크게 올라간 U자 입꼬리 · 둥글게 올라간 볼 '
            '(이빨을 톱니 · 지그재그로 그리지 말 것 — 무섭게 보인다)',
    '슬픔': '슬픔 — 안쪽 끝이 치켜올라간 ㅅ자 눈썹 · 아래로 처진 눈 · 양 끝이 아래로 내려간 ∩ 모양 입 · 눈 밑의 큰 눈물 방울 '
            '(감긴 ^ 모양 눈 · 위로 휜 입 금지 — 웃는 얼굴로 보인다)',
    '분노': '분노 — 안쪽으로 모여 내리꽂힌 눈썹 · 부릅뜬 눈 · 이를 악문 입',
    '공포': '공포 — 흰자가 큰 동그란 눈과 아주 작은 점 눈동자 · 높이 올라간 눈썹 · 세로로 길게 벌어진 입 · 떨리는 지그재그 윤곽',
    '놀람': '놀람 — 높이 둥글게 올라간 눈썹 · 동그랗게 커진 눈 · 동그랗게 벌어진 입',
    '혐오': '혐오 — 찡그린 코 · 한쪽으로 들린 윗입술 · 가늘게 뜬 눈',
    '중립': '담담함 — 편안한 눈과 다문 입',
}
MAX_PER_SCENE = 4   # 장면마다 그릴 형상 수 (오브제가 많으면 이야기 순서대로 고르게 고른다 · 시선이 한곳에 머물게)
# 11/12 피드백 — 얼굴 · 사람으로 쏠리지 않게: 장면마다 얼굴 있는 형상은 딱 하나(그 장면 감정), 나머지는 얼굴 없이 서로 다른 갈래
KINDS = ['동물', '탈것', '자연(식물 · 날씨 · 풍경)', '건축물', '도구 · 기계', '생활 사물', '바다 · 하늘의 생물', '천체 · 빛']
HYBRID = 0.35       # 얼굴 없는 형상 중 '잡종'(이야기 속 두 오브제를 합친 낯선 형상 · 바퀴 달린 말처럼)으로 그릴 비율
ROLES = ('main', 'detail', 'accent', 'grid')

PROMPT = """너는 꿈 영상의 오브제를 '기하학적 선화'로 그리는 일러스트레이터야.

[꿈 장면 이야기]
{story}

[이 장면의 감정] {emotion}
[그릴 오브제] {name}
[이 꿈에서 이미 쓴 대상 — 겹치지 않게] {used}

1. 이 오브제를 표현할 '구체적인 대상' 하나를 정해. 사람 · 동물 · 탈것(자동차 · 배 · 비행기 …) · 사물 중에서,
   이야기와 이어지면서 보는 사람이 바로 알아볼 수 있고, 이미 쓴 대상과 종류가 겹치지 않게 다양하게.
   {face_rule}
   {kind_rule}
2. 그 대상을 아래 스타일의 선화로 그려. 어두운 배경 위의 흰 선이 중심인 기하학적 라인 아트야.
   - main: 대상의 윤곽과 큰 구조를 이루는 굵은 선 8~20개
   - detail: 눈 · 입 · 코 · 귀 · 바퀴 · 창문 같은 세부 선 4~14개.
     대상에게 얼굴이 있으면(사람 · 동물 · 의인화) 표정을 반드시 이 감정에 맞춰: {expression}
     얼굴은 대상 너비의 40% 이상으로 크게(바퀴 · 몸통 옆에 작게 붙이지 말고 대상의 중심에), 눈썹 · 눈 · 입을 각각 따로 선으로 그려
     멀리서도 표정이 한눈에 읽히게. 그린 뒤 '이 얼굴을 처음 보는 사람이 감정을 맞힐 수 있는가'를 스스로 확인해.
     얼굴이 없으면 자세 · 기울기 · 선의 긴장으로 감정을 드러내.
   - 전체가 직선 · 꺾은선 · 원 · 다각형 같은 기하학적 요소로 이뤄지게 (손으로 그린 곡선 낙서처럼 보이지 않게).
   - accent: main 선 몇 개를 살짝 어긋나게 다시 따라 그린 색 선 3~8개
   - grid: 대상의 결을 따르는 선 4~8개 (대상 윤곽 안쪽만). 가로줄을 층층이 쌓지 말고 대상에 맞게 대각선 · 방사형 · 곡선 ·
     세로 결 등 방향을 달리해 (모든 대상이 마디진 애벌레나 원통처럼 보이지 않게)
   좌표는 1000x1000 캔버스, 대상은 가운데에 크게 (x, y 모두 100~900 안). 선 하나는 점 4~40개, 전체 점은 1500개 이하.
3. JSON 하나로만 답해 (설명 · 코드블록 없이):
{{"subject": "대상 이름(한국어)", "subject_en": "english", "kind": "갈래", "has_face": true, "expression": "그린 표정 한 줄",
  "reason": "이 대상이 이야기와 이어지는 이유 한 문장",
  "strokes": [{{"role": "main", "closed": false, "points": [[x, y], ...]}}, ...]}}"""


def _client():
    import anthropic
    try:
        from dotenv import load_dotenv
        load_dotenv(HERE.parent.parent / '.env')
    except Exception:
        pass
    return anthropic.Anthropic()


def _parse(text):
    a, b = text.find('{'), text.rfind('}')
    if a < 0 or b <= a:
        raise ValueError('JSON 없음')
    d = json.loads(text[a:b + 1])
    strokes = []
    for st in d.get('strokes') or []:
        role = st.get('role', 'main')
        pts = [[float(p[0]), float(p[1])] for p in (st.get('points') or []) if isinstance(p, (list, tuple)) and len(p) >= 2]
        pts = [[min(1000.0, max(0.0, x)), min(1000.0, max(0.0, y))] for x, y in pts]
        if len(pts) >= 2 and role in ROLES:
            if st.get('closed') and pts[0] != pts[-1]:
                pts.append(pts[0])
            strokes.append({'role': role, 'points': pts})
    n_struct = sum(1 for s in strokes if s['role'] in ('main', 'detail'))
    if n_struct < 6:
        raise ValueError(f'윤곽 · 세부 선이 너무 적음 ({n_struct}개)')
    d['strokes'] = strokes
    return d


def draw_one(client, sc, name, used, ref=None, face=False, kind=None, hybrid_with=None, person_ok=True):
    emo = (sc.get('main_emotion') or {}).get('label', '중립')
    if face:
        face_rule = ('이번 대상은 이 장면의 감정을 보여 줄 형상이야. 반드시 얼굴이 있는 존재(동물 · 의인화된 사물'
                     + (' · 사람' if person_ok else ', 사람은 이미 썼으니 사람 말고') + ')로 정하고, 얼굴을 크게 앞에 보이게 그려 '
                     f"'{emo}' 표정이 화면의 중심이 되게 해.")
    else:
        face_rule = ('이번 대상은 얼굴 · 눈 · 입을 절대 그리지 마. has_face 는 false. 사람이나 사람 모양(막대 인간 포함)도 그리지 마. '
                     '감정은 자세 · 기울기 · 선의 긴장으로만 드러내. 실루엣(전체 윤곽)이 다른 대상들과 확연히 다르게.')
    kind_rule = ''
    if kind:
        kind_rule = f"대상의 갈래는 '{kind}' 에서 골라 (사람 금지)."
    if hybrid_with:
        kind_rule += (f" 그리고 이 대상은 이야기 속 다른 오브제 '{hybrid_with}' 와 합쳐진 낯선 잡종 형상으로 그려 "
                      "(예: 바퀴 달린 말 · 날개 달린 자동차 · 뿌리가 내린 등대). 보는 사람의 고정관념을 깨는 결합이어야 해.")
    prompt = PROMPT.format(story=(sc.get('story') or '')[:2500], emotion=emo, name=name, face_rule=face_rule, kind_rule=kind_rule,
                           used=', '.join(used) or '(없음)', expression=EXPRESSION.get(emo, EXPRESSION['중립']))
    content = [{'type': 'text', 'text': prompt}]
    if ref is not None:  # 참고 사진 (아피찻퐁 이미지 등) — 이 사진 속 대상을 기하학적 선화로 바꾼다
        media = 'image/png' if ref.suffix.lower() == '.png' else 'image/jpeg'
        content = [{'type': 'image', 'source': {'type': 'base64', 'media_type': media,
                                                 'data': base64.b64encode(ref.read_bytes()).decode()}},
                   {'type': 'text', 'text': '이 사진 속 대상을 참고해서 그려.\n\n' + prompt}]
    last = None
    for attempt in range(2):
        try:
            msg = client.messages.create(model=MODEL, max_tokens=16000, messages=[{'role': 'user', 'content': content}])
            text = ''.join(b.text for b in msg.content if getattr(b, 'type', '') == 'text')
            return _parse(text)
        except Exception as e:
            last = e
    print(f'  ! {name}: 선화를 받지 못했습니다 ({last})')
    return None


def choose(sc, objs, seen, k=MAX_PER_SCENE):
    """장면에서 그릴 오브제 고르기 — 앞 장면에서 이미 그린 것은 뒤로, 이야기에 나오는 순서로 고르게 k 개"""
    if len(objs) <= k:
        return list(objs)
    sys.path.insert(0, str(HERE))
    from doodles import first_sentence
    pos = {o: (first_sentence(sc.get('story', ''), o)[1] if first_sentence(sc.get('story', ''), o)[1] is not None else 1.0) for o in objs}
    fresh = [o for o in objs if o not in seen]
    pool = fresh if len(fresh) >= k else fresh + [o for o in objs if o in seen][:k - len(fresh)]
    pool = sorted(pool, key=lambda o: pos[o])
    idx = [round(i * (len(pool) - 1) / max(k - 1, 1)) for i in range(k)]
    return [pool[i] for i in sorted(set(idx))]


def preview(d, path, size=500):
    try:
        import cv2
        import numpy as np
    except Exception:
        return
    img = np.full((size, size, 3), (32, 14, 10), np.uint8)
    col = {'main': (245, 240, 235), 'detail': (245, 240, 235), 'accent': (200, 140, 230), 'grid': (190, 150, 90)}
    th = {'main': 2, 'detail': 2, 'accent': 1, 'grid': 1}
    for st in d['strokes']:
        p = (np.array(st['points']) * size / 1000).astype(np.int32).reshape(-1, 1, 2)
        cv2.polylines(img, [p], False, col[st['role']], th[st['role']], cv2.LINE_AA)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imencode('.png', img)[1].tofile(str(path))


def build(story_path, out_dir, ref_dir=None, only=None):
    story_path, out_dir = Path(story_path), Path(out_dir)
    data = json.loads(story_path.read_text(encoding='utf-8'))
    scenes = sorted(data['scenes'], key=lambda s: s['scene'])
    sys.path.insert(0, str(HERE))
    from doodles import first_sentence   # 이야기에 처음 나오는 자리 (드러나는 때)
    client = _client()
    old = {}
    tj = out_dir / 'targets.json'
    if tj.exists():  # 이미 그린 오브제는 다시 부르지 않는다 (--only 로 고르면 그것만 다시)
        try:
            for s in json.loads(tj.read_text(encoding='utf-8'))['scenes']:
                for o in s['objects']:
                    old[(s['scene'], o['name'])] = o
        except Exception:
            old = {}
    seen = set()
    used_kinds, person_used = set(), False
    rng_t = __import__('numpy').random.default_rng(int(hashlib.sha1(story_path.read_bytes()).hexdigest()[:8], 16))
    used, result = [], {'source': 'Claude 기하학적 선화', 'scenes': [],
                        'story_hash': hashlib.sha1(story_path.read_bytes()).hexdigest()[:12]}
    md = ['# 오브제 ↔ 꿈 이야기 설명서 (진화 목표 선화)', '',
          '오브제마다 Claude 가 이야기를 읽고 그릴 대상을 정해 기하학적 선화로 그렸고, 영상에서는 흩어진 점들이 진화하며 이 선화를 향해 갑니다.',
          '형상은 그 오브제가 장면 이야기에 처음 나오는 자리에서 모습을 갖추고, 얼굴이 있는 대상은 장면 감정에 맞는 표정을 짓습니다.', '']
    for sc in scenes:
        emo = (sc.get('main_emotion') or {}).get('label', '중립')
        ent = {'scene': sc['scene'], 'emotion': emo, 'objects': []}
        md += [f"## 장면 {sc['scene']} · {emo}", '', '| 오브제 | 그린 대상 | 표정 | 이렇게 고른 이유 | 드러나는 때 |', '|---|---|---|---|---|']
        objs = sc.get('objects') or []
        pick = choose(sc, objs, seen)            # 장면마다 최대 4개 — 앞 장면에서 그린 오브제는 뒤로 미루고 이야기 순서대로 고르게
        skipped = [o for o in objs if o not in pick]
        n_face = 0
        face_slot = int(rng_t.integers(len(pick)))            # 장면마다 얼굴 있는 형상은 딱 하나 (그 장면 감정) · 자리는 무작위
        kinds_left = [k for k in KINDS if k not in used_kinds] or list(KINDS)
        for i, name in enumerate(objs, 1):
            if name not in pick:
                continue
            face_req = pick.index(name) == face_slot
            kind = None if face_req else kinds_left.pop(int(rng_t.integers(len(kinds_left)))) if kinds_left else None
            hyb = None
            if not face_req and rng_t.random() < HYBRID:
                others = [o for o in objs if o != name]
                hyb = others[int(rng_t.integers(len(others)))] if others else None
            key = (sc['scene'], name)
            redo = only is not None and f"{sc['scene']}-{i}" in only
            if key in old and not redo and old[key].get('strokes'):
                d = old[key]
                print(f"  = {sc['scene']}-{i} {name} → {d.get('subject')} (이미 그림)")
            else:
                ref = None
                if ref_dir:
                    for ext in ('.png', '.jpg', '.jpeg'):
                        for cand in (Path(ref_dir) / f"{sc['scene']}-{i}{ext}", Path(ref_dir) / f"{name}{ext}"):
                            if cand.exists():
                                ref = cand
                print(f"  … {sc['scene']}-{i} {name} 그리는 중" + (f' (참고 사진 {ref.name})' if ref else ''))
                d = draw_one(client, sc, name, used, ref, face_req, kind, hyb, person_ok=not person_used) or {'subject': '', 'strokes': []}
            sent, pos = first_sentence(sc.get('story', ''), name)
            if pos is None:
                pos = (i - 0.5) / max(len(sc.get('objects') or []), 1)
            o = dict(d, index=i, name=name, sentence=sent, reveal=round(pos, 3))
            if o.get('has_face'):
                n_face += 1
            if o.get('kind'):
                used_kinds.add(o['kind'])
            if '사람' in str(o.get('kind', '')) or '사람' in str(o.get('subject', '')):
                person_used = True
            seen.add(name)
            if o.get('subject'):
                used.append(o['subject'])
            ent['objects'].append(o)
            if o.get('strokes'):
                preview(o, out_dir / 'targets_preview' / f"{sc['scene']}_{i}.png")
            md.append(f"| {name} | {o.get('subject') or '없음'} | {o.get('expression', '')} | {o.get('reason', '')} | 이야기의 {int(pos * 100)}% 지점 |")
        result['scenes'].append(ent)
        if skipped:
            md.append(f"(이 장면에서 그리지 않은 오브제: {', '.join(skipped)} — 앞 장면과 겹치거나 4개를 넘어서)")
        md.append('')
    out_dir.mkdir(parents=True, exist_ok=True)
    tj.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    (out_dir / 'object_story.md').write_text('\n'.join(md), encoding='utf-8')
    n = sum(len(s['objects']) for s in result['scenes'])
    ok = sum(1 for s in result['scenes'] for o in s['objects'] if o.get('strokes'))
    print(f'  선화 {ok}/{n}개 → {tj} · 미리보기 {out_dir / "targets_preview"} · 설명서 object_story.md')
    return result


def main():
    ap = argparse.ArgumentParser(description='진화 목표 선화 (Claude 기하학적 선화)')
    ap.add_argument('--story', default=str(HERE / 'dream_scenes.json'))
    ap.add_argument('--out', default=str(HERE / 'output_objects'))
    ap.add_argument('--ref', help='참고 사진 폴더 (파일 이름: 장면-번호.png 또는 오브제이름.jpg)')
    ap.add_argument('--only', nargs='+', help='이 오브제만 다시 그림 (예: --only 1-2 3-1)')
    args = ap.parse_args()
    build(args.story, args.out, args.ref, set(args.only) if args.only else None)


if __name__ == '__main__':
    main()
