"""
꿈 대본의 오브제 → 알아볼 수 있는 손그림 형상 (10/30 교수님 피드백)
  "오브제 형상들이 비슷비슷 — 차 · 어린아이 · 동물처럼 다양하게"
  "오브제가 꿈 스토리랑 어떻게 이어져서 만든 건지 설명"
  "형상이 처음엔 드러나지 않다가 나중에 나타나고 · 꿈 이야기로 전개되며 변화"

  1. 오브제 이름(한국어 낱말 + 번역)을 사람이 직접 그린 낙서 데이터셋
     Quick, Draw!(Google · 345가지 · CC BY 4.0)의 형상 이름에 맞춘다 (새 → bird, 드론 → helicopter …)
     ANTHROPIC_API_KEY 가 있고 --llm 이면 Claude 에게 이야기 맥락까지 보고 고르게 한다
  2. 그 형상의 낙서 중 하나를 스토리 시드로 고른다 — 사람이 그은 획 순서 그대로 (그리는 과정이 살아 있다)
  3. 형상이 드러나는 시각 = 그 오브제가 장면 이야기에 처음 나오는 자리 (이야기 앞쪽이면 일찍, 뒤쪽이면 늦게)
  4. 결과: doodles.json (엔진이 읽음) + object_story.md (오브제 ↔ 이야기 설명서)

  python doodles.py --story dream_scenes.json --out output_objects        (규칙으로 고르기)
  python doodles.py --story dream_scenes.json --out output_objects --llm  (Claude 로 고르기)

낙서 데이터는 처음 한 번 형상마다 앞부분 일부만 내려받아 doodle_cache/ 에 둔다 (인터넷 필요 · 형상당 수백 KB)
"""
import argparse
import hashlib
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
QD_URL = 'https://storage.googleapis.com/quickdraw_dataset/full/simplified/{}.ndjson'

# Quick, Draw! 형상 이름 (345가지 중 꿈 오브제에 쓸 만한 것)
CATEGORIES = set('''airplane alarm_clock ambulance angel ant anvil apple arm axe backpack banana barn bat bathtub beach bear bed bee
bench bicycle binoculars bird book boomerang bottlecap bowtie bracelet brain bread bridge broom bucket bus bush butterfly cactus cake
calculator camel camera campfire candle cannon canoe car carrot castle cat ceiling_fan cell_phone chair chandelier church circle clock
cloud coffee_cup compass computer cookie couch cow crab crown cruise_ship cup diamond dog dolphin door dragon dresser drums duck ear
elephant envelope eye eyeglasses face fan feather fence finger fire_hydrant fireplace fish flamingo flashlight flower flying_saucer
foot fork frog garden giraffe guitar hammer hand harp hat headphones hedgehog helicopter hexagon horse hospital hot_air_balloon
hourglass house house_plant hurricane jacket key keyboard knee knife ladder lantern laptop leaf leg light_bulb lighthouse lightning
line lion lobster lollipop mailbox map megaphone mermaid microphone monkey moon mosquito motorbike mountain mouse moustache mouth mug
mushroom nail necklace nose ocean octagon octopus owl paintbrush palm_tree panda parachute parrot pear pencil penguin piano
pickup_truck picture_frame pig pillow pineapple pliers pond pool rabbit radio rain rainbow rhinoceros river sailboat saw saxophone
scissors scorpion sea_turtle shark sheep shoe skull skyscraper smiley_face snail snake snowflake snowman sock speedboat spider spoon
square squiggle squirrel stairs star stethoscope stop_sign stove streetlight submarine suitcase sun swan sword table teapot teddy-bear
telephone television tent tiger toaster toilet tooth tornado tractor traffic_light train tree triangle truck trumpet umbrella vase
violin watermelon whale wheel windmill wine_bottle wine_glass wristwatch zigzag'''.split())

# 한국어 낱말 → 형상 (앞에 있는 낱말이 먼저 맞으면 그걸 쓴다 · 형상은 첫 번째부터 시도)
KO_RULES = [
    ('드론', ['helicopter', 'flying_saucer']), ('비행기', ['airplane']), ('헬리콥터', ['helicopter']),
    ('조종사', ['airplane', 'face']), ('자동차', ['car']), ('차 ', ['car']), ('트럭', ['truck']), ('기차', ['train']),
    ('자전거', ['bicycle']), ('배 ', ['sailboat']), ('선체', ['cruise_ship', 'sailboat']), ('잠수함', ['submarine']),
    ('참새', ['bird']), ('새소리', ['bird']), ('날갯짓', ['bird', 'butterfly']), ('날개', ['bird', 'angel']), ('새', ['bird']),
    ('고양이', ['cat']), ('강아지', ['dog']), ('개', ['dog']), ('말', ['horse']), ('물고기', ['fish']), ('고래', ['whale']),
    ('나방', ['butterfly']), ('나비', ['butterfly']), ('벌', ['bee']), ('거미', ['spider']), ('뱀', ['snake']), ('달팽이', ['snail']),
    ('토끼', ['rabbit']), ('곰', ['bear', 'teddy-bear']), ('인형', ['teddy-bear', 'angel']), ('부엉이', ['owl']), ('오리', ['duck']),
    ('아이', ['smiley_face', 'face']), ('얼굴', ['face', 'smiley_face']), ('사람', ['face']), ('그림자', ['face', 'angel']),
    ('손바닥', ['hand']), ('손끝', ['finger', 'hand']), ('손가락', ['finger']), ('손', ['hand']), ('발소리', ['foot']), ('발', ['foot']),
    ('눈', ['eye']), ('귀', ['ear']), ('입', ['mouth']), ('다리', ['leg']), ('팔', ['arm']),
    ('종소리', ['bell', 'alarm_clock']), ('종', ['bell', 'alarm_clock']), ('시계', ['clock', 'alarm_clock']), ('열쇠', ['key']),
    ('문', ['door']), ('창', ['picture_frame', 'house']), ('유리', ['picture_frame', 'diamond']), ('거울', ['picture_frame']),
    ('계단', ['stairs']), ('사다리', ['ladder']), ('집', ['house']), ('등대', ['lighthouse']), ('다리 ', ['bridge']),
    ('나무 상자', ['suitcase']), ('상자', ['suitcase']), ('나무', ['tree']), ('나뭇잎', ['leaf']), ('꽃', ['flower']), ('풀', ['bush']),
    ('깃털', ['feather']), ('물방울', ['rain']), ('빗방울', ['rain']), ('비 ', ['rain']), ('액체', ['cup', 'wine_glass']),
    ('물', ['pond', 'ocean']), ('파도', ['ocean']), ('바다', ['ocean']), ('웅덩이', ['pond']), ('얼음', ['snowflake']),
    ('소금', ['snowflake', 'diamond']), ('결정', ['diamond', 'snowflake']), ('먼지', ['cloud', 'tornado']), ('구름', ['cloud']),
    ('안개', ['cloud']), ('연기', ['cloud']), ('빛', ['light_bulb', 'sun']), ('햇살', ['sun']), ('달', ['moon']), ('별', ['star']),
    ('번개', ['lightning']), ('불', ['campfire', 'candle']), ('촛불', ['candle']), ('등불', ['lantern']),
    ('책', ['book']), ('서류', ['book', 'envelope']), ('종이', ['envelope', 'book']), ('편지', ['envelope']), ('일지', ['book']),
    ('지도', ['map']), ('사진', ['camera', 'picture_frame']), ('의자', ['chair']), ('침대', ['bed']), ('우산', ['umbrella']),
    ('모자', ['hat']), ('신발', ['shoe']), ('가방', ['backpack', 'suitcase']), ('컵', ['cup', 'mug']), ('병', ['wine_bottle']),
    ('캡슐', ['hot_air_balloon', 'cup']), ('뚜껑', ['bottlecap']), ('쇳덩이', ['anvil']), ('철판', ['anvil']), ('칼', ['knife']),
    ('목소리', ['microphone', 'megaphone']), ('소리', ['megaphone', 'microphone']), ('음악', ['guitar', 'violin']),
    ('벽', ['fence']), ('틈', ['door', 'zigzag']), ('금', ['lightning', 'zigzag']), ('균열', ['lightning', 'zigzag']),
    ('구멍', ['circle']), ('막', ['cloud', 'squiggle']), ('얼룩', ['cloud', 'squiggle']), ('줄', ['line', 'squiggle']),
    ('바퀴', ['wheel']), ('풍선', ['hot_air_balloon']), ('낙하산', ['parachute']), ('텐트', ['tent']), ('성', ['castle']),
]
FALLBACK = ['squiggle', 'cloud', 'star', 'circle']
ABSTRACT = {'line', 'squiggle', 'zigzag', 'circle', 'square', 'triangle', 'hexagon', 'octagon',
            'ocean', 'river', 'rain'}  # 바다 · 강 · 비는 낙서가 물결선 · 빗금뿐이라 무엇인지 알아보기 어렵다


def _seed_int(*parts):
    return int(hashlib.sha1('|'.join(map(str, parts)).encode('utf-8')).hexdigest()[:8], 16)


def _jong_n(ch):
    c = ord(ch) - 0xAC00
    return 0 <= c < 11172 and c % 28 == 4


def name_words(name):
    """오브제 이름 → 낱말들 (머리 명사 = 마지막 낱말을 맨 앞에 · 꾸밈말 '낡은 · 긴 · 떨어지는' 은 뺀다)"""
    out = []
    for chunk in re.split(r'[/()·,]+', name):
        ws = [w for w in chunk.split() if w]
        for i, w in enumerate(ws):
            if len(w) >= 3 and w[-1] in '의과와':
                w = w[:-1]
            if w.endswith(('는', '은', '던')) and i < len(ws) - 1:
                continue
            if i < len(ws) - 1 and _jong_n(w[-1]):
                continue
            out.append(w)
    heads = [w for w in out if w == out[-1]] if out else []
    return list(dict.fromkeys(heads + out[::-1]))


def _kw_in(kw, word):
    kw = kw.strip()
    if len(kw) == 1:  # 한 글자(손 · 문 · 금 · 새 …)는 낱말 그 자체이거나 낱말 맨 앞일 때만
        return word == kw or (word.startswith(kw) and len(word) <= 3 and word[1:] in ('이', '가', '을', '를', '은', '는', '의', '도'))
    return kw in word


VIVID = [('날갯짓', ['bird', 'butterfly', 'angel']), ('날개', ['bird', 'angel', 'butterfly'])]  # 그림이 또렷한 낱말은 머리 명사보다 먼저


def rule_pick(name, en=''):
    """오브제 이름 → (형상 후보들, 근거) — 머리 명사부터, 긴 낱말부터 맞춘다 ('서류철과 종이' → 종이 · '타일 금' → 금)"""
    for kw, cats in VIVID:
        if kw in name:
            return cats, f"이름의 '{kw}'"
    found = []
    for w in name_words(name):
        hits = [(len(kw.strip()), kw, cats) for kw, cats in KO_RULES if _kw_in(kw, w)]
        for _, kw, cats in sorted(hits, key=lambda h: -h[0]):
            ok = [c for c in cats if c in CATEGORIES or c == 'bell']
            if ok:
                found.append((ok, f"이름의 '{kw.strip()}'"))
                break
    concrete = [f for f in found if not all(c in ABSTRACT for c in f[0])]
    if concrete or found:   # 선 · 낙서 같은 추상 형상보다 알아볼 수 있는 형상을 먼저 ('먼지 줄' → 먼지)
        return (concrete or found)[0]
    for w in re.findall(r'[a-z]+', (en or '').lower()):
        for c in (w, w.rstrip('s')):
            if c in CATEGORIES:
                return [c], f"번역 '{en}'의 '{c}'"
    return FALLBACK, '맞는 형상이 없어 낙서'


def llm_pick(scenes, model='claude-sonnet-5'):  # 2팀 이야기 생성과 같은 모델
    """Claude 에게 장면 이야기와 오브제를 보여 주고 형상을 고르게 한다 → {(장면, 순번): (형상, 근거)}"""
    try:
        import anthropic
        try:
            from dotenv import load_dotenv
            load_dotenv(HERE.parent.parent / '.env')
        except Exception:
            pass
        client = anthropic.Anthropic()
    except Exception as e:
        print(f'  ! Claude 를 쓸 수 없어 규칙으로 고릅니다 ({e})')
        return {}
    cats = ', '.join(sorted(CATEGORIES - ABSTRACT))  # 선 · 낙서 · 도형처럼 무엇인지 알아볼 수 없는 형상은 빼고 고르게
    out = {}
    for sc in scenes:
        objs = sc.get('objects') or []
        prompt = (f"꿈 장면 이야기:\n{sc.get('story', '')[:2500]}\n\n오브제: {json.dumps(objs, ensure_ascii=False)}\n\n"
                  f"각 오브제를 어린아이가 낙서로 그릴 수 있는, 알아볼 수 있는 형상 하나로 바꿔 줘. "
                  f"형상은 반드시 이 목록에서 고르고, 오브제끼리 겹치지 않게 다양하게. 사물·동물·사람처럼 "
                  f"보는 사람이 무엇인지 바로 알아볼 수 있는 형상이어야 해: {cats}\n"
                  f"JSON 배열만 답해: [{{\"object\": 이름, \"category\": 형상, \"reason\": 이야기와 이어지는 이유 한 문장}}]")
        try:
            msg = client.messages.create(model=model, max_tokens=1500, messages=[{'role': 'user', 'content': prompt}])
            text = ''.join(b.text for b in msg.content if getattr(b, 'type', '') == 'text')
            arr = json.loads(text[text.find('['):text.rfind(']') + 1])
            for i, o in enumerate(objs, 1):
                hit = next((a for a in arr if a.get('object') == o), None)
                if hit and hit.get('category', '').replace(' ', '_') in CATEGORIES - ABSTRACT:
                    out[(sc['scene'], i)] = (hit['category'].replace(' ', '_'), 'Claude: ' + hit.get('reason', ''))
        except Exception as e:
            print(f"  ! 장면 {sc.get('scene')} Claude 답을 읽지 못했습니다 ({e}) — 규칙으로 고릅니다")
    return out


def fetch(cat, cache_dir, want=150, max_bytes=4_000_000):
    """형상 하나의 낙서를 앞에서부터 조금만 받아 둔다 (알아본 낙서 · 획 3~14개)"""
    cache_dir.mkdir(parents=True, exist_ok=True)
    f = cache_dir / f'{cat}.json'
    if f.exists():
        return json.loads(f.read_text(encoding='utf-8'))
    url = QD_URL.format(urllib.parse.quote(cat.replace('_', ' ')))
    got, n = [], 0
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            for line in r:
                n += len(line)
                d = json.loads(line)
                if d.get('recognized') and 3 <= len(d['drawing']) <= 14:
                    got.append(d['drawing'])
                if len(got) >= want or n > max_bytes:
                    break
    except Exception as e:
        print(f'  ! 낙서 데이터를 받지 못했습니다: {cat} ({e})')
        return []
    f.write_text(json.dumps(got), encoding='utf-8')
    return got


def normalize(drawing):
    """[[xs],[ys]] 획들 → 가운데 0 · 가장 긴 변 1 인 좌표 (획 순서 그대로)"""
    pts = [list(zip(s[0], s[1])) for s in drawing if len(s[0]) >= 2]
    xs = [p[0] for s in pts for p in s]
    ys = [p[1] for s in pts for p in s]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    sc = max(max(xs) - min(xs), max(ys) - min(ys)) or 1
    return [[[round((x - cx) / sc, 4), round((y - cy) / sc, 4)] for x, y in s] for s in pts]


def first_sentence(story, name):
    """오브제가 이야기에 처음 나오는 문장과 그 자리(0~1) — 머리 명사로 먼저 찾고, 없으면 다른 낱말로"""
    sents = [x for x in re.split(r'(?<=[.!?。])\s+|\n+', story or '') if x.strip()]
    total = max(len(story or ''), 1)
    for w in name_words(name):
        if len(w) < 2 and not re.search(r'[가-힣]', w):
            continue
        for i, s in enumerate(sents):
            found = (w in s) if len(w) >= 2 else re.search(rf'(?<![가-힣]){w}(?=$|[^가-힣]|[이가을를은는의에도])', s)
            if found:
                pos = (story.find(s) if story.find(s) >= 0 else 0) / total
                return s.strip(), min(1.0, max(0.0, pos))
    return '', None


def picks_llm(flag):
    return bool(flag)


def build(story_path, out_dir, use_llm=False, cache_dir=None, translations=None):
    data = json.loads(Path(story_path).read_text(encoding='utf-8'))
    scenes = sorted(data['scenes'], key=lambda s: s['scene'])
    seed = _seed_int(json.dumps(scenes, ensure_ascii=False, sort_keys=True))
    tr = {}
    tp = Path(translations) if translations else HERE / 'translations.json'
    if tp.exists():
        tr = {k: v.get('en', '') for k, v in json.loads(tp.read_text(encoding='utf-8')).items()}
    cache_dir = Path(cache_dir) if cache_dir else HERE / 'doodle_cache'
    picks = llm_pick(scenes) if use_llm else {}
    import hashlib as _h
    result, md = {'source': 'Quick, Draw! Dataset (Google · CC BY 4.0)', 'seed': seed, 'scenes': [],
                  'story_hash': _h.sha1(Path(story_path).read_bytes()).hexdigest()[:12], 'chooser': 'Claude' if picks_llm(use_llm) else '규칙'}, []
    md += ['# 오브제 ↔ 꿈 이야기 설명서', '',
           '오브제마다 알아볼 수 있는 손그림 형상을 고르고(사람이 직접 그린 낙서 · Quick, Draw! 데이터셋 · CC BY 4.0),',
           '그 오브제가 장면 이야기에 **처음 나오는 자리**에 맞춰 형상이 드러나게 했습니다. 앞쪽에 나오면 일찍, 뒤쪽에 나오면 늦게.', '']
    used = set()
    for sc in scenes:
        objs = sc.get('objects') or []
        ent = {'scene': sc['scene'], 'emotion': (sc.get('main_emotion') or {}).get('label', ''), 'objects': []}
        md += [f"## 장면 {sc['scene']} · {ent['emotion']}", '', '| 오브제 | 형상 | 이렇게 고른 이유 | 이야기에 처음 나오는 문장 | 드러나는 때 |', '|---|---|---|---|---|']
        for i, name in enumerate(objs, 1):
            if (sc['scene'], i) in picks:
                cands, why = [picks[(sc['scene'], i)][0]], picks[(sc['scene'], i)][1]
            else:
                cands, why = rule_pick(name, tr.get(name, ''))
            cands = sorted(cands, key=lambda c: c in used)  # 같은 꿈 안에서는 되도록 다른 형상
            drawing, cat, alts = None, None, []
            for c in cands + FALLBACK:
                pool = fetch(c, cache_dir)
                if pool:
                    h = _seed_int(seed, sc['scene'], i, name)
                    drawing = pool[h % len(pool)]
                    cat = c
                    # 갈래 — 같은 형상을 다른 사람이 그린 낙서 2개 (탐색 · 변이 때 섞어 쓴다)
                    alts = [pool[(h + 7 * (k + 1)) % len(pool)] for k in range(2) if len(pool) > 1]
                    break
            for c in [c for c in cands if c != cat][:1]:  # 다른 후보 형상 하나도 갈래로
                pool = fetch(c, cache_dir)
                if pool:
                    alts.append(pool[_seed_int(seed, c, i) % len(pool)])
            sent, pos = first_sentence(sc.get('story', ''), name)
            if pos is None:
                pos = (i - 0.5) / max(len(objs), 1)
                sent = '(이야기에 같은 낱말이 없어 순서대로)'
            used.add(cat)
            ent['objects'].append({'index': i, 'name': name, 'category': cat, 'reason': why,
                                   'sentence': sent, 'reveal': round(pos, 3),
                                   'strokes': normalize(drawing) if drawing else [],
                                   'alts': [normalize(a) for a in alts]})
            md.append(f"| {name} | {cat or '없음'} | {why} | {sent[:60]} | 이야기의 {int(pos * 100)}% 지점 |")
        result['scenes'].append(ent)
        md.append('')
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'doodles.json').write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    (out_dir / 'object_story.md').write_text('\n'.join(md), encoding='utf-8')
    missing = sum(1 for s in result['scenes'] for o in s['objects'] if not o['strokes'])
    print(f"  형상 {sum(len(s['objects']) for s in result['scenes'])}개 · 낙서 없음 {missing}개 → {out_dir / 'doodles.json'} · 설명서 object_story.md")
    return result


def main():
    ap = argparse.ArgumentParser(description='꿈 오브제 → 손그림 형상 + 설명서')
    ap.add_argument('--story', default=str(HERE / 'dream_scenes.json'))
    ap.add_argument('--out', default=str(HERE / 'output_objects'))
    ap.add_argument('--llm', action='store_true', help='Claude 로 이야기 맥락까지 보고 형상을 고른다 (ANTHROPIC_API_KEY 필요)')
    args = ap.parse_args()
    build(args.story, args.out, args.llm)


if __name__ == '__main__':
    main()
