"""1단계 ③ · 그림 인식 — 배경·오브제 그림이 '무엇인지' 알아본다 (10-08).

지금까지 그림에서는 모양·밝기 수치만 읽었다(실루엣 → 음색). 그래서 종이 물체가 쇠처럼 울릴 수도 있었다.
여기서는 상업 이용이 가능한 공개 모델 셋으로 그림의 '뜻'을 읽고, 그 결과를 자체 합성의 손잡이로만 쓴다.
모델은 소리를 만들지 않는다 — 출력 오디오는 여전히 전부 자체 합성이다(저작권 판정 그대로).

  ① SigLIP 2 (Tschannen et al. 2025 · Apache-2.0)        영(0)샷 분류 — 정해 둔 낱말 목록과 그림을 비교
       오브제 → 재질(금속·종이·유리·나무·돌·천·액체·살갗·그림자)  → 모달 합성의 배음·감쇠·두드림 방식
       배경   → 장소(복도·서가·욕실·동굴·큰 홀…)                   → 잔향 길이·고역 흡음
  ② Florence-2 (Xiao et al. CVPR 2024 · MIT)              물체 찾기(<OD>) + 설명 문장(<CAPTION> · <MORE_DETAILED_CAPTION>)
       배경 속 소리 낼 물체(형광등·창문·시계·책·파이프…)와 그 위치 → '그림 속 소리원' (좌우 위치·거리)
       오브제가 무엇인지(설명 문장) → 그 오브제의 '정체 소리' (항해일지 → 종이 넘김, 열쇠 → 쇠붙이 찰랑임)
  ③ Depth Anything V2 Small (Yang et al. NeurIPS 2024 · Apache-2.0 — Small 만. Base/Large 는 비상업)
       배경 깊이 지도 → 공간의 깊이(잔향) · 소리원까지 거리(가까울수록 크고 밝게)

  · 결과는 그림 지문(SHA-256)별로 cache/vision/ 에 남긴다 → 같은 그림은 다음 실행부터 0초
  · torch·transformers 가 없거나 모델을 못 받으면 그 모델만 건너뛰고 예전 방식(수치만)으로 진행한다
  · GPU 가 있으면 GPU, 없으면 CPU (노트북에서도 느리게나마 돈다)
"""
import hashlib
import json
import os
import re
import time

import numpy as np
from PIL import Image

from . import paths

VERSION = 1      # 낱말 목록·후처리를 바꾸면 올린다 → 캐시가 새로 만들어진다

SIGLIP = os.environ.get('SOUND_SIGLIP_MODEL', 'google/siglip2-base-patch16-224')
FLORENCE = os.environ.get('SOUND_FLORENCE_MODEL', 'florence-community/Florence-2-base')
DEPTH = os.environ.get('SOUND_DEPTH_MODEL', 'depth-anything/Depth-Anything-V2-Small-hf')
MODEL_INFO = {
    'siglip': (SIGLIP, 'Apache-2.0', 'Tschannen et al. 2025, SigLIP 2'),
    'florence': (FLORENCE, 'MIT', 'Xiao et al. 2024, Florence-2 (CVPR)'),
    'depth': (DEPTH, 'Apache-2.0 (Small 만 — Base/Large/Giant 는 CC-BY-NC-4.0)', 'Yang et al. 2024, Depth Anything V2 (NeurIPS)'),
}

# ── 낱말 목록 (키, 한글, 영어 묘사) ─────────────────────────────────────────
# 오브제 그림은 투명 배경 일러스트라 '사진' 대신 '그림' 문형을 쓴다.
MATERIALS = [
    ('metal',   '금속',   'metal, iron or rusty steel'),
    ('paper',   '종이',   'paper, a book or old documents'),
    ('glass',   '유리·얼음', 'glass, crystal or ice'),
    ('wood',    '나무',   'wood or a wooden thing'),
    ('stone',   '돌·도자기', 'stone, concrete or ceramic tile'),
    ('fabric',  '천',     'cloth, fabric or soft textile'),
    ('liquid',  '액체',   'water or a liquid'),
    ('organic', '살갗·몸', 'skin, a hand or a living body'),
    ('shadow',  '그림자·연기', 'a dark shadow, smoke or an intangible silhouette'),
]
MAT_TEMPLATE = 'an illustration of a thing made of {}.'
PLACES = [
    ('corridor',  '복도',       'a long narrow corridor or hallway'),
    ('library',   '서가·도서관', 'a library with bookshelves'),
    ('bathroom',  '타일 욕실',   'a tiled bathroom or washroom'),
    ('basement',  '지하실',     'a basement or cellar'),
    ('cave',      '동굴·터널',   'a cave or a tunnel'),
    ('hall',      '큰 홀',      'a large empty hall or cathedral'),
    ('room',      '작은 방',     'a small room or bedroom'),
    ('stairs',    '계단',       'a staircase'),
    ('forest',    '숲',         'a forest'),
    ('field',     '열린 들판',   'an open field under the sky'),
    ('water',     '물가·바다',   'a seashore, lake or underwater'),
    ('street',    '거리',       'a street or alley at night'),
]
PLACE_TEMPLATE = 'a picture of {}.'
# 장소 → (잔향 길이 초, 고역 흡음 배율 — 책·천이 많을수록 작게). 실내 음향의 대략값(Sabine 식이 주는 크기 순서)
PLACE_ACOUSTICS = {
    'corridor': (2.6, 1.0), 'library': (1.1, 0.45), 'bathroom': (1.8, 1.3), 'basement': (2.2, 0.8),
    'cave': (5.5, 0.7), 'hall': (4.5, 1.0), 'room': (0.7, 0.6), 'stairs': (2.4, 1.0), 'forest': (0.9, 0.5),
    'field': (0.5, 0.8), 'water': (1.5, 0.6), 'street': (1.2, 0.9),
}

# 그림 속 물체 이름(영어) → 사건 키(read.EVENT_RULES). 낱말 경계로 맞춘다.
SOURCE_RULES = [
    ('electric', ['lamp', 'light', 'lights', 'bulb', 'fluorescent', 'lantern', 'chandelier', 'neon', 'screen', 'monitor',
                  'television', 'tv', 'ceiling light', 'light fixture']),
    ('drip',     ['pipe', 'pipes', 'faucet', 'tap', 'drip', 'droplet', 'droplets', 'leak', 'sink']),
    ('liquid',   ['puddle', 'puddles', 'pool', 'liquid', 'bathtub', 'aquarium', 'tank', 'fluid', 'ink', 'syringe']),
    ('flow',     ['river', 'stream', 'waterfall', 'wave', 'waves', 'sea', 'ocean', 'fountain']),
    ('clock',    ['clock', 'watch', 'pendulum']),
    ('door',     ['door', 'doors', 'gate', 'doorway', 'lock', 'handle']),
    ('glass',    ['window', 'windows', 'mirror', 'glass', 'bottle', 'bottles', 'vase', 'jar', 'vial', 'flask', 'cup',
                  'lens', 'bell', 'crystal']),
    ('rustle',   ['book', 'books', 'bookshelf', 'bookshelves', 'bookcase', 'paper', 'papers', 'document', 'documents',
                  'folder', 'newspaper', 'letter', 'letters', 'notebook', 'map', 'files', 'logbook', 'log book', 'journal',
                  'diary', 'envelope', 'page', 'pages', 'scroll', 'photograph', 'photo']),
    ('metal',    ['chain', 'chains', 'metal', 'iron', 'cage', 'locker', 'lockers', 'rail', 'railing', 'radiator',
                  'bucket', 'can', 'pan', 'steel', 'key', 'keys', 'coin', 'coins', 'knife', 'scissors', 'spoon', 'hook',
                  'compass', 'tin']),
    ('machine',  ['fan', 'machine', 'engine', 'ventilator', 'vent', 'computer', 'motor', 'refrigerator', 'generator']),
    ('creak',    ['chair', 'chairs', 'bed', 'swing', 'ladder', 'cabinet', 'drawer', 'drawers', 'shelf', 'shelves',
                  'stairs', 'staircase', 'wooden floor']),
    ('wind',     ['tree', 'trees', 'curtain', 'curtains', 'flag', 'leaves', 'grass', 'reeds', 'plant', 'plants', 'feather',
                  'feathers', 'veil']),
    ('fire',     ['fire', 'candle', 'candles', 'fireplace', 'torch', 'flame', 'flames']),
    ('animal',   ['bird', 'birds', 'crow', 'cat', 'dog', 'wolf', 'insect', 'owl', 'moth', 'raven', 'fish']),
    ('breath',   ['face', 'mouth', 'mask', 'lungs']),
    ('presence', ['shadow', 'shadows', 'silhouette', 'ghost', 'figure', 'smoke']),
    ('crack',    ['tile', 'tiles', 'crack', 'cracks', 'cracked', 'broken', 'shards']),
    ('rain',     ['rain', 'raindrops', 'umbrella']),
    ('snow',     ['snow', 'snowflakes']),
]
_SRC_RE = [(k, re.compile(r'\b(' + '|'.join(re.escape(w) for w in sorted(ws, key=len, reverse=True)) + r')\b'))
           for k, ws in SOURCE_RULES]
MAX_SOURCES = 4


def object_identity(caption, name_en=None):
    """오브제가 '무엇인지' → 정체 소리 {event, word, src}. 그림 설명 문장 먼저, 없으면 오브제 팀 영어 이름표."""
    for text, src in ((caption, '그림 인식(Florence-2 설명: "%s")' % (caption or '')[:60]),
                      (name_en, '오브제 이름표("%s")' % (name_en or ''))):
        if text:
            hit = source_event(text)
            if hit:
                return {'event': hit[0], 'word': hit[1], 'src': src}
    return None


def source_event(label):
    """물체 이름 → (사건 키, 맞은 낱말) 또는 None."""
    s = label.lower()
    for k, rx in _SRC_RE:
        m = rx.search(s)
        if m:
            return k, m.group(1)
    return None


# ── 그림 불러오기 · 캐시 ──────────────────────────────────────────────────
def _image(path):
    im = Image.open(path)
    if im.mode in ('RGBA', 'LA', 'P'):
        im = im.convert('RGBA')
        bg = Image.new('RGBA', im.size, (128, 128, 128, 255))      # 투명 오브제 → 회색 바탕 (흰·검정 쪽으로 쏠리지 않게)
        im = Image.alpha_composite(bg, im)
    return im.convert('RGB')


def _sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _cache_path(kind, model, path):
    key = hashlib.sha1(json.dumps([VERSION, kind, model, _sha(path)]).encode()).hexdigest()[:20]
    d = os.path.join(paths.CACHE_DIR, 'vision')
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, '%s_%s.json' % (kind, key))


def _cache_get(kind, model, path):
    p = _cache_path(kind, model, path)
    if os.path.exists(p):
        try:
            return json.load(open(p, encoding='utf-8'))
        except (OSError, ValueError):
            pass
    return None


def _cache_put(kind, model, path, out):
    json.dump(out, open(_cache_path(kind, model, path), 'w', encoding='utf-8'), ensure_ascii=False)
    return out


# ── 모델 셋 ──────────────────────────────────────────────────────────────
class Seer:
    """세 모델을 필요할 때 한 번만 불러 쓴다. 하나가 실패해도 나머지는 계속."""

    def __init__(self, log=print, require=False):
        import torch
        self.torch = torch
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.dtype = torch.float16 if self.device == 'cuda' else torch.float32
        self.log, self.require = log, require
        self._m = {}
        self.failed = {}
        self.used = set()
        self.cache_hits = 0

    def _load(self, name):
        if name in self._m or name in self.failed:
            return self._m.get(name)
        t = time.time()
        try:
            import transformers as tf
            if name == 'siglip':
                proc = tf.AutoProcessor.from_pretrained(SIGLIP)
                model = tf.AutoModel.from_pretrained(SIGLIP, torch_dtype=self.dtype).to(self.device).eval()
            elif name == 'florence':
                if not hasattr(tf, 'Florence2ForConditionalGeneration'):
                    raise RuntimeError('transformers 가 Florence-2 를 모릅니다 — pip install -U transformers')
                proc = tf.AutoProcessor.from_pretrained(FLORENCE)
                model = tf.Florence2ForConditionalGeneration.from_pretrained(
                    FLORENCE, torch_dtype=self.dtype).to(self.device).eval()
            else:
                proc = tf.AutoImageProcessor.from_pretrained(DEPTH)
                model = tf.AutoModelForDepthEstimation.from_pretrained(DEPTH).to(self.device).eval()
            self._m[name] = (proc, model)
            self.log('%s 불러옴 (%s · %s · %.0f초)' % (name, MODEL_INFO[name][0], self.device, time.time() - t))
        except Exception as e:                                    # 모델 하나가 안 돼도 나머지로 계속
            self.failed[name] = str(e)[:200]
            self.log('%s 건너뜀 — %s' % (name, self.failed[name]))
            if self.require:
                raise
        return self._m.get(name)

    def _run(self, name, kind, path, fn):
        """캐시에 있으면 모델을 부르지도 않는다. 없으면 모델을 불러 계산하고 캐시에 남긴다."""
        model_id = MODEL_INFO[name][0]
        out = _cache_get(kind, model_id, path)
        if out is None:
            if self._load(name) is None:
                return None
            try:
                out = _cache_put(kind, model_id, path, fn())
            except Exception as e:
                self.log('%s 실행 실패 (%s) — %s' % (name, os.path.basename(path), str(e)[:200]))
                if self.require:
                    raise
                return None
        else:
            self.cache_hits += 1
        self.used.add(name)
        return out

    # ① SigLIP 2 — 낱말 목록 분류
    def classify(self, path, vocab, template, kind):
        def run():
            proc, model = self._load('siglip')
            texts = [template.format(en) for _, _, en in vocab]
            with self.torch.no_grad():
                inp = proc(text=texts, images=_image(path), padding='max_length', max_length=64, return_tensors='pt')
                inp = {k: (v.to(self.device, self.dtype) if v.is_floating_point() else v.to(self.device))
                       for k, v in inp.items()}
                logits = model(**inp).logits_per_image[0].float().cpu().numpy()
            p = np.exp(logits - logits.max())
            p = p / p.sum()
            return [[k, ko, round(float(x), 4)] for (k, ko, _), x in sorted(zip(vocab, p), key=lambda kv: -kv[1])]
        return self._run('siglip', kind, path, run)

    # ② Florence-2 — 물체 찾기 + 자세한 설명
    def caption(self, path):
        """오브제 한 장 → 짧은 설명 문장 (무엇인지)."""
        def run():
            return {'caption': self._florence(path, ('<CAPTION>',))['<CAPTION>']}
        out = self._run('florence', 'objcap', path, run)
        return (out or {}).get('caption')

    def _florence(self, path, tasks):
        proc, model = self._load('florence')
        im = _image(path)
        res = {'size': im.size}
        for task in tasks:
            with self.torch.no_grad():
                inp = proc(text=task, images=im, return_tensors='pt')
                inp = {k: (v.to(self.device, self.dtype) if v.is_floating_point() else v.to(self.device))
                       for k, v in inp.items()}
                ids = model.generate(**inp, max_new_tokens=256, num_beams=3, do_sample=False)
            txt = proc.batch_decode(ids, skip_special_tokens=False)[0]
            out = proc.post_process_generation(txt, task=task, image_size=im.size).get(task)
            res[task] = out if isinstance(out, dict) else str(out or '').strip()
        return res

    def describe(self, path):
        def run():
            res = self._florence(path, ('<OD>', '<MORE_DETAILED_CAPTION>'))
            od = res.get('<OD>') or {}
            return {'size': list(res['size']), 'boxes': [[str(l), [round(float(v), 1) for v in b]]
                                                     for l, b in zip(od.get('labels', []), od.get('bboxes', []))],
                    'caption': str(res.get('<MORE_DETAILED_CAPTION>') or '').strip()}
        return self._run('florence', 'florence', path, run)

    # ③ Depth Anything V2 Small — 깊이 지도 (가까울수록 큰 값 → 0~1 로 정규화, 64×64 로 줄여 저장)
    def depth(self, path):
        def run():
            proc, model = self._load('depth')
            im = _image(path)
            with self.torch.no_grad():
                inp = proc(images=im, return_tensors='pt').to(self.device)
                d = model(**inp).predicted_depth[0].float().cpu().numpy()
            d = (d - d.min()) / (np.ptp(d) + 1e-9)
            small = np.asarray(Image.fromarray((d * 255).astype(np.uint8)).resize((64, 64), Image.BILINEAR)) / 255.0
            return {'near': np.round(small, 3).tolist()}
        return self._run('depth', 'depth', path, run)


# ── 해석: 모델 출력 → 소리 손잡이 ─────────────────────────────────────────
def depth_features(near):
    """깊이 지도(가까움 0~1) → 공간 수치.
    depth   = 화면 안 거리 폭(먼 곳과 가까운 곳의 차) + 아주 먼 곳의 비율 — 복도·동굴처럼 깊을수록 1
    open    = 아주 먼 곳의 비율 (하늘·끝이 안 보이는 복도)"""
    far = 1 - np.asarray(near, dtype=float)
    spread = float(np.percentile(far, 90) - np.percentile(far, 10))
    far_frac = float((far > 0.8).mean())
    return {'depth': round(float(np.clip(0.55 * spread + 1.2 * far_frac, 0, 1)), 4),
            'open': round(far_frac, 4), 'spread': round(spread, 4)}


def find_sources(desc, near):
    """Florence-2 출력 → 그림 속 소리원 [{event, label, word, x(-1~1), near(0~1), area, src}] (사건마다 하나, 큰 것 먼저)."""
    W, H = desc['size']
    best = {}
    for label, (x0, y0, x1, y1) in desc.get('boxes') or []:
        hit = source_event(label)
        if not hit:
            continue
        k, w = hit
        area = max(0.0, (x1 - x0) * (y1 - y0)) / max(1.0, W * H)
        nr = 0.5
        if near is not None:
            a = np.asarray(near)
            gx0, gx1 = int(64 * x0 / W), max(int(64 * x0 / W) + 1, int(64 * x1 / W))
            gy0, gy1 = int(64 * y0 / H), max(int(64 * y0 / H) + 1, int(64 * y1 / H))
            nr = float(a[gy0:gy1, gx0:gx1].mean())
        item = {'event': k, 'label': label, 'word': w, 'x': round(((x0 + x1) / 2 / W) * 2 - 1, 3),
                'y': round((y0 + y1) / 2 / H, 3), 'near': round(nr, 3), 'area': round(area, 4), 'src': 'Florence-2 물체 찾기'}
        if k not in best or area > best[k]['area']:
            best[k] = item
    # 설명 문장에만 나오는 소리원 — 위치를 모르니 가운데 · 중간 거리
    cap = desc.get('caption') or ''
    for sent in re.split(r'(?<=[.!?])\s+', cap):
        for k, rx in _SRC_RE:                                   # 한 문장에 여럿('형광등과 벽시계')이어도 모두
            m = rx.search(sent.lower())
            if m and k not in best:
                best[k] = {'event': k, 'label': sent.strip()[:80], 'word': m.group(1), 'x': 0.0, 'y': 0.5, 'near': 0.4,
                           'area': 0.0, 'src': 'Florence-2 설명 문장'}
    return sorted(best.values(), key=lambda s: (-s['area'], s['event']))[:MAX_SOURCES]


def annotate(scenes, log=print, require=False):
    """장면들에 그림 인식 결과를 붙인다. 반환: 요약 {'models': [...], 'failed': {...}, 'sec': ...} 또는 None(모델 없음)."""
    t0 = time.time()
    try:
        seer = Seer(log=log, require=require)
    except ImportError as e:
        if require:
            raise
        log('그림 인식 건너뜀 — torch/transformers 없음 (%s). 예전처럼 모양·밝기 수치만 씁니다' % e)
        return None
    for s in scenes:
        v = {'place': None, 'bg_materials': None, 'sources': [], 'caption': None, 'depth': None}
        bg = s.get('background') or {}
        bp = bg.get('path')
        if bp:
            v['place'] = seer.classify(bp, PLACES, PLACE_TEMPLATE, 'place')
            v['bg_materials'] = seer.classify(bp, MATERIALS, MAT_TEMPLATE, 'bgmat')
            d = seer.depth(bp)
            near = d['near'] if d else None
            if near is not None:
                v['depth'] = depth_features(near)
                f = bg.get('features')
                if f is not None:
                    f['depth_luma'] = f.get('depth')                 # 예전 밝기 기반 추정은 남겨 둔다(비교용)
                    f['depth'] = v['depth']['depth']
                    f['open'] = v['depth']['open']
            desc = seer.describe(bp)
            if desc:
                v['caption'] = desc['caption']
                v['boxes'] = desc['boxes']
                v['sources'] = find_sources(desc, near)
        for o in s.get('objects', []):
            m = seer.classify(o['path'], MATERIALS, MAT_TEMPLATE, 'objmat')
            if m and not o['features'].get('empty'):
                o['features']['material'] = m[0][0]
                o['features']['material_p'] = m[0][2]
                o['material_rank'] = m[:3]
            cap = seer.caption(o['path'])
            o['caption'] = cap
            o['identity'] = object_identity(cap, o.get('name_en'))
        s['vision'] = v
        s['seen'] = v['sources']
        pl = v['place'][0] if v['place'] else None
        log('장면 %d: 장소 %s · 깊이 %s · 그림 속 소리원 %s · 오브제 재질/정체 소리 %s' % (
            s['num'], ('%s(%.2f)' % (pl[1], pl[2])) if pl else '-',
            ('%.2f' % v['depth']['depth']) if v['depth'] else '-',
            ', '.join('%s←%s' % (x['event'], x['word']) for x in v['sources']) or '-',
            ', '.join('%s=%s/%s' % (o['name'], o['features'].get('material', '-'), (o.get('identity') or {}).get('event', '-'))
                      for o in s.get('objects', [])) or '-'))
    used = sorted(seer.used)
    seer._m.clear()                                               # 진화·렌더 동안 GPU 메모리를 비워 둔다
    if seer.device == 'cuda':
        seer.torch.cuda.empty_cache()
    if not used:
        return None
    return {'models': [{'role': k, 'id': MODEL_INFO[k][0], 'license': MODEL_INFO[k][1], 'paper': MODEL_INFO[k][2]}
                       for k in used],
            'failed': seer.failed, 'device': seer.device, 'cache_hits': seer.cache_hits, 'sec': round(time.time() - t0, 1)}
