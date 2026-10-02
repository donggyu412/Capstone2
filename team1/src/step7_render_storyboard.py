"""
Step 7. 꿈 서사 렌더링 엔진 (Dream Narrative Renderer)  — v4

위치: team1/src/step7_render_storyboard.py
입출력 폴더: team1/output/

[INPUT]  assembled_blueprint.json   (Step 6 출력: 4장면 설계도 + 장면 전환)
[OUTPUT] final_storyboard.json      (꿈 카드 4장 + 설계도 참조 + 생성 기록)
         final_storyboard.txt       (사람이 읽기 좋은 버전)

역할
  Step 6이 '무엇이 나오고 어떻게 변하는가'를 이미 정했다.
  Step 7(LLM)은 이야기를 지어내지 않고, 그 설계도를 7살 아이의 말로 '표현'만 한다.

v4 변경점 (v3 결과: 재시도의 대부분이 '~다' 말투 때문, 설계도 용어 노출)
  1) 반말 어미 규칙 변환기: '~다' 문장을 재시도 없이 즉시 반말로 고침 (to_banmal)
  2) '배경이/주체' 같은 설계도 용어 노출 검사 + 소리 이름 보존 규칙

v3 변경점 (v2 결과: 칸끼리 내용이 섞임, 소리를 사람 행동으로 오해, 관계 누락, '~다' 말투, 제목 환각)
  1) 칸별 재료 분리: 보여요=배경·주체·상태 / 들려요=소리 / 이상해요=관계 / 변해요=넘어가는 방법
  2) 칸별 검증: 보여요에 배경·주체, 들려요에 소리, 이상해요에 관계 단서, 변해요에 전환 단서
  3) 말투('~다' 금지)·길이 검사, 상태 누락 검사
  4) 제목은 꿈에 나온 말을 포함해야 통과

v2 변경점 (v1: 키워드를 그대로 베껴 쓰는 문제, 느린 재시도, 깨진 영어)
  1) 예시 1개(few-shot): 원하는 말투를 실제 예시로 보여 준다
  2) 장면별 생성: 한 번에 한 장면만 쓰고, 틀린 장면만 다시 쓴다
     (매번 '꿈 전체 흐름'과 '직전 장면에서 한 말'을 함께 줘서 이야기가 이어지게 함)
  3) 재시도는 대화 기록을 쌓지 않고 '지난번 문제' 한 줄만 붙여 새로 요청
  4) 검증 강화: 문장인가 / 전환 이름만 적지 않았나 / 마지막 장면에서 깨어나는가
  5) 공통 프롬프트를 앞에 고정해 Ollama 캐시 재사용, 출력 길이 상한

Close-Ended 장치
  JSON 스키마 강제 + 사후 검증(핵심어 등장, 문장 형태, 한자·영어 혼입) + 설계도 값으로 역할·감정 고정

꿈 카드 형식
  보여요 / 들려요 / 이상해요 / 변해요(마지막은 깨어나요)

필요 설치
  - Ollama + 모델:  ollama pull qwen2.5:7b
  - pip install pydantic requests

실행 예 (Capstone2 폴더에서):
  python team1/src/step7_render_storyboard.py
  python team1/src/step7_render_storyboard.py --model exaone3.5:2.4b   # 저사양 노트북용 (한국어 특화, 빠름)
  python team1/src/step7_render_storyboard.py --offline                 # LLM 없이 규칙 기반 초안
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

try:
    from pydantic import BaseModel, Field, ValidationError
except ImportError:
    sys.exit("[오류] pydantic이 없습니다. venv에서 `pip install pydantic requests`를 실행하세요.")


# ======================================================================
# 1. 출력 스키마 (장면 1개 단위)
# ======================================================================
class SceneCard(BaseModel):
    see: str = Field(description="보여요: 눈앞에 보이는 것을 2~3문장으로")
    hear: str = Field(description="들려요: 들리는 소리와 그때 몸의 느낌을 1~2문장으로")
    strange: str = Field(description="이상해요: 꿈이라서 가능한 이상한 점을 1~2문장으로")
    morph: str = Field(description="변해요: 다음 장면으로 변하는 모습(마지막은 깨어나는 순간)을 1~2문장으로")


class Title(BaseModel):
    title: str = Field(description="꿈의 제목")


# ======================================================================
# 2. 프롬프트
# ======================================================================
SYSTEM = """너는 세상에 대한 고정관념이 아직 없는 7살 아이야. 방금 꿈에서 깨어나서, 꿈에서 본 장면을 엄마에게 한 장면씩 말해 주고 있어.

말하는 방식:
- 반말로, 완성된 문장으로 말해. 문장 끝은 '~어', '~야', '~해', '~거든' 같은 말투야. '~다', '~본다', '~했다'처럼 책 읽는 말투로 끝내지 마.
- 한국어로만 말해. 한자, 중국어, 영어, 로마자는 한 글자도 쓰지 마.
- '무서워', '슬퍼', '놀랐어' 같은 감정 단어는 쓰지 말고, 몸의 느낌이나 행동으로 보여 줘. (예: 심장이 쿵쿵해, 목이 꽉 막혀, 다리가 굳어)
- 어른처럼 설명하거나 교훈을 말하지 마. 어려운 말(예: '이는', '양면')도 쓰지 마.
- '배경', '주체', '상태', '관계', '재료' 같은 설계도 용어는 말하지 마. 그 장소나 물건의 이름으로 말해.
- 소리 이름은 바꾸지 말고 그대로 써. (예: '엔진의 낮은 험'을 '험한 소리'로 바꾸지 마)

칸마다 쓸 재료가 정해져 있어. 각 칸에는 그 칸의 재료만 써.
- 보여요 (2~3문장): 배경, 주체, 상태. 눈에 보이는 것만. 소리 이야기는 여기서 하지 마.
- 들려요 (1~2문장): 소리 재료와 그 소리를 들을 때 몸의 느낌. 소리 재료는 전부 '소리'야. 소리를 사람이나 물건의 행동으로 바꾸지 마.
- 이상해요 (1~2문장): '관계'에 적힌 이상한 모습. 꿈속의 너는 그걸 늦게 알아차려.
- 변해요 (1~2문장): '넘어가는 방법'에 적힌 모습을 눈에 보이게 그려 줘. '삼킴', '번짐' 같은 방법 이름만 쓰면 안 돼.

장면 설계도 지키기:
- 배경과 주체의 이름은 보여요에서 한 번은 꼭 그대로 말해. 이상하게 붙은 이름(예: '우산을 쓴 고양이')도 고치지 말고 꿈에서 본 그대로 믿고 말해.
- 설계도에 없는 새로운 인물, 장소, 탈것, 중요한 물건을 만들지 마.
- 장면은 직전 장면의 마지막 모습에서 이어져 시작해. 이 장면의 '넘어가는 방법'은 변해요에서만 써.
- 마지막 장면의 변해요는 꿈에서 깨어나는 순간이야.

[예시]
장면 설계도:
보여요 재료 - 배경: 사탕으로 만든 계단 / 주체: 우산을 쓴 고양이 / 상태: 녹아내리는
들려요 재료 - 소리: 빗방울이 피아노를 치는 소리
이상해요 재료 - 관계: 배경 '사탕으로 만든 계단' 전체가 주인공 '우산을 쓴 고양이' 안에 통째로 들어 있다
변해요 재료 - 넘어가는 방법: 앞 장면의 소리 '빗방울이 피아노를 치는 소리'가 눈에 보이는 모양이 되어 다음 장면의 공간을 짓는다
출력:
{"see": "나는 사탕으로 만든 계단 위에 서 있어. 계단이 자꾸 녹아내려서 발바닥이 끈적끈적 달라붙어. 맨 위에서 우산을 쓴 고양이가 나를 가만히 내려다보고 있어.", "hear": "빗방울이 피아노를 치는 소리가 들리는데, 한 방울 떨어질 때마다 내 심장도 같이 쿵 하고 떨어져.", "strange": "근데 고양이 배 속을 들여다보니까, 내가 서 있는 계단이 통째로 거기 들어 있었어. 그럼 나는 지금 어디에 있는 거야?", "morph": "피아노 소리가 점점 동그란 건반 모양으로 굳더니, 건반들이 차곡차곡 쌓여서 새로운 방이 되었어."}

출력은 오직 JSON 하나만."""


def story_summary(bp: dict) -> str:
    """모든 장면 요청에 똑같이 들어가는 '꿈 전체 흐름' (프롬프트 앞부분 고정 → 캐시 재사용)"""
    lines = ["[꿈 전체 흐름]"]
    for s in bp["scenes"]:
        subj = ", ".join(x["키워드"] for x in s["주체"])
        lines.append(f"{s['장면']}. ({s['역할']}·{s['감정']}) {s['배경']}에서 {subj}")
    return "\n".join(lines)


def scene_prompt(bp: dict, idx: int, prev_card: dict | None, issue: str | None) -> str:
    """칸별 재료를 나눠서 준다 (보여요/들려요/이상해요/변해요 재료가 섞이지 않게)"""
    s = bp["scenes"][idx]
    trans = {t["from"]: t for t in bp["transitions"]}
    t = trans.get(s["역할"])
    move = t["설명"] if t else "꿈에서 깨어난다 (눈을 뜨고, 꿈의 느낌이 몸에 조금 남아 있다)"
    rel = s["관계"]["설명"] if s.get("관계") else "특별한 관계 없음 (대신 장면 속에서 가장 이상한 점을 말해)"
    parts = [story_summary(bp), ""]
    if prev_card:
        parts += ["[직전 장면의 마지막 모습 — 이 장면은 여기서 이어져 시작해]", prev_card["morph"], ""]
    parts += [f"[지금 말할 장면: {s['장면']}번째 / 4 · 감정: {s['감정']}]",
              "장면 설계도:",
              f"보여요 재료 - 배경: {s['배경']} / 주체: {', '.join(x['키워드'] for x in s['주체'])}"
              f" / 상태: {', '.join(s['상태'])}",
              f"들려요 재료 - 소리: {', '.join(x['키워드'] + '(소리)' for x in s['사운드'])}",
              f"이상해요 재료 - 관계: {rel}",
              f"변해요 재료 - 넘어가는 방법: {move}"]
    if issue:
        parts.append(f"\n(주의: 지난번에 이런 문제가 있었어. 꼭 고쳐 줘: {issue})")
    parts.append("\n출력:")
    return "\n".join(parts)


# ======================================================================
# 2-1. 반말 어미 변환 (Close-Ended 후처리)
#   LLM이 자꾸 '~다'(책 읽는 말투)로 끝내는 문제를 재시도 대신 규칙으로 고친다.
#   크다→커, 뱉어냈다→뱉어냈어, 깨어난다→깨어나, 감돈다→감돌아, 차갑다→차가워, 것이다→거야
# ======================================================================
# ---------------- 반말 어미 변환 (Close-Ended 후처리) ----------------
_CHO = 19; _JUNG = 21; _JONG = 28
J_A, J_AE, J_EO, J_E, J_O, J_WA, J_OE, J_U, J_WEO, J_WI, J_EU, J_UI, J_I = 0, 1, 4, 5, 8, 9, 11, 13, 14, 16, 18, 19, 20
JONG_N, JONG_L, JONG_B, JONG_SS = 4, 8, 17, 20
B_IRREG = {"차갑", "무겁", "가볍", "뜨겁", "어둡", "무섭", "가깝", "아름답", "반갑", "귀엽", "즐겁",
           "어렵", "쉽", "춥", "덥", "밉", "시끄럽", "간지럽", "부드럽", "날카롭", "외롭", "괴롭", "새롭"}
L_STEMS = {"돌", "살", "열", "울", "놀", "불", "풀", "걸", "밀", "떨", "들", "흔들", "만들", "팔", "빨", "갈", "알"}


def _dec(c):
    n = ord(c) - 0xAC00
    return n // (_JUNG * _JONG), (n // _JONG) % _JUNG, n % _JONG


def _com(cho, jung, jong=0):
    return chr(0xAC00 + (cho * _JUNG + jung) * _JONG + jong)


def _is_h(c):
    return "가" <= c <= "힣"


def conj_eo(stem: str) -> str:
    """용언 어간 + 아/어 (반말 종결형): 크→커, 보→봐, 되→돼, 하→해, 떠다니→떠다녀, 차갑→차가워"""
    if not stem or not _is_h(stem[-1]):
        return stem + "어"
    last, head = stem[-1], stem[:-1]
    if stem.endswith("하"):
        return head + "해"
    cho, jung, jong = _dec(last)
    bright = jung in (J_A, J_O)
    if jong:
        if jong == JONG_B and stem in B_IRREG or (jong == JONG_B and any(stem.endswith(x) for x in B_IRREG)):
            return head + _com(cho, jung) + "워"
        return stem + ("아" if bright else "어")
    if last == "르" and head and _is_h(head[-1]):            # 르 불규칙: 흐르→흘러, 빠르→빨라
        pc, pj, _ = _dec(head[-1])
        return head[:-1] + _com(pc, pj, JONG_L) + ("라" if pj in (J_A, J_O) else "러")
    if jung == J_EU:                                         # ㅡ 탈락: 크→커, 바쁘→바빠
        prev_bright = bool(head) and _is_h(head[-1]) and _dec(head[-1])[1] in (J_A, J_O)
        return head + _com(cho, J_A if prev_bright else J_EO)
    table = {J_O: J_WA, J_U: J_WEO, J_I: 6, J_OE: 10}        # 6=ㅕ, 10=ㅙ
    if jung in table:
        if jung == J_I and cho == 11:                        # 이 → 여
            return head + "여"
        return head + _com(cho, table[jung])
    return stem                                              # 가/서/내/세… 는 그대로(가, 서, 보내)


def _stem_from_plain(word: str):
    """'~다' 앞부분 → 어간 (과거형이면 None: 그대로 '다'→'어')"""
    body = word[:-1]                                         # '다' 제거
    if not body or not _is_h(body[-1]):
        return body, "plain"
    if body.endswith("는"):                                   # 먹는다 → 먹
        return body[:-1], "stem"
    cho, jung, jong = _dec(body[-1])
    if jong == JONG_SS:                                      # 했다/뱉어냈다 → 과거
        return body, "past"
    if jong == JONG_N:                                       # 난다/된다/감돈다
        base = body[:-1] + _com(cho, jung)
        for ls in L_STEMS:                                   # ㄹ 탈락 복원: 돈→돌, 든→들
            c2, j2, _ = _dec(ls[-1])
            if base.endswith(ls[:-1] + _com(c2, j2)) and ls[-1] != base[-1]:
                return base[:-len(ls)] + ls, "stem"
        return base, "stem"
    return body, "stem"                                      # 크다/있다/같다/차갑다


def fix_sentence_end(sent: str) -> str:
    """문장 끝의 '~다'를 반말로: 크다→커, 뱉어냈다→뱉어냈어, 깨어난다→깨어나, 것이다→거야"""
    m = re.match(r"^(.*?)([가-힣]+)다([.!?…~\s\"']*)$", sent)
    if not m:
        return sent
    pre, word, tail = m.group(1), m.group(2) + "다", m.group(3)
    if word.endswith("것이다"):
        return pre + word[:-3] + "거야" + tail
    if word.endswith("이다") and len(word) > 2:
        w = word[:-2]
        return pre + w + ("이야" if _is_h(w[-1]) and _dec(w[-1])[2] else "야") + tail
    stem, kind = _stem_from_plain(word)
    if kind == "past":
        return pre + stem + "어" + tail
    return pre + conj_eo(stem) + tail


def to_banmal(text: str) -> str:
    parts = re.split(r"(?<=[.!?…])\s+", text.strip())
    return " ".join(fix_sentence_end(p) for p in parts)


# ======================================================================
# 3. 사후 검증 (Close-Ended)
# ======================================================================
HAN = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\u3040-\u30ff]")   # 한자·중국어·일본어 가나
LATIN = re.compile(r"[A-Za-z]{2,}")
MODE_NAMES = {"번짐", "공감각", "삼킴", "뒤집힘", "녹아내림", "없음"}
WAKE_WORDS = ["깼", "깨어", "깨났", "눈을 떴", "눈을 뜨", "눈 떴", "일어났", "잠에서"]
ENDINGS = set("요다어아야해지네걸까나봐라래게고서데니며여워와져줘겨려돼거대자써떠켜쳐혀펴")
FIELD_KO = {"see": "보여요", "hear": "들려요", "strange": "이상해요", "morph": "변해요"}


def core_words(item: dict) -> list:
    """새 표현이면 핵심어, 원본이면 키워드에서 2글자 이상 어절"""
    base = item["재료"]["핵심어"] if item.get("재료") else item["키워드"]
    return [w for w in base.replace(",", " ").split() if len(w) >= 2] or [base]


def is_sentence(text: str) -> bool:
    """단어 나열이 아니라 끝맺은 문장인가: 마침표류로 끝나거나, 반말/존댓말 어미로 끝남"""
    raw = text.strip()
    t = raw.rstrip(".!?…~ \"'")
    if len(raw) < 8 or " " not in raw or not t:
        return False
    return raw[-1] in ".!?…~" or t[-1] in ENDINGS


REL_CUES = {
    "크기역전": ["커", "크", "거대", "거인", "높"],
    "포함역전": ["안에", "속에", "속으로", "안으로", "들어"],
    "합체": ["붙", "한 몸", "하나로", "하나가", "합쳐"],
    "공감각": ["보여", "보이", "모양", "색깔", "떠다", "만질"],
    "재질치환": ["만들어", "로 된", "으로 된", "만든"],
}
MODE_CUES = {
    "번짐": ["번지", "번져", "번졌", "물들", "스며"],
    "공감각": ["모양", "보이", "보여", "생기", "지어", "쌓", "변해", "변했", "되었", "됐"],
    "삼킴": ["삼키", "삼켜", "삼켰", "뱉", "입을"],
    "뒤집힘": ["뒤집", "안팎"],
    "녹아내림": ["녹", "흘러내", "굳"],
}


def sentences(text: str) -> list:
    return [x.strip() for x in re.split(r"(?<=[.!?…])\s+", text.strip()) if x.strip()]


def verify_scene(card: SceneCard, s: dict, is_last: bool, mode: str | None = None) -> list:
    problems = []
    f = card.model_dump()
    whole = " ".join(f.values())
    # 1) 문장 형태 · 말투 · 길이
    for k, v in f.items():
        if v.strip() in MODE_NAMES:
            problems.append(f"'{FIELD_KO[k]}'에 방법 이름만 적음 → 모습을 문장으로 그려 줘")
            continue
        if not is_sentence(v):
            problems.append(f"'{FIELD_KO[k]}'가 완성된 문장이 아님 → 반말 문장으로 끝맺어 줘")
        adult = [x for x in sentences(v) if x.rstrip(".!?…~ ").endswith("다")]
        if adult:
            problems.append(f"'{FIELD_KO[k]}'가 '~다' 말투로 끝남('{adult[0][-12:]}') → '~어/~야/~해'로 바꿔 줘")
        limit = 3 if k == "see" else 2
        if len(sentences(v)) > limit + 1:
            problems.append(f"'{FIELD_KO[k]}'가 너무 김({len(sentences(v))}문장) → {limit}문장 이내로 줄여 줘")
    # 2) 칸별 재료
    for item in [s["배경_상세"]] + s["주체"]:
        words = core_words(item)
        if not any(w in f["see"] for w in words):
            problems.append(f"보여요에 {_j(repr(item['키워드']), '이/가')} 빠짐 → '{'/'.join(words)}'라는 말을 꼭 넣어 줘")
    # 보여요에 소리 이야기가 새어 들어갔는가 (설계도 키워드 안의 '소리'는 제외)
    see_rest = f["see"]
    for kw in [s["배경"]] + [x["키워드"] for x in s["주체"]] + s["상태"]:
        see_rest = see_rest.replace(kw, "")
    if any(w in see_rest for w in ("소리", "들려", "들리고", "들리는데")):
        problems.append("보여요에 소리 이야기가 섞임 → 소리는 들려요에서만 말하고, 보여요는 눈에 보이는 것만 말해 줘")
    snd_words = [w for x in s["사운드"] for w in core_words(x)]
    if not any(w in f["hear"] for w in snd_words):
        problems.append(f"들려요에 설계도의 소리가 없음 → '{s['사운드'][0]['키워드']}'를 소리로 말해 줘")
    # 상태는 활용형이 바뀌므로 어간으로 비교 ('멈춘' → '멈', '차가운' → '차가')
    stems = [w[:-1] if len(w) >= 3 else w[:1] for st in s["상태"] for w in st.split() if len(w) >= 2]
    if stems and not any(x in whole for x in stems):
        problems.append(f"상태 {_j(repr(', '.join(s['상태'])), '이/가')} 빠짐 → 보여요에 그 모습을 넣어 줘")
    if s.get("관계"):
        cues = REL_CUES.get(s["관계"]["유형"], [])
        if cues and not any(c in f["strange"] for c in cues):
            problems.append(f"이상해요에 관계가 안 보임 → '{s['관계']['설명']}' 모습을 말해 줘")
    if mode and not is_last:
        cues = MODE_CUES.get(mode, [])
        if cues and not any(c in f["morph"] for c in cues):
            problems.append(f"변해요에 '{mode}' 모습이 안 보임 → 넘어가는 방법대로 그려 줘")
    # 3) 설계도 용어가 그대로 새어 나왔는가 ('배경이 차가워서' 같은 문장)
    leaked = [w for w in ("배경이", "배경은", "배경을", "배경의", "배경에", "주체", "설계도", "재료") if w in whole]
    if leaked:
        problems.append(f"설계도 용어를 그대로 씀({', '.join(leaked)}) → 그 장소나 물건의 이름으로 말해 줘")
    # 4) 문자
    if HAN.search(whole):
        problems.append(f"한자/외국 문자가 섞임({''.join(HAN.findall(whole))[:6]}) → 한글로만 써 줘")
    if LATIN.search(whole):
        problems.append(f"영어가 섞임({', '.join(LATIN.findall(whole)[:3])}) → 한글로만 써 줘")
    if is_last and not any(w in card.morph for w in WAKE_WORDS):
        problems.append("마지막 장면의 '변해요'에서 꿈에서 깨어나지 않음 → 눈을 뜨고 깨어나는 순간을 말해 줘")
    return problems


# ======================================================================
# 4. LLM 호출 (Ollama REST API)
# ======================================================================
def check_ollama(host: str, model: str):
    import requests
    try:
        r = requests.get(f"{host}/api/tags", timeout=5)
        r.raise_for_status()
    except Exception:
        sys.exit(f"[오류] Ollama 서버({host})에 연결할 수 없습니다.\n"
                 f"       Ollama가 실행 중인지 확인하세요 (작업 표시줄 트레이의 라마 아이콘, 또는 `ollama serve`).")
    names = [m.get("name", "") for m in r.json().get("models", [])]
    if not any(n == model or n.split(":")[0] == model for n in names):
        sys.exit(f"[오류] 모델 '{model}'이 없습니다. 설치된 모델: {names or '없음'}\n"
                 f"       `ollama pull {model}`을 먼저 실행하세요.")


def chat(host, model, user, schema, temperature, num_predict):
    import requests
    r = requests.post(f"{host}/api/chat", timeout=900, json={
        "model": model, "stream": False, "format": schema,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        "options": {"temperature": temperature, "num_ctx": 4096, "num_predict": num_predict},
        "keep_alive": "10m"})
    r.raise_for_status()
    return r.json()["message"]["content"]


def render_llm(bp: dict, model: str, host: str, retries: int, temperature: float):
    cards, all_problems, log = [], [], []
    schema = SceneCard.model_json_schema()
    n = len(bp["scenes"])
    for idx, s in enumerate(bp["scenes"]):
        prev = cards[-1] if cards else None
        best, best_p, issue = None, None, None
        for attempt in range(1, retries + 1):
            t0 = time.time()
            print(f"[Step 7] 장면 {idx + 1}/{n} ({s['역할']}·{s['감정']}) 시도 {attempt}/{retries} ... ",
                  end="", flush=True)
            raw = chat(host, model, scene_prompt(bp, idx, prev, issue), schema, temperature, 450)
            dt = time.time() - t0
            try:
                card = SceneCard.model_validate_json(raw)
            except ValidationError:
                print(f"형식 오류 ({dt:.0f}초)")
                log.append({"scene": idx + 1, "attempt": attempt, "result": "schema_error", "seconds": round(dt, 1)})
                issue = "정해진 JSON 형식(see, hear, strange, morph)으로만 출력해 줘"
                continue
            mode = next((t["방식"] for t in bp["transitions"] if t["from"] == s["역할"]), None)
            before = card.model_dump()
            card = SceneCard(**{k: to_banmal(v) for k, v in before.items()})
            fixed = sum(1 for k in before if before[k].strip() != getattr(card, k))
            problems = verify_scene(card, s, idx == n - 1, mode)
            log.append({"scene": idx + 1, "attempt": attempt, "result": "ok" if not problems else "verify_fail",
                        "problems": problems, "banmal_fixed_fields": fixed, "seconds": round(dt, 1)})
            if best is None or len(problems) < len(best_p):
                best, best_p = card, problems
            if not problems:
                print(f"통과 ({dt:.0f}초" + (f", 말투 자동 변환 {fixed}칸)" if fixed else ")"))
                break
            print(f"문제 {len(problems)}개 ({dt:.0f}초)")
            for p in problems:
                print(f"      - {p}")
            issue = " / ".join(problems[:3])     # 프롬프트가 길어지지 않게 3개까지만
        if best is None:
            sys.exit(f"[오류] 장면 {idx + 1}에서 올바른 JSON을 받지 못했습니다. 다시 실행하거나 --retries를 늘리세요.")
        cards.append(best.model_dump())
        all_problems += [f"{idx + 1}번 카드: {p}" for p in best_p]

    # 제목: 짧은 호출 1번. 꿈에 나온 말을 포함해야 통과, 실패하면 규칙 기반 제목
    title = None
    dream_words = []
    for sc in bp["scenes"]:
        for it in [sc["배경_상세"]] + sc["주체"]:
            for w in core_words(it)[-1:]:
                if w not in dream_words:
                    dream_words.append(w)
    try:
        t0 = time.time()
        print("[Step 7] 제목 짓기 ... ", end="", flush=True)
        user = ("다음은 네가 방금 말한 꿈이야.\n" + "\n".join(f"{i + 1}. {c['see']}" for i, c in enumerate(cards))
                + f"\n\n이 꿈에 7살 아이가 붙일 만한 짧은 제목을 하나 지어 줘. 15자 이내, 한글로만."
                + f" 꿈에 나온 것({', '.join(dream_words[:6])}) 중 하나를 꼭 넣고, 꿈에 없던 것은 넣지 마.\n출력:")
        title = Title.model_validate_json(chat(host, model, user, Title.model_json_schema(), temperature, 40)).title.strip()
        if (HAN.search(title) or LATIN.search(title) or not (2 <= len(title) <= 25)
                or not any(w in title for w in dream_words)):
            title = None
        print(f"{title or '실패 → 기본 제목 사용'} ({time.time() - t0:.0f}초)")
    except Exception:
        print("실패 → 기본 제목 사용")
    return cards, title or default_title(bp), all_problems, log


# ======================================================================
# 5. 오프라인 대체 렌더러 (LLM 없이 파이프라인 테스트용)
# ======================================================================
def _j(w: str, pair: str) -> str:
    a, b = pair.split("/")
    c = next((ch for ch in reversed(w) if "가" <= ch <= "힣"), None)
    return w + (a if c and (ord(c) - 0xAC00) % 28 else b)


def default_title(bp: dict) -> str:
    return f"{_j(bp['scenes'][0]['주체'][0]['키워드'], '이/가')} 건너간 네 개의 방"


def render_offline(bp: dict):
    trans = {t["from"]: t for t in bp["transitions"]}
    cards = []
    for s in bp["scenes"]:
        subj = s["주체"][0]["키워드"]
        see = f"나는 {s['배경']}에 있어. {s['상태'][0]} {_j(subj, '이/가')} 보여."
        if len(s["주체"]) > 1:
            see += f" 옆에는 {s['주체'][1]['키워드']}도 있어."
        snd = [x["키워드"] for x in s["사운드"]]
        hear = f"{_j(snd[0], '이/가')} 들려." + (f" 그 사이로 {snd[1]}도 들려." if len(snd) > 1 else "")
        strange = ("근데 이상해. " + s["관계"]["설명"] + ".") if s.get("관계") \
            else f"근데 이상해. {_j(subj, '은/는')} 아무렇지도 않아 보여."
        t = trans.get(s["역할"])
        morph = (t["설명"] + ".") if t else "그러다 눈을 떴어. 귀에 소리가 아직 조금 남아 있어."
        cards.append({"see": see, "hear": hear, "strange": strange, "morph": morph})
    return cards, default_title(bp), [], []


# ======================================================================
# 6. 저장
# ======================================================================
def to_output(cards: list, title: str, bp: dict, meta: dict) -> dict:
    out = []
    for c, s in zip(cards, bp["scenes"]):
        out.append({
            "장면": s["장면"], "역할": s["역할"], "감정": s["감정"],
            "보여요": c["see"].strip(), "들려요": c["hear"].strip(),
            "이상해요": c["strange"].strip(), "변해요": c["morph"].strip(),
            "설계도": {"배경": s["배경"], "주체": [x["키워드"] for x in s["주체"]],
                    "상태": s["상태"], "사운드": [x["키워드"] for x in s["사운드"]],
                    "관계": s["관계"]["유형"] if s.get("관계") else None,
                    "기억의_씨앗": s.get("기억의_씨앗")},
        })
    return {"title": title, "cards": out, "render": meta}


def to_text(out: dict) -> str:
    lines = [f"■ {out['title']}", ""]
    for c in out["cards"]:
        lines += [f"[{c['장면']}. {c['역할']} · {c['감정']}]",
                  f"  보여요   {c['보여요']}",
                  f"  들려요   {c['들려요']}",
                  f"  이상해요 {c['이상해요']}",
                  f"  {'변해요  ' if c['역할'] != '결' else '깨어나요'} {c['변해요']}", ""]
    r = out["render"]
    extra = f", 총 {r['total_seconds']}초" if r.get("total_seconds") else ""
    lines.append(f"(renderer={r['renderer']}, model={r.get('model')}, 남은 검증 문제={len(r.get('problems', []))}개{extra})")
    return "\n".join(lines)


# ======================================================================
# 7. 실행
# ======================================================================
def main():
    output_dir = Path(__file__).resolve().parent.parent / "output"
    ap = argparse.ArgumentParser(description="Step 7: 꿈 서사 렌더링 v2")
    ap.add_argument("--blueprint", default=str(output_dir / "assembled_blueprint.json"))
    ap.add_argument("--out-dir", default=str(output_dir))
    ap.add_argument("--model", default="qwen2.5:7b")
    ap.add_argument("--host", default="http://localhost:11434")
    ap.add_argument("--retries", type=int, default=3, help="장면당 최대 시도 횟수")
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--offline", action="store_true", help="LLM 없이 규칙 기반 초안 생성")
    a = ap.parse_args()

    bp_path = Path(a.blueprint)
    if not bp_path.exists():
        sys.exit(f"[오류] 설계도 파일이 없습니다: {bp_path}\n       Step 6(step6_assemble_blueprint)을 먼저 실행하세요.")
    bp = json.loads(bp_path.read_text(encoding="utf-8"))
    print(f"[Step 7] 설계도 로드: {bp_path.name} (장면 {len(bp['scenes'])}개, 전환 {len(bp['transitions'])}개)")

    t_start = time.time()
    if a.offline:
        cards, title, problems, log = render_offline(bp)
        meta = {"renderer": "offline"}
    else:
        check_ollama(a.host, a.model)
        print(f"[Step 7] 모델: {a.model} (첫 호출은 모델을 메모리에 올리느라 더 오래 걸립니다)")
        cards, title, problems, log = render_llm(bp, a.model, a.host, a.retries, a.temperature)
        meta = {"renderer": "llm", "model": a.model, "temperature": a.temperature}
    meta.update({"problems": problems, "attempts": log, "blueprint": bp_path.name,
                 "total_seconds": round(time.time() - t_start)})

    out = to_output(cards, title, bp, meta)
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "final_storyboard.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "final_storyboard.txt").write_text(to_text(out), encoding="utf-8")

    print()
    print(to_text(out))
    if problems:
        print("\n[경고] 일부 장면이 검증을 완전히 통과하지 못했습니다 (가장 나은 결과를 저장):")
        for p in problems:
            print(f"   - {p}")
    print(f"\n[Step 7] 완료 → {out_dir / 'final_storyboard.json'}")


if __name__ == "__main__":
    main()