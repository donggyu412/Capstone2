"""
Step 6. 오픈엔디드 변이 조립 엔진 (Open-Ended Assembly Engine)  — v2

위치: team1/src/step6_assemble_blueprint.py
입출력 폴더: team1/output/

[INPUT]  keyword_pool.json        (Step 5 출력: 기승전결 배정 + 피크 + 키워드 풀)
[OUTPUT] assembled_blueprint.json (Step 7 Qwen 입력: 4장면 설계도 + 장면 전환 + 원본 대비 지표)
         scene_handoff.json       (다음 팀: 장면별 배경 / 엔티티·오브제 / 배치 관계)
         step6_alternatives.json  (대안 설계도)
         step6_archive_map.txt    (MAP-Elites 격자 — 탐색이 만든 꿈의 분포)
         step6_evolution_log.json (세대별 격자 점유율 · 품질)

v2 핵심 변경 (원본 재현 문제 해결)
  A. 목표 뒤집기  : 장면마다 원본 피크 키워드는 '기억의 씨앗' 1조각만 남기고,
                    나머지 재료는 피크 장면 ±2 밖에서만 가져온다.
                    '원본 재현도'(같은 원본 장면에 함께 있던 재료 쌍 비율)를 감점한다.
  B. 표현 생성    : 키워드를 [수식어 + 핵심어]로 쪼개 교차 재조합한다.
                    예) '금속 바닥을 긁는' + '파도 녹음' → '금속 바닥을 긁는 파도 녹음'
                    원본에 없던 표현이 진화 과정에서 새로 태어난다.
  C. 차이 증명    : 장면별 원본 재현도 · 새 표현 비율 · 씨앗 키워드를 출력한다.

구조
  Open-Ended  : 상상 문법 변이 연산자(재조합·의인화·합체·관계) + MAP-Elites 진화 탐색,
                장면 전환 후보 생성-평가
  Close-Ended : 기승전결 배정, 고정축-회전축 규칙, 씨앗 1조각 · 원본 거리 규칙,
                비복원(중복 금지), 감정 적합도 평가, 안전 조건 기반 최종 선택

외부 라이브러리 불필요 (Python 3.10 표준 라이브러리만 사용)

실행 예 (Capstone2 폴더에서):
  python team1/src/step6_assemble_blueprint.py                 # 매번 다른 꿈
  python team1/src/step6_assemble_blueprint.py --seed 2        # 재현 가능한 결과
  python team1/src/step6_assemble_blueprint.py --curiosity 0.6 # 더 기괴한 꿈 선호
"""
from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

# ======================================================================
# 0. 설정값
# ======================================================================
PEAK_RADIUS = 2          # 피크 장면 ±2 는 '원본과 가까운' 재료로 본다
DATA_EMO_SCALE = 0.6     # 관객 감정 분포 근거의 반영 비율 (원본 쪽으로 끌려가지 않도록 축소)
MIN_EMOTION = 0.25       # 최종 선택 조건: 모든 장면의 감정 적합도 하한
MAX_REPRO = 0.25         # 최종 선택 조건: 평균 원본 재현도 상한
MIN_NEW = 0.2            # 최종 선택 조건: 평균 새 표현 비율 하한
STG_RANGE = (0.0, 0.8)   # 기묘함 축 범위


# ======================================================================
# 1. 한국어 처리 (조사, 수식어/핵심어 분해)
# ======================================================================
def _last_hangul(w: str):
    for c in reversed(w):
        if "가" <= c <= "힣":
            return c
    return None


def josa(w: str, pair: str) -> str:
    """pair는 '받침 있을 때/없을 때' 순서: 이/가, 은/는, 을/를, 과/와, 으로/로"""
    a, b = pair.split("/")
    c = _last_hangul(w)
    if c is None:
        return w + b
    jong = (ord(c) - 0xAC00) % 28
    if pair == "으로/로" and jong == 8:  # ㄹ받침
        return w + "로"
    return w + (a if jong else b)


def q(w: str, pair: str) -> str:
    """작은따옴표로 감싼 뒤 조사 붙이기: 'X'가"""
    return josa(w, pair).replace(w, f"'{w}'", 1)


# ㄴ/ㄹ 받침으로 끝나지만 관형어(수식어)가 아닌 명사들
NOT_ADNOMINAL = {"수면", "주변", "보존", "표본", "외판", "전", "190년", "200년간",
                 "캡슐", "개인", "무전", "생물", "신호", "디지털", "현", "얼음물", "불", "엔진",
                 "카운트다운"}


def is_adnominal(word: str) -> bool:
    """'갈라지는', '텅 빈', '비상등만 켜진'처럼 뒤의 명사를 꾸미는 어절인가"""
    if word in NOT_ADNOMINAL or word.endswith("만"):   # '비상등만' 같은 명사+조사 제외
        return False
    if word.endswith("의") and len(word) >= 2:
        return True
    c = _last_hangul(word)
    if c is None or c != word[-1]:
        return False
    return (ord(c) - 0xAC00) % 28 in (4, 8)   # ㄴ, ㄹ 받침


def split_phrase(text: str, cat: str):
    """키워드 → (수식어, 핵심어)
    '금속 바닥을 긁는 발톱 소리' → ('금속 바닥을 긁는', '발톱 소리')
    '최저 출력으로 공회전하는 엔진의 깊고 느린 진동' → ('깊고 느린', '진동')  (수식어가 4어절을 넘으면 마지막 수식절만)
    상태 키워드는 전체가 수식어
    """
    if cat == "상태":
        return text, ""
    words = text.split()
    bounds = [i for i, w in enumerate(words[:-1]) if is_adnominal(w)]
    if not bounds:
        return "", text
    last = bounds[-1]
    mod_words = words[:last + 1]
    if len(mod_words) > 4 and len(bounds) > 1:
        mod_words = words[bounds[-2] + 1:last + 1]
    return " ".join(mod_words), " ".join(words[last + 1:])


# ======================================================================
# 2. 키워드 풀 + 감정 친화도 (Close-Ended 평가 기준)
# ======================================================================
EMOTIONS = ["기쁨", "신뢰", "공포", "놀람", "슬픔", "혐오", "분노", "기대"]
CATS = ["배경", "사물", "상태", "사운드"]

# 감정별 표현 단서 (부분 문자열 매칭). 1팀 8감정 분류기로 교체 가능
LEXICON = {
    "공포": ["갈라", "균열", "비명", "감압", "폭발", "터지", "찢", "파열", "경보", "굉음", "뒤틀",
             "공포", "절규", "삼켜", "붙잡힌", "조각", "휘파람", "신음", "비상", "빠져나가", "얼어붙",
             "폭주", "고통", "증폭", "진공", "잔해", "끌려가", "차가운", "고압", "파손", "무너"],
    "놀람": ["들뜬", "급작", "갑작", "날카", "이질", "튀는", "클릭", "헐떡", "낑낑", "긁는", "터지",
             "순식간", "분출", "연달아", "빠르게", "카운트다운", "낯선", "왜곡", "번쩍", "반짝"],
    "슬픔": ["텅 빈", "홀로", "본 적 없는", "먹먹", "오래된", "낡은", "웃음만", "190년", "200년",
             "멀어", "먼 ", "사라진", "멈춘", "멈추는", "느려", "잡음", "필터링된", "녹음", "얇",
             "희미", "서툰", "망설이", "한숨", "그 사람", "남는", "남은", "잠들어", "건조한", "바스러"],
    "기쁨": ["따뜻", "편안", "맑은", "지저귀", "살아 있는", "부드러운", "노래처럼", "깨끗", "푸른", "새소리",
             "선명", "미풍", "통기타", "모닥불"],
    "신뢰": ["차분", "안정", "규칙적", "박자", "고른", "자리를 잡는", "공격적이지", "일정한"],
    "기대": ["점화 직전", "감각이 돌아오는", "상승", "카운트다운", "열린", "잠들어 있던", "신호", "비켜나는"],
    "혐오": ["걸쭉", "점성", "생체 실험", "냉동액", "빨려"],
    "분노": ["집요", "거칠게", "연타", "때리는", "주먹", "공격"],
}


@dataclass(frozen=True)
class Kw:
    text: str
    cat: str                 # 배경 / 사물 / 상태 / 사운드
    kind: str = ""           # 사물일 때: 엔티티 / 오브제
    scenes: tuple = ()
    label: str = ""          # 사운드 라벨
    span: str = ""           # 사운드 원본 구간 (다음 단계: 사운드 그레인 절단에 사용)
    mod: str = ""            # 수식어
    head: str = ""           # 핵심어
    parts: tuple = ()        # 재조합으로 생성된 경우 (수식어 재료 Kw, 핵심어 재료 Kw)

    @property
    def key(self):
        return (self.cat, self.text)

    @property
    def nums(self):
        return [int(s[1:]) for s in self.scenes]

    @property
    def generated(self):
        return bool(self.parts)

    @property
    def spans(self):
        if self.parts:
            return [p.span for p in self.parts if p.span]
        return [self.span] if self.span else []


class Pool:
    def __init__(self, path: str):
        with open(path, encoding="utf-8-sig") as f:
            raw = json.load(f)
        self.meta = raw["메타"]
        self.assign = raw["기승전결_배정"]
        self.peaks = raw["피크"]
        self.n_scenes = self.meta.get("장면수", 30)
        self.items: dict = {c: [] for c in CATS}
        for cat in CATS:
            for x in raw["키워드"][cat]:
                mod, head = split_phrase(x["키워드"], cat)
                self.items[cat].append(Kw(
                    text=x["키워드"], cat=cat, kind=x.get("종류", ""),
                    scenes=tuple(x.get("출처_장면", [])), label=x.get("라벨", ""),
                    span=x.get("구간", ""), mod=mod, head=head))
        self.entities = [k for k in self.items["사물"] if k.kind == "엔티티"]
        self.objects = [k for k in self.items["사물"] if k.kind == "오브제"]
        self.entity_scenes = {s for e in self.entities for s in e.scenes}
        self.originals = {k.text for c in CATS for k in self.items[c]}
        # 재조합 재료: 수식어를 줄 수 있는 키워드 / 핵심어를 줄 수 있는 키워드
        self.mod_donors = [k for c in CATS for k in self.items[c] if k.mod]
        self._aff: dict = {}

    # ---------- 샘플링 (비복원: exclude에 이미 쓴 키워드) ----------
    def sample(self, cat, rng: random.Random, exclude=(), kind=None, where=None):
        cands = [k for k in self.items[cat] if k.key not in exclude
                 and (kind is None or k.kind == kind) and (where is None or where(k))]
        return rng.choice(cands) if cands else None

    def linked(self, peak_scene: str):
        """피크 장면에서 나온 원본 키워드 = 씨앗 후보"""
        return [k for c in CATS for k in self.items[c] if peak_scene in k.scenes]

    # ---------- 재조합: 새 표현 생성 ----------
    def recombine(self, head_kw: Kw, rng: random.Random, peak: str | None = None, used=()):
        """head_kw의 핵심어에 다른 키워드의 수식어를 붙여 새 키워드를 만든다"""
        base = head_kw.parts[1] if head_kw.generated else head_kw
        head_words = set(base.head.split())
        cands = [m for m in self.mod_donors if m.text != base.text and m.key not in used
                 and m.mod not in base.text
                 and not (head_words & set(m.mod.split()))          # '선내에서 … 선내' 같은 중복 방지
                 and not any(w in base.head for w in m.mod.split() if len(w) >= 2)
                 and (peak is None or not near(m, peak))]
        if not cands or base.cat == "상태":
            return None
        m = rng.choice(cands)
        text = f"{m.mod} {base.head}"
        if text in self.originals:
            return None
        return Kw(text=text, cat=base.cat, kind=base.kind,
                  scenes=tuple(sorted(set(m.scenes) | set(base.scenes))),
                  label=base.label, span=base.span, mod=m.mod, head=base.head, parts=(m, base))

    # ---------- 감정 친화도 ----------
    def affinity(self, kw: Kw, emo: str) -> float:
        key = (kw.key, emo)
        if key in self._aff:
            return self._aff[key]
        s = 0.0
        for p in self.peaks:                       # 데이터 근거 (축소 반영)
            if p["장면"] in kw.scenes:
                tot = sum(p["분포"].values())
                s = max(s, DATA_EMO_SCALE * p["분포"].get(emo, 0) / tot)
        hits = sum(1 for cue in LEXICON.get(emo, []) if cue in kw.text)
        s = max(s, min(1.0, 0.5 * hits))            # 표현 근거
        self._aff[key] = s
        return s

    def context_distance(self, a: Kw, b: Kw) -> float:
        """원본 영상 안에서 두 재료가 얼마나 멀리 떨어져 있었나 (0=같은 장면, 1=처음과 끝)"""
        if not a.nums or not b.nums:
            return 0.5
        return min(abs(i - j) for i in a.nums for j in b.nums) / max(1, self.n_scenes - 1)


def footprint(k: Kw) -> set:
    """키워드가 차지하는 원본 재료들: 원본이면 자기 자신, 재조합이면 자기 + 두 재료"""
    return {k.key} | {p.key for p in k.parts}


def near(k: Kw, peak: str) -> bool:
    p = int(peak[1:])
    return any(abs(n - p) <= PEAK_RADIUS for n in k.nums)


def is_seed(k: Kw, peak: str) -> bool:
    return peak in k.scenes


# ======================================================================
# 3. 설계도 유전체 + Close-Ended 복구 + Open-Ended 변이 연산자
# ======================================================================
ROLES = ["기", "승", "전", "결"]
REL_TYPES = {"포함역전": None, "재질치환": "사물", "크기역전": None, "합체": None, "공감각": None}
ANCHORED = {"승": {"subj0"}, "전": {"bg"}, "결": {"subj0"}}   # 고정축 슬롯


@dataclass
class Scene:
    role: str
    emotion: str
    peak: str
    bg: Kw
    subj: list
    states: list
    sounds: list
    rel: dict | None = None      # {"type": ..., "b": Kw | None}
    ops: list = field(default_factory=list)

    def clone(self):
        return Scene(self.role, self.emotion, self.peak, self.bg, list(self.subj),
                     list(self.states), list(self.sounds),
                     dict(self.rel) if self.rel else None, list(self.ops))

    def keywords(self):
        ks = [self.bg, *self.subj, *self.states, *self.sounds]
        if self.rel and self.rel.get("b") is not None:
            ks.append(self.rel["b"])
        return ks

    def free(self, slot):
        return slot not in ANCHORED.get(self.role, set())

    # ----- 자유 슬롯(고정축이 아닌 슬롯) 다루기 -----
    def free_slots(self):
        out = []
        if self.free("bg"):
            out.append(("bg", 0))
        for i in range(len(self.subj)):
            if i > 0 or self.free("subj0"):
                out.append(("subj", i))
        out += [("states", i) for i in range(len(self.states))]
        out += [("sounds", i) for i in range(len(self.sounds))]
        if self.rel and self.rel.get("b") is not None:
            out.append(("relb", 0))
        return out

    def get(self, slot):
        name, i = slot
        if name == "bg": return self.bg
        if name == "relb": return self.rel["b"]
        return getattr(self, name)[i]

    def set(self, slot, kw):
        name, i = slot
        if name == "bg": self.bg = kw
        elif name == "relb": self.rel["b"] = kw
        else: getattr(self, name)[i] = kw

    def slot_kind(self, slot):
        if slot == ("subj", 0):
            return {"기": "엔티티", "전": "오브제"}.get(self.role)
        return None


@dataclass
class Blueprint:
    scenes: list
    lineage: list = field(default_factory=list)

    def clone(self):
        return Blueprint([s.clone() for s in self.scenes], list(self.lineage))

    def used(self):
        """사용 중인 재료 (재조합 표현의 원재료 키워드까지 포함 → 같은 기억이 두 번 쓰이지 않게)"""
        return {key for s in self.scenes for k in s.keywords() for key in footprint(k)}

    def keyset(self):
        return frozenset(self.used())


def random_blueprint(pool: Pool, rng: random.Random) -> Blueprint:
    scenes, used = [], set()

    def take(cat, peak, kind=None):
        k = pool.sample(cat, rng, used, kind, where=lambda x: not near(x, peak)) \
            or pool.sample(cat, rng, used, kind)
        used.add(k.key)
        return k

    for a in pool.assign:
        role, pk = a["역할"], a["피크_장면"]
        kind = "엔티티" if role == "기" else ("오브제" if role == "전" else None)
        scenes.append(Scene(role, a["감정"], pk, take("배경", pk), [take("사물", pk, kind)],
                            [take("상태", pk)], [take("사운드", pk)]))
    bp = Blueprint(scenes)
    repair(bp, pool, rng)
    return bp


# ---------------- Close-Ended 복구 ----------------
def repair(bp: Blueprint, pool: Pool, rng: random.Random):
    _anchor(bp, pool, rng)
    _dedup(bp, pool, rng)
    _seed_and_distance(bp, pool, rng)
    _anchor(bp, pool, rng)        # 씨앗 주입이 주인공을 바꿨을 수 있으므로 다시 고정
    _dedup(bp, pool, rng)
    _relations(bp)


def _anchor(bp, pool, rng):
    g, s, j, k = bp.scenes
    if g.subj[0].kind != "엔티티":
        g.subj[0] = pool.sample("사물", rng, bp.used(), "엔티티") or pool.entities[0]
    s.subj[0] = g.subj[0]         # 승: 주인공 유지, 공간만 변이
    j.bg = s.bg                   # 전: 공간 유지, 주인공이 사물로 변이
    if j.subj[0].kind != "오브제":
        j.subj[0] = pool.sample("사물", rng, bp.used(), "오브제")
    k.subj[0] = g.subj[0]         # 결: 처음 주인공 복귀(수미상관)


def _replacement(sc, slot, pool, rng, exclude):
    """같은 카테고리·종류에서 피크와 먼 원본 키워드로 교체"""
    cur = sc.get(slot)
    kind = sc.slot_kind(slot)
    return (pool.sample(cur.cat, rng, exclude, kind, where=lambda x: not near(x, sc.peak))
            or pool.sample(cur.cat, rng, exclude, kind) or cur)


def _dedup(bp, pool, rng):
    """비복원: 이야기 전체에서 같은 재료는 한 번만 (고정축 슬롯은 예외)"""
    seen = set()
    for sc in bp.scenes:
        if not sc.free("bg"):
            seen |= footprint(sc.bg)
        if not sc.free("subj0"):
            seen |= footprint(sc.subj[0])
        for slot in sc.free_slots():
            x = sc.get(slot)
            if footprint(x) & seen:
                x = _replacement(sc, slot, pool, rng, seen | bp.used())
                sc.set(slot, x)
            seen |= footprint(x)


def _seed_and_distance(bp, pool, rng):
    """씨앗 규칙: 자유 슬롯 중 피크 장면 키워드는 정확히 1개, 나머지는 피크 ±2 밖"""
    for sc in bp.scenes:
        slots = sc.free_slots()
        seed_slot = next((sl for sl in slots if is_seed(sc.get(sl), sc.peak)), None)
        # 씨앗이 없으면 주입
        if seed_slot is None:
            cands = [x for x in pool.linked(sc.peak) if x.key not in bp.used()]
            rng.shuffle(cands)
            for x in cands:
                seed_slot = _place_seed(sc, x)
                if seed_slot:
                    break
        # 씨앗 외에 피크와 가까운 재료는 먼 재료로 교체
        for sl in sc.free_slots():
            if sl == seed_slot:
                continue
            x = sc.get(sl)
            if near(x, sc.peak):
                if x.generated:            # 생성 표현이면 재조합으로 먼 쪽 재료를 다시 찾는다
                    y = pool.recombine(pool.sample(x.cat, rng, bp.used(), sc.slot_kind(sl),
                                                   where=lambda k: not near(k, sc.peak)) or x.parts[1],
                                       rng, sc.peak, bp.used())
                    if y is not None and not near(y, sc.peak) and not (footprint(y) & bp.used()):
                        sc.set(sl, y)
                        continue
                sc.set(sl, _replacement(sc, sl, pool, rng, bp.used()))


def _place_seed(sc: Scene, x: Kw):
    if x.cat == "배경":
        return ("bg", 0) if sc.free("bg") else None
    if x.cat == "사물":
        if sc.slot_kind(("subj", 0)) == x.kind and sc.free("subj0"):
            sc.subj[0] = x
            return ("subj", 0)
        if len(sc.subj) < 2:
            sc.subj.append(x)
        else:
            sc.subj[1] = x
        return ("subj", len(sc.subj) - 1)
    lst = sc.states if x.cat == "상태" else sc.sounds
    name = "states" if x.cat == "상태" else "sounds"
    i = len(lst) - 1
    lst[i] = x
    return (name, i)


def _relations(bp):
    for sc in bp.scenes:
        if sc.rel and sc.rel["type"] == "합체" and len(sc.subj) < 2:
            sc.rel = None
        if sc.rel and REL_TYPES[sc.rel["type"]] is None:
            sc.rel["b"] = None


# ---------------- Open-Ended 변이 연산자 (상상 문법) ----------------
def op_recombine(bp, pool, rng):
    """재조합: 핵심어는 두고 다른 기억의 수식어를 붙여 새 표현을 만든다
    예) '파도 녹음' + '금속 바닥을 긁는' → '금속 바닥을 긁는 파도 녹음'"""
    sc = rng.choice(bp.scenes)
    slots = [sl for sl in sc.free_slots() if sl[0] in ("bg", "subj", "sounds", "relb")]
    if not slots:
        return None
    sl = rng.choice(slots)
    y = pool.recombine(sc.get(sl), rng, sc.peak, bp.used())
    if y is None or y.key in bp.used():
        return None
    sc.set(sl, y)
    sc.ops.append("재조합")
    return f"재조합({sc.role})"


def op_pivot(bp, pool, rng):
    """회전축 교체: 고정되지 않은 슬롯 하나를 풀에서 새로 뽑는다"""
    sc = rng.choice(bp.scenes)
    sl = rng.choice(sc.free_slots())
    sc.set(sl, _replacement(sc, sl, pool, rng, bp.used()))
    return f"교체({sc.role})"


def op_animate(bp, pool, rng):
    """의인화: 생명체 장면에서 나온 상태/소리를 무생물에 붙인다"""
    sc = rng.choice(bp.scenes)
    cat = rng.choice(["상태", "사운드"])
    x = pool.sample(cat, rng, bp.used(),
                    where=lambda k: bool(set(k.scenes) & pool.entity_scenes) and not near(k, sc.peak))
    if x is None:
        return None
    lst = sc.states if cat == "상태" else sc.sounds
    (lst.append(x) if len(lst) < 2 else lst.__setitem__(rng.randrange(2), x))
    sc.ops.append("의인화")
    return f"의인화({sc.role})"


def op_fuse(bp, pool, rng):
    """합체: 전혀 상관없는 사물을 주인공에 붙인다"""
    sc = rng.choice(bp.scenes)
    x = pool.sample("사물", rng, bp.used(), where=lambda k: not near(k, sc.peak))
    if x is None:
        return None
    (sc.subj.append(x) if len(sc.subj) < 2 else sc.subj.__setitem__(1, x))
    sc.rel = {"type": "합체", "b": None}
    return f"합체({sc.role})"


def op_relate(bp, pool, rng):
    """관계 부여: 안팎 뒤집기 / 재질 바꾸기 / 크기 뒤집기 / 소리를 눈으로 보기"""
    sc = rng.choice(bp.scenes)
    t = rng.choice(["포함역전", "재질치환", "크기역전", "공감각"])
    b = None
    if REL_TYPES[t]:
        b = pool.sample(REL_TYPES[t], rng, bp.used(), where=lambda k: not near(k, sc.peak))
        if b is None:
            return None
    sc.rel = {"type": t, "b": b}
    return f"{t}({sc.role})"


def op_grow(bp, pool, rng):
    """겹침: 상태나 소리를 하나 더 겹친다"""
    sc = rng.choice(bp.scenes)
    cat = rng.choice(["상태", "사운드"])
    lst = sc.states if cat == "상태" else sc.sounds
    if len(lst) >= 2:
        return None
    x = pool.sample(cat, rng, bp.used(), where=lambda k: not near(k, sc.peak))
    if x is None:
        return None
    lst.append(x)
    return f"겹침({sc.role})"


def op_drop(bp, pool, rng):
    """도태: 덧붙은 요소를 떼어 단순하게 만든다"""
    sc = rng.choice(bp.scenes)
    opts = []
    if len(sc.states) > 1: opts.append("state")
    if len(sc.sounds) > 1: opts.append("sound")
    if len(sc.subj) > 1: opts.append("subj")
    if sc.rel: opts.append("rel")
    if not opts:
        return None
    o = rng.choice(opts)
    if o == "state": sc.states.pop()
    elif o == "sound": sc.sounds.pop()
    elif o == "subj":
        sc.subj.pop()
        if sc.rel and sc.rel["type"] == "합체": sc.rel = None
    else: sc.rel = None
    return f"도태({sc.role}.{o})"


def op_swap(bp, pool, rng):
    """장면 간 교환: 두 장면이 상태나 소리를 서로 맞바꾼다"""
    a, b = rng.sample(bp.scenes, 2)
    if rng.random() < 0.5:
        i, j = rng.randrange(len(a.states)), rng.randrange(len(b.states))
        a.states[i], b.states[j] = b.states[j], a.states[i]
    else:
        i, j = rng.randrange(len(a.sounds)), rng.randrange(len(b.sounds))
        a.sounds[i], b.sounds[j] = b.sounds[j], a.sounds[i]
    return f"교환({a.role}↔{b.role})"


OPERATORS = [(op_recombine, 3), (op_pivot, 3), (op_animate, 1.5), (op_fuse, 1), (op_relate, 2),
             (op_grow, 1), (op_drop, 1.5), (op_swap, 1)]


def mutate(parent: Blueprint, pool: Pool, rng: random.Random) -> Blueprint:
    child = parent.clone()
    n = 1
    while rng.random() < 0.4 and n < 4:
        n += 1
    fns, ws = zip(*OPERATORS)
    for _ in range(n):
        tag = rng.choices(fns, ws)[0](child, pool, rng)
        if tag:
            child.lineage.append(tag)
    child.lineage = child.lineage[-40:]
    repair(child, pool, rng)
    return child


def crossover(a: Blueprint, b: Blueprint, pool: Pool, rng: random.Random) -> Blueprint:
    child = Blueprint([(x if rng.random() < 0.5 else y).clone() for x, y in zip(a.scenes, b.scenes)],
                      a.lineage[-20:] + ["교배"])
    repair(child, pool, rng)
    return child


# ======================================================================
# 4. 평가 함수 (Close-Ended 심판)
# ======================================================================
W = {"배경": 0.8, "사물": 0.5, "상태": 1.0, "사운드": 1.0}


def emotion_fit(sc: Scene, pool: Pool) -> float:
    ks = sc.keywords()
    return sum(W[k.cat] * pool.affinity(k, sc.emotion) for k in ks) / sum(W[k.cat] for k in ks)


def reproduction(sc: Scene) -> float:
    """원본 재현도: 원본의 같은 장면에 함께 있던 재료 쌍의 비율 (낮을수록 원본과 다름)"""
    ks = sc.keywords()
    pairs = list(combinations(ks, 2))
    if not pairs:
        return 0.0
    return sum(1 for a, b in pairs if set(a.scenes) & set(b.scenes)) / len(pairs)


def new_ratio(sc: Scene) -> float:
    ks = sc.keywords()
    return sum(1 for k in ks if k.generated) / len(ks)


def strangeness(sc: Scene, pool: Pool) -> float:
    ks = sc.keywords()
    pairs = list(combinations(ks, 2))
    d = sum(pool.context_distance(a, b) for a, b in pairs) / max(1, len(pairs))
    bonus = (0.15 if sc.rel else 0) + 0.05 * sc.ops.count("의인화") + 0.05 * sum(k.generated for k in ks)
    return min(1.0, d + bonus)


def evaluate(bp: Blueprint, pool: Pool) -> dict:
    emo = [emotion_fit(s, pool) for s in bp.scenes]
    rep = [reproduction(s) for s in bp.scenes]
    new = [new_ratio(s) for s in bp.scenes]
    stg = [strangeness(s, pool) for s in bp.scenes]
    tension = (int(stg[0] <= stg[1]) + int(stg[1] <= stg[2])) / 2   # 기 ≤ 승 ≤ 전
    quality = (0.5 * (sum(emo) / 4) + 0.15 * min(emo) + 0.15 * tension
               + 0.2 * (1 - sum(rep) / 4))
    return {"quality": quality, "emotion": emo, "reproduction": rep, "new": new,
            "strangeness": stg, "tension": tension, "bd": (sum(stg) / 4, sum(new) / 4)}


def jaccard(a: frozenset, b: frozenset) -> float:
    return 1 - len(a & b) / max(1, len(a | b))


def novelty(bp: Blueprint, others: list, k: int = 5) -> float:
    ks = bp.keyset()
    ds = sorted(jaccard(ks, o.keyset()) for o in others if o is not bp)
    return sum(ds[:k]) / max(1, min(k, len(ds))) if ds else 1.0


# ======================================================================
# 5. MAP-Elites 탐색 · 선택 · 장면 전환 · 내보내기
# ======================================================================
def cell_of(bd, bins):
    s, n = bd
    lo, hi = STG_RANGE
    si = min(bins - 1, max(0, int((s - lo) / (hi - lo) * bins)))
    ni = min(bins - 1, max(0, int(n * bins)))
    return si, ni


def map_elites(pool: Pool, rng: random.Random, iters=20000, bins=8, init=300, log_every=2000):
    """격자 축: 기묘함 × 새 표현 비율. 칸마다 최고 품질 설계도 1개를 보관"""
    archive: dict = {}
    log = []

    def insert(bp):
        ev = evaluate(bp, pool)
        c = cell_of(ev["bd"], bins)
        if c not in archive or ev["quality"] > archive[c][1]["quality"]:
            archive[c] = (bp, ev)

    for _ in range(init):
        insert(random_blueprint(pool, rng))
    for it in range(1, iters + 1):
        elites = list(archive.values())
        if rng.random() < 0.1 and len(elites) > 1:
            (a, _), (b, _) = rng.sample(elites, 2)
            child = crossover(a, b, pool, rng)
        else:
            child = mutate(rng.choice(elites)[0], pool, rng)
        insert(child)
        if it % log_every == 0:
            qs = [e["quality"] for _, e in archive.values()]
            log.append({"iter": it, "coverage": len(archive), "cells": bins * bins,
                        "best_q": round(max(qs), 3), "mean_q": round(sum(qs) / len(qs), 3)})
    return archive, log


def select(archive, rng: random.Random, curiosity=0.3, top_frac=0.2, temperature=0.03, n_alt=2):
    """Close-Ended 선택기
    1) 안전 조건: 모든 장면 감정 적합도 ≥ MIN_EMOTION, 평균 원본 재현도 ≤ MAX_REPRO,
                  평균 새 표현 비율 ≥ MIN_NEW
    2) 점수 = 품질 + 기묘함 × curiosity + 새로움 × 0.1
    3) 상위 top_frac 안에서 점수 기반 확률 선택 → 실행마다 다른 좋은 꿈
    """
    elites = [bp for bp, _ in archive.values()]
    scored = []
    for bp, ev in archive.values():
        ok = (min(ev["emotion"]) >= MIN_EMOTION and sum(ev["reproduction"]) / 4 <= MAX_REPRO
              and ev["bd"][1] >= MIN_NEW)
        nov = novelty(bp, elites)
        score = ev["quality"] + curiosity * ev["bd"][0] + 0.1 * nov
        scored.append((ok, score, bp, ev, nov))
    passed = [x for x in scored if x[0]] or scored
    passed.sort(key=lambda x: -x[1])
    top = passed[:max(3, int(len(passed) * top_frac))]
    ws = [math.exp((x[1] - top[0][1]) / temperature) for x in top]
    pick = rng.choices(top, ws)[0]
    alts = [x for x in top if x is not pick][:n_alt]
    return pick, alts


# ---------------- 장면 전환 (Open-Ended 연결) ----------------
MODES = {
    ("기", "승"): ["번짐", "공감각", "삼킴", "뒤집힘"],     # 공간의 변이
    ("승", "전"): ["녹아내림", "번짐", "공감각"],           # 사물의 변이
    ("전", "결"): ["삼킴", "뒤집힘", "공감각", "번짐"],     # 붕괴와 수렴
}
MODE_DESC = {
    "번짐": lambda b: f"앞 장면의 상태 {q(b, '이/가')} 물감처럼 번져 나가며 다음 장면을 물들인다",
    "공감각": lambda b: f"앞 장면의 소리 {q(b, '이/가')} 눈에 보이는 모양이 되어 다음 장면의 공간을 짓는다",
    "삼킴": lambda b: f"앞 장면의 공간 {q(b, '이/가')} 입을 벌려 모든 것을 삼킨 뒤 다른 곳으로 뱉어 낸다",
    "뒤집힘": lambda b: f"앞 장면의 공간 {q(b, '이/가')} 양말처럼 안팎이 뒤집히며 안쪽에서 다음 장면이 나온다",
    "녹아내림": lambda b: f"주인공 {q(b, '이/가')} 촛농처럼 녹아내려 다른 모양으로 굳는다",
}


def bridges(A, mode):
    if mode == "번짐": return A.states
    if mode == "공감각": return A.sounds
    if mode == "녹아내림": return [A.subj[0]]
    return [A.bg]


def make_transition(A, B, pool: Pool, rng: random.Random, used_modes: set, n_cand=12):
    """생성-평가: 여러 전환 후보를 만들고 점수로 고른다"""
    cands = []
    for _ in range(n_cand):
        mode = rng.choice(MODES[(A.role, B.role)])
        b = rng.choice(bridges(A, mode))
        emo_cont = (pool.affinity(b, A.emotion) + pool.affinity(b, B.emotion)) / 2
        lead = 1 - min(pool.context_distance(b, x) for x in B.keywords())
        fresh = 0.0 if mode in used_modes else 1.0
        score = 0.45 * emo_cont + 0.35 * lead + 0.2 * fresh + rng.uniform(0, 0.05)
        cands.append((score, mode, b))
    score, mode, b = max(cands, key=lambda x: x[0])
    used_modes.add(mode)
    steps = [{"순서": 1, "무엇이": b.text, "어떻게": mode}]
    diffs = []
    if A.bg.key != B.bg.key: diffs.append(("배경", A.bg.text, B.bg.text))
    if A.subj[0].key != B.subj[0].key: diffs.append(("주체", A.subj[0].text, B.subj[0].text))
    diffs.append(("상태", ", ".join(x.text for x in A.states), ", ".join(x.text for x in B.states)))
    diffs.append(("사운드", ", ".join(x.text for x in A.sounds), ", ".join(x.text for x in B.sounds)))
    for i, (slot, fr, to) in enumerate(diffs, start=2):
        steps.append({"순서": i, "슬롯": slot, "이전": fr, "이후": to})
    return {"from": A.role, "to": B.role, "방식": mode, "다리_요소": b.text,
            "설명": MODE_DESC[mode](b.text), "점수": round(score, 3), "변이_경로": steps}


# ---------------- 내보내기 ----------------
REL_DESC = {
    "포함역전": lambda bg, a, b, s: f"배경 '{bg}' 전체가 주인공 '{a}' 안에 통째로 들어 있다",
    "재질치환": lambda bg, a, b, s: f"배경 {q(bg, '이/가')} 전부 {q(b, '으로/로')} 만들어져 있다",
    "크기역전": lambda bg, a, b, s: f"주인공 {q(a, '이/가')} 배경 '{bg}'보다 훨씬 거대해졌다",
    "합체": lambda bg, a, b, s: f"{q(a, '과/와')} {q(b, '이/가')} 하나로 붙어 한 몸이 되었다",
    "공감각": lambda bg, a, b, s: f"소리 {q(s, '이/가')} 눈에 보이는 모양으로 떠다닌다",
}


def rel_text(sc):
    if not sc.rel:
        return None
    t = sc.rel["type"]
    b = sc.rel["b"].text if sc.rel.get("b") else (sc.subj[1].text if len(sc.subj) > 1 else "")
    return {"유형": t, "설명": REL_DESC[t](sc.bg.text, sc.subj[0].text, b, sc.sounds[0].text)}


def kw_info(k: Kw, sc: Scene) -> dict:
    d = {"키워드": k.text, "출처": list(k.scenes), "새_표현": k.generated,
         "씨앗": is_seed(k, sc.peak)}
    if k.kind:
        d["종류"] = k.kind
    if k.generated:
        d["재료"] = {"수식어": k.mod, "수식어_출처": k.parts[0].text,
                   "핵심어": k.head, "핵심어_출처": k.parts[1].text}
    if k.cat == "사운드":
        d["라벨"] = k.label
        d["원본_구간"] = k.spans
    return d


def export(bp: Blueprint, ev: dict, pool: Pool, transitions: list, extra: dict) -> dict:
    assign = {a["역할"]: a for a in pool.assign}
    scenes = []
    for i, sc in enumerate(bp.scenes):
        a = assign[sc.role]
        seed = next((k.text for k in sc.keywords() if is_seed(k, sc.peak)), None)
        scenes.append({
            "장면": i + 1, "역할": sc.role, "감정": sc.emotion,
            "피크": {"장면": sc.peak, "공감률": a["공감률"], "시간": a["시간"]},
            "기억의_씨앗": seed,
            "배경": sc.bg.text,
            "배경_상세": kw_info(sc.bg, sc),
            "주체": [kw_info(x, sc) for x in sc.subj],
            "관계": rel_text(sc),
            "관계_재료": kw_info(sc.rel["b"], sc) if sc.rel and sc.rel.get("b") else None,
            "상태": [x.text for x in sc.states],
            "상태_상세": [kw_info(x, sc) for x in sc.states],
            "사운드": [kw_info(x, sc) for x in sc.sounds],
            "고정축": {"기": "없음(진입)", "승": "주체 유지", "전": "배경 유지", "결": "기의 주체 복귀"}[sc.role],
            "지표": {"감정_적합도": round(ev["emotion"][i], 3), "원본_재현도": round(ev["reproduction"][i], 3),
                   "새_표현_비율": round(ev["new"][i], 3), "기묘함": round(ev["strangeness"][i], 3)},
        })
    all_kw = [k for sc in bp.scenes for k in sc.keywords()]
    return {"scenes": scenes, "transitions": transitions,
            "story_metrics": {"quality": round(ev["quality"], 3), "tension": ev["tension"],
                              "mean_strangeness": round(ev["bd"][0], 3),
                              "mean_new_ratio": round(ev["bd"][1], 3),
                              "mean_reproduction": round(sum(ev["reproduction"]) / 4, 3),
                              "original_keywords_used": sum(1 for k in all_kw if not k.generated),
                              "new_expressions": sum(1 for k in all_kw if k.generated)},
            "evolution_lineage": bp.lineage, **extra}


def handoff(bp_json: dict) -> dict:
    """다음 팀(배경/오브제 이미지 생성)으로 넘길 추출본"""
    def obj(x, kind=None):
        r = x.get("재료")
        return {"이름": x["키워드"], "종류": kind or x.get("종류", ""),
                "핵심": r["핵심어"] if r else x["키워드"], "속성": r["수식어"] if r else ""}
    out = []
    for s in bp_json["scenes"]:
        objs = [obj(x) for x in s["주체"]]
        if s["관계_재료"]:
            objs.append(obj(s["관계_재료"], "오브제(관계 재료)"))
        bg = s["배경_상세"]
        out.append({"장면": s["장면"], "역할": s["역할"], "감정": s["감정"],
                    "배경": {"장소": s["배경"], "핵심_장소": bg["재료"]["핵심어"] if bg.get("재료") else s["배경"],
                           "분위기_상태": s["상태"]},
                    "엔티티_오브제": objs,
                    "배치_관계": s["관계"]["설명"] if s["관계"] else "특별한 관계 없음"})
    return {"scenes": out}


def archive_map(archive, bins=8) -> str:
    lo, hi = STG_RANGE
    lines = ["MAP-Elites 아카이브 (칸 값 = 품질, 가로 = 기묘함 →, 세로 = 새 표현 비율 ↑)", ""]
    for ni in reversed(range(bins)):
        row = []
        for si in range(bins):
            v = archive.get((si, ni))
            row.append(f"{v[1]['quality']:.2f}" if v else "  · ")
        lines.append(f"새표현 {ni / bins:.2f}~ | " + " ".join(row))
    lines.append("             " + " ".join(f"{lo + (hi - lo) * i / bins:.2f}" for i in range(bins)))
    return "\n".join(lines)


# ======================================================================
# 6. 실행
# ======================================================================
def transitions_for(bp, pool, rng):
    used, out = set(), []
    for A, B in zip(bp.scenes, bp.scenes[1:]):
        out.append(make_transition(A, B, pool, rng, used))
    return out


def fmt_kw(k: dict) -> str:
    mark = ("✦" if k["새_표현"] else "") + ("●" if k["씨앗"] else "")
    return f"{mark}{k['키워드']}"


def main():
    # 폴더 구조: team1/src/step6_*.py  →  입출력은 team1/output/
    team_dir = Path(__file__).resolve().parent.parent
    output_dir = team_dir / "output"
    ap = argparse.ArgumentParser(description="Step 6: 오픈엔디드 변이 조립 엔진 v2")
    ap.add_argument("--pool", default=str(output_dir / "keyword_pool.json"), help="Step 5 출력 파일")
    ap.add_argument("--out-dir", default=str(output_dir), help="출력 폴더")
    ap.add_argument("--iters", type=int, default=20000, help="진화 탐색 횟수")
    ap.add_argument("--bins", type=int, default=8, help="MAP-Elites 격자 한 변 칸 수")
    ap.add_argument("--seed", type=int, default=None, help="고정하면 재현 가능, 비우면 매번 다른 꿈")
    ap.add_argument("--curiosity", type=float, default=0.3, help="최종 선택 시 기묘함 가중치")
    a = ap.parse_args()

    if not Path(a.pool).exists():
        raise SystemExit(f"[오류] 키워드 풀 파일이 없습니다: {a.pool}\n"
                         f"       Step 5(step5_extract_keywords)를 먼저 실행하세요.")
    rng = random.Random(a.seed)
    pool = Pool(a.pool)
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    print(f"[Step 6] 키워드 풀 로드: 배경 {len(pool.items['배경'])} / 사물 {len(pool.items['사물'])}"
          f" (엔티티 {len(pool.entities)}) / 상태 {len(pool.items['상태'])} / 사운드 {len(pool.items['사운드'])}"
          f" | 수식어 재료 {len(pool.mod_donors)}")
    print(f"[Step 6] MAP-Elites 탐색 시작 ({a.iters}회)...")
    archive, log = map_elites(pool, rng, iters=a.iters, bins=a.bins)
    for row in log:
        print(f"   iter {row['iter']:>6} | 격자 {row['coverage']}/{row['cells']} | 최고 품질 {row['best_q']} | 평균 {row['mean_q']}")

    (ok, score, bp, ev, nov), alts = select(archive, rng, curiosity=a.curiosity)
    extra = {"search": {"algorithm": "MAP-Elites", "version": "v2", "iters": a.iters, "seed": a.seed,
                        "coverage": f"{len(archive)}/{a.bins ** 2}", "selected_novelty": round(nov, 3),
                        "passed_constraints": ok},
             "source": Path(a.pool).name}
    bp_json = export(bp, ev, pool, transitions_for(bp, pool, rng), extra)
    alt_json = [export(b, e, pool, transitions_for(b, pool, rng), {}) for _, _, b, e, _ in alts]

    def dump(name, obj):
        with open(out / name, "w", encoding="utf-8") as f:
            if isinstance(obj, str):
                f.write(obj)
            else:
                json.dump(obj, f, ensure_ascii=False, indent=2)

    dump("assembled_blueprint.json", bp_json)
    dump("scene_handoff.json", handoff(bp_json))
    dump("step6_alternatives.json", alt_json)
    dump("step6_archive_map.txt", archive_map(archive, a.bins))
    dump("step6_evolution_log.json", log)

    m = bp_json["story_metrics"]
    print()
    print(archive_map(archive, a.bins))
    print(f"\n[선택] 품질={ev['quality']:.3f}  기묘함={ev['bd'][0]:.3f}  새표현={ev['bd'][1]:.3f}"
          f"  원본재현도={m['mean_reproduction']:.3f}  새로움={nov:.3f}  조건통과={ok}")
    print(f"       원본 키워드 {m['original_keywords_used']}개 + 새로 생성된 표현 {m['new_expressions']}개"
          f"   (● 기억의 씨앗, ✦ 새 표현)")
    for s in bp_json["scenes"]:
        rel = f" | 관계: {s['관계']['유형']}" if s["관계"] else ""
        print(f"  [{s['역할']}·{s['감정']}] 배경: {fmt_kw(s['배경_상세'])}"
              f" | 주체: {', '.join(fmt_kw(x) for x in s['주체'])}"
              f" | 상태: {', '.join(fmt_kw(x) for x in s['상태_상세'])}"
              f" | 사운드: {', '.join(fmt_kw(x) for x in s['사운드'])}{rel}")
        print(f"         재현도 {s['지표']['원본_재현도']:.2f} · 새표현 {s['지표']['새_표현_비율']:.2f}"
              f" · 감정적합 {s['지표']['감정_적합도']:.2f}")
    for t in bp_json["transitions"]:
        print(f"    {t['from']}→{t['to']} 전환: {t['방식']} (다리 요소: {t['다리_요소']})")
    print(f"\n[Step 6] 완료 → {out / 'assembled_blueprint.json'}")


if __name__ == "__main__":
    main()