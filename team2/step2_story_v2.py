# -*- coding: utf-8 -*-
"""
step2_story_v2.py
emotion_peaks.txt → 4개 꿈 장면 생성

[파이프라인]
장면1: 1팀 assembled_blueprint.json 첫 장면 재료 사용 (없으면 emotion_peaks 풀 폴백)
장면2~4: 이전 장면 elements + 타임테이블 전체 재료에서 Dream Drift + 코사인 유사도 샘플링 → 글 생성

[조정 가능한 값]
- COHERENCE   : 장면 간 연결 강도 (0=꿈처럼 단절, 1=이야기처럼 연결)
- TEMPERATURE : 샘플링 랜덤성 (높을수록 무작위)
- MAX_DRIFT   : 분위기 변화 최대폭
- BG_RANGE / OBJ_RANGE / EMO_RANGE : (최소, 최대) 재료 개수 범위
  실제 개수는 1팀 공감 비율 P에 의해 이항분포로 결정됨
"""
import json
import math
import os
import random
import re
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL_EXTRACT = "claude-haiku-4-5-20251001"
MODEL_STORY   = "claude-sonnet-5"

# ── 재료 개수 범위 (L=최소, U=최대) ──────────────────
# 실제 개수는 공감 비율 P로 N = L + Binomial(U-L, q) 결정
BG_RANGE  = (1, 2)   # (L_c, U_c) for 배경
OBJ_RANGE = (1, 3)   # (L_c, U_c) for 오브제
EMO_RANGE = (1, 3)   # (L_c, U_c) for 감정

# ── Dream State Machine 파라미터 ─────────────────────
COHERENCE   = 0.9   # 벡터 drift 크기만 좌우 (낮을수록 분위기가 크게 튄다)
TEMPERATURE = 0.3   # 0.0 ~ 1.0  (낮을수록 알고리즘 주도, 높을수록 랜덤)
MAX_DRIFT   = 0.2   # 분위기 변화 최대폭. Hourglass 축이 -1~1(폭 2.0)이라
                    # 0~1 시절 0.1과 같은 체감 변화량을 내려면 2배가 필요하다.
REVERSAL_BOOST = 1.6   # 클라이맥스 반전 목표 증폭. 글쓰기+사후추출을 거치면
                        # 목표가 실측상 절반 정도로 희석돼서, 미리 더 세게 잡는다.

# 이전 글을 프롬프트에 얼마나 넘길지. COHERENCE와 분리돼 있다.
# 0.0=안 넘김 / 0.5=직전 장면 마지막 문단만 / 1.0=이전 모든 장면 전문
CONTEXT_LEVEL = 1.0

# 이전 장면에서 이미 쓴 재료가 다시 뽑힐 때 곱해지는 가중치
REPEAT_PENALTY = 0.1

# 기승전결 중 "전"(클라이맥스)에 해당하는 장면 번호. 1팀 블루프린트를
# 쓰면 scene1=기이므로 scene3=전이 된다. 이 장면만 반전 drift를 쓴다.
CLIMAX_SCENE = 3

# 장면 벡터 계산 시 카테고리 가중치
VECTOR_WEIGHTS = {"배경": 0.2, "오브제": 0.5, "감정": 0.3}

# ── 글 품질 검사 기준 ─────────────────────────────────
MIN_CHARS    = 500
MAX_CHARS    = 650
TARGET_CHARS = 580   # 범위 중앙(575) 근처. 550이면 모델이 하한 아래로 내려간다.
MAX_TRIES    = 3
BANNED       = ["듯", "것 같", "느낌"]   # "듯"은 듯한/듯이/비틀리듯/옮긴 듯 모두 포괄
SENTENCE_ENDS = {'.', '!', '?', '…', '"', "'", '”', '’', '」'}

HUMAN_WORDS      = ["사람", "남자", "여자", "아이", "노인"]
HUMAN_WARN_RATIO = 0.4
_HUMAN_SUBJECT_RE = re.compile(
    r"^(?:(?:그녀|그)[는가의]|(?:" + "|".join(HUMAN_WORDS) + r")[은는이가의])"
)

# ── 4D 벡터 축 설명 (Hourglass of Emotions, Cambria 2012) ────────────────
VECTOR_AXES = """4개 축의 의미 (Hourglass of Emotions 기반, 각 값 -1.0 ~ +1.0):
- Pleasantness (쾌적감) : -1(불쾌·혐오·공포) ~ 0(중립) ~ +1(기쁨·편안·아름다움)
- Attention    (주의감) : -1(무관심·졸음·멍함) ~ 0(중립) ~ +1(각성·호기심·긴장)
- Sensitivity  (민감감) : -1(둔감·무감각·익숙함) ~ 0(중립) ~ +1(예민·날카로움·낯섦)
- Aptitude     (적합감) : -1(무력감·실패·좌절) ~ 0(중립) ~ +1(자신감·유능함·성취)

평가 지침:
- 값이 명확히 판단되지 않으면 null을 출력한다.
- 평가상태: "정상" (판단 근거 있음) 또는 "미확정" (근거 불충분, 벡터 null)
- 근거문장: 글에서 실제로 사용한 문장 또는 구절 (없으면 빈 문자열)
- 판단근거: 왜 그 값인지 한 줄 설명"""


# ════════════════════════════════════════════════
# 프롬프트
# ════════════════════════════════════════════════

# 한 주인공의 목표, 행동, 결과를 누적하여 네 장면을 하나의 이야기로 구성한다.
ROLE_PROMPTS = {
    1: """[기 — 주인공의 목표와 사건의 시작]
한 명의 주인공을 정하고, 그 사람이 지금 처한 상황과 이루려는 구체적인 목표를 세운다.
첫 행동에서 목표나 필요가 드러나게 한다. 배경과 오브제는 행동의 대상이나 조건이 된다.
주인공이 왜 그 목표에 매달리는지, 무엇을 바라거나 잃을까 두려워하는지 쉬운 말로 드러낸다.
주인공이 목표를 향해 움직이다 예상 밖의 장애물이나 사건을 만난다.
장면 안에서 주인공이 대응을 선택하고 실행하며, 그 결과가 다음 장면의 문제를 만든다.
핵심 사물이나 관계에 작은 단서를 심어 이후 반전의 근거로 남긴다.
마지막에는 주인공의 위치, 행동의 결과, 다음에 해야 할 일이 구체적으로 드러나게 한다.

""",
    2: """[승 — 이전 행동의 결과와 갈등의 심화]
앞선 이야기의 같은 주인공을 따라간다. 직전 행동의 결과가 이번 상황의 원인이 된다.
주인공은 이미 세운 목표를 위해 구체적인 시도를 하고, 장애물의 반응 때문에 방법을 바꾼다.
그 시도는 단서나 성과를 얻는 동시에 더 큰 대가, 위험, 갈등을 불러온다.
이전 장면의 단서를 행동 속에서 발전시키고, 전에서 뒤집힐 상황에 설득력 있는 근거를 쌓는다.
마지막에는 주인공이 피할 수 없는 선택이나 결정적인 행동의 문턱에 도달하게 한다.
감정은 겪은 사건에 따라 변하고 그 변화가 다음 행동을 바꾸게 한다.
시도가 어긋나는 순간의 속상함이나 두려움, 그래도 계속하려는 마음을 독자가 바로 이해하게 쓴다.

""",
    3: """[전 — 행동으로 드러나는 반전과 결정적 선택]
기와 승 전체를 읽고, 이미 등장한 단서와 주인공의 행동이 맞물리는 절정을 만든다.
주인공의 시도나 선택 때문에 숨겨진 사실 또는 사물과 인물 사이의 진짜 관계가 드러난다.
그 사건은 앞선 이야기의 해석을 크게 바꾼다. 보호라고 믿은 것이 구속이거나,
방해라고 여긴 행동이 구조였다는 식으로 기존 단서에서 재료에 맞는 반전을 구성한다.
장면 중간에 반전이 드러나고, 주인공은 달라진 상황을 이해하여 행동의 방향을 바꾼다.
감정의 급격한 전환은 새로 드러난 사실과 그 인물이 치르는 대가에서 비롯되게 한다.
직전 장면 전체의 메인 감정이 속한 그룹을 기준으로 반전 후의 중심 감정을 정한다.
이번 입력이 이전과 같은 그룹이면 그 감정으로 시작하고, 반전 사건을 통해 다른 그룹의 감정으로 크게 이동한다.
입력 감정이 둘 이상이면 이전 그룹과 다른 그룹의 감정을 반전 후 중심으로 우선 활용한다.
이미 다른 그룹의 입력을 받았다면 이전 감정에서 그 입력 감정으로 넘어가는 사건을 구성하고, 전환된 감정이 후반을 지배하게 한다.
후반 중심 감정은 A군 기쁨, B군 혐오·공포·분노·슬픔, C군 놀람 중 이전 그룹 바깥에서 고른다.
반전 이후의 선택, 속마음, 행동의 결과에 새 감정을 반복해서 연결하여 이번 장면 전체의 메인 감정으로 자리 잡게 한다.
장면 전반의 이전 감정에서 출발하여 반전의 사건을 거쳐 후반과 마지막 문단에 새로운 감정이 충분히 자리 잡게 한다.
반전 직후에는 주인공이 받은 충격과 그 사실이 개인적으로 어떤 의미인지 충분히 담고 다음 선택으로 이어간다.
마지막에는 주인공이 결말의 결과를 결정할 행동을 실제로 실행한다.

""",
    4: """[결 — 선택의 결과와 하나의 이야기의 완결]
전에서 실행한 행동의 결과를 이어서 보여 준다.
직전 대표 감정과 다른 그룹의 감정이 이번 장면 전체를 이끌도록, 결과를 받아들이는 마음의 방향을 바꾼다.
전이 기쁨이면 재회의 기쁨을 짧게 이어받은 뒤 잃어버린 시간에 대한 슬픔이나 새로 밝혀진 진실에 대한 놀람으로 이동하는 등 기존 사건에서 전환의 이유를 찾는다.
전이 부정적인 감정이면 해결의 기쁨이나 예상 밖의 결과에 대한 놀람으로, 전이 놀람이면 사실을 받아들이는 기쁨 또는 상실의 슬픔 등으로 발전시킨다.
초반에 이전 감정을 연결하고 중반부터 새 감정이 선택과 행동, 마지막 여운을 이끌게 한다. 안도에서 희망으로의 변화는 모두 기쁨이므로 같은 그룹의 연장임을 구별한다.
기에서 시작한 목표와 핵심 갈등이 어떤 결과에 이르렀는지 분명하게 드러낸다.
주인공이 얻거나 잃은 것과 달라진 관계를 구체적인 상황, 행동, 감정으로 묘사한다.
앞선 핵심 사물이나 행동을 달라진 의미로 다시 활용하여 시작과 끝이 연결되게 한다.
주인공의 마지막 행동으로 사건을 마무리하고, 그 결과를 받아들이는 감정적 여운을 남긴다.
일이 끝난 뒤에도 남아 있는 마음과 처음에 비해 달라진 마음을 주인공의 눈높이에서 들려준다.
이번 장면에서 네 장면으로 이루어진 하나의 스토리를 완결한다.

""",
}

SCENE_PROMPT = """
{이전_장면_컨텍스트}{이전_장면_제약}{역할_지시}
당신은 한 명의 주인공을 따라가는 영화적 단편 이야기를 쓴다.
총 네 장면 중 {장면번호}번째 장면의 본문을 한국어로 작성한다.
네 장면은 기·승·전·결을 이루는 하나의 연속된 스토리다.
독자가 한 번 읽으며 사건을 따라가고 주인공의 마음에 공감할 수 있는 쉽고 자연스러운 이야기를 쓴다.

[이번 장면에 활용할 재료]
- 배경: {배경}
- 오브제: {오브제}
- 감정: {감정}

[이야기 구성]
1. 인물과 맥락
기에서 한 명의 주인공을 세우고 결까지 같은 인물을 중심으로 쓴다.
이름이나 호칭, 외형, 목표, 알고 있는 사실, 소지품, 부상, 인물 관계를 앞선 이야기와 일치시킨다.
주변 인물은 주인공의 행동과 갈등에 필요한 만큼 등장시킨다.
이전 이야기 전체에서 해결된 사건, 남은 문제, 단서를 읽고 그 이후의 사건을 전개한다.
이번 장면만의 사건을 쓰되, 직전 장면에서 벌어진 일의 결과로 출발한다.
시간이나 장소가 바뀌면 주인공이 왜, 어떻게 그곳에 도달했는지 자연스럽게 연결한다.

2. 행동과 인과관계
각 장면은 '바라는 것 → 행동 → 예상 밖의 결과 → 마음의 반응 → 다음 선택'으로 자연스럽게 이어진다.
주인공이 무엇을 하려 하고, 무엇 때문에 어려워지며, 어떻게 대응하는지 독자가 이해할 수 있게 쓴다.
주요 행동에는 대상과 이유가 있고, 행동 뒤에는 상황이나 관계의 변화가 따른다.
주요 사건 사이에는 인물이 그 일을 어떻게 받아들이는지 머무는 짧은 순간을 둔다.
장면마다 핵심 사건 하나에 집중하고, 그 사건이 주인공에게 갖는 의미와 마음의 변화에 충분한 분량을 쓴다.
첫 문장은 이번 상황에 맞는 주인공의 구체적인 행동으로 시작한다.

3. 상황과 감정
주인공을 가까이 따라가는 3인칭 시점으로 행동, 상황, 감정을 함께 묘사한다.
주인공이 바라는 것, 걱정하는 것, 서운한 이유와 말하지 못한 마음을 서술자가 가까이서 들려준다.
감정은 '두렵다', '서운하다', '안도한다'처럼 직접 표현하고, 그렇게 느끼는 개인적인 이유를 함께 쓴다.
표정, 몸짓, 호흡과 함께 속마음을 담아 독자가 감정을 바로 이해할 수 있게 한다.
예를 들어 '문고리를 세 번 돌린다'에 '밖에서 기다릴 동생을 생각하자, 혼자 남게 될까 두렵다'처럼
행동의 대상과 맥락에 맞는 마음을 결합한다. 구체적인 표현은 이번 인물과 사건에서 찾는다.
감정이 크게 바뀌는 대목에서는 그 마음을 한두 문장으로 충분히 들려준 뒤 다음 행동으로 이어간다.
'사건을 겪음 → 감정이 바뀜 → 다음 행동을 선택함'의 흐름을 만든다.
장면의 중심 감정은 다음 세 그룹 안에서 구체적으로 정한다.
- A군: 기쁨
- B군: 혐오, 공포, 분노, 슬픔
- C군: 놀람
중립 대신 인물이 무엇을 바라거나 두려워하고, 얻거나 잃는지 드러나는 선명한 감정을 중심에 둔다.
차분한 장면도 기쁨의 안도나 슬픔의 여운처럼 세 그룹 중 하나에 속하는 마음으로 구체화한다.
첫 장면은 입력과 상황에 맞는 A·B·C 감정 하나를 중심으로 세운다.
두 번째 장면부터는 직전 본문 전체에서 메인 감정과 그 그룹을 먼저 파악한다.
그룹 전환의 기준은 이번 입력 자체가 아니라 직전 장면의 메인 감정이 속한 그룹이다.
직전 마지막 문장의 일시적인 반응보다 장면 전반을 지배하는 마음을 기준으로 삼는다.
이번 입력이 이전 메인 감정과 같은 그룹이면 그 입력 감정으로 자연스럽게 시작한다.
그 뒤 사건, 발견, 선택을 통해 다른 그룹의 감정으로 이동하여 이번 장면의 메인 감정으로 정착시킨다.
- 직전 A군 → 이번 메인은 B군 또는 C군
- 직전 B군 → 이번 메인은 A군 또는 C군
- 직전 C군 → 이번 메인은 A군 또는 B군
예를 들어 직전이 공포이고 이번 입력이 분노여도 모두 B군이다. 분노로 시작하여 기쁨이나 놀람이 중심이 되는 사건을 만든다.
이번 입력이 이미 이전과 다른 그룹이면 그 감정을 새로운 중심으로 활용하고, 이전 마음에서 변화하는 이유를 보여 준다.
예를 들어 직전이 공포이고 이번 입력이 기쁨이면, 공포를 이어받아 기쁨으로 넘어가며 기쁨을 충분히 펼친다.
입력이 여러 개면 이전과 같은 그룹의 감정은 시작이나 갈등에, 다른 그룹의 감정은 전환 후 중심에 우선 배치한다.
입력이 하나이거나 모두 이전과 같은 그룹이면 사건의 결과로 다른 그룹의 감정을 새롭게 도출한다.
중립 입력은 잠시 감정을 누르는 상태로 해석하고, 사건의 개인적인 의미를 통해 A·B·C 중 하나로 구체화한다.
이전 이야기가 중립적으로 읽히면 인물의 목표와 행동에서 가장 뚜렷한 A·B·C 감정을 출발 기준으로 찾는다.
전환 후 감정을 중반 이후의 속마음, 행동, 마지막 결과에 일관되게 반영하여 장면 전체의 대표 정서가 되게 한다.
전에서는 앞선 단서와 반전 사건을 맞물려 그룹 간 대비를 가장 크게 만든다.
결에서도 이전과 다른 그룹의 감정으로 결과를 받아들이며 핵심 사건을 마무리한다.
감정 방향 안내는 참고로 활용하고, 직전 그룹과 다른 그룹으로 도달하는 서사 및 장면 역할을 우선한다.
감정 선택 과정은 본문 속 사건과 마음의 변화로 표현한다.
놀람은 인물의 예상과 이해가 뒤집히는 마음으로, 공포는 위협을 피하려는 마음으로 구별한다.
슬픔은 상실을 아파하는 마음, 분노는 부당함에 맞서는 마음, 혐오는 대상을 밀어내는 마음,
기쁨은 소중한 것을 얻거나 지켜서 안도하는 마음으로 구체화한다.
짧은 속말이나 자연스러운 대화로 인물의 바람, 망설임, 애착을 드러낸다.

4. 재료와 세계
배경은 주인공이 행동하는 무대, 오브제는 목표·도구·장애물·단서로 활용한다.
이번 배경 중 주요 공간 하나, 오브제 중 중심 사물 하나를 정하여 장면의 시각적 중심으로 삼는다.
첫 문단의 행동 속에서 주요 공간의 이름, 주인공의 위치, 눈에 띄는 구조나 빛을 짧고 명확하게 보여 준다.
중심 사물은 이름과 색·재질·형태 중 두 가지를 구체화하고 주인공이 직접 만지거나 사용하거나 지키려 하게 한다.
장면의 중요한 선택과 결과가 그 공간의 특성 및 중심 사물의 용도나 상태 변화에 연결되게 한다.
후반에도 중심 사물을 다시 등장시켜 달라진 상태나 주인공에게 갖는 의미를 보여 준다.
이번 재료는 이야기의 맥락에 맞는 비중으로 모두 반영한다.
이미 등장한 장소와 사물은 인물의 동선과 사건에 따라 이어서 활용할 수 있다.
새 재료는 주인공의 이동, 발견, 접촉을 통해 기존 이야기로 연결한다.
초현실적인 설정이 어울리면 앞서 정한 세계의 작동 방식과 사건의 인과를 유지하며 활용한다.
인물의 동선과 사물의 상태는 상황을 이해하는 데 필요한 만큼 간결하게 쓴다.
묘사의 초점은 주인공이 마음을 쓰는 대상과 그 대상이 주인공에게 갖는 의미에 둔다.
빛, 소리, 온도, 촉감은 인물이 마주한 상황과 감정에 맞춰 선택한다.

5. 기승전결과 마무리
기는 목표와 사건을 시작하고, 승은 행동의 대가로 갈등을 키운다.
전은 앞선 단서가 맞물리는 반전과 결정적 선택을, 결은 그 선택의 결과와 갈등의 마무리를 보여 준다.
기·승·전의 마지막 행동과 결과가 다음 장면을 필요하게 만든다.
결에서는 처음 시작한 사건의 결과를 보여 주고 주인공의 마지막 행동으로 이야기를 완결한다.

6. 문체와 출력
현재형을 중심으로 읽기 쉬운 소설 문장으로 쓴다.
일상적인 어휘와 명확한 문장을 쓰고, 누가 무엇을 하며 왜 마음이 움직이는지 바로 읽히게 한다.
한 문장에는 하나의 중심 내용을 담고, 짧은 행동 문장과 자연스럽게 이어지는 감정 문장을 섞는다.
낯선 설정이나 반전은 주인공이 보고 이해하는 순서로 풀어 설명한다.
관찰과 판단은 구체적으로 진술한다. '듯', '것 같', '느낌'에 기대는 표현은 명확한 상태와 행동으로 바꾼다.
문단 수와 문장 길이는 행동, 대화, 감정의 흐름에 맞춰 조절한다.
공백 제외 {최소글자수}~{최대글자수}자, 목표 {목표글자수}자 안팎으로 작성한다.
출력은 이번 장면의 이야기 본문만으로 구성하고, 마지막 문장까지 완결한다.

[작성 전 확인]
이전 이야기에서 주인공의 현재 상태와 남은 목표를 확인한다.
이번 사건이 주인공에게 왜 중요하고, 사건 전후 마음이 어떻게 달라지는지 정한다.
그 마음의 변화가 다음 행동으로 이어지도록 본문으로 구현한다.
현재 장면의 역할에 맞춰 사건과 감정이 변화하는 하나의 연속된 장면을 쓴다.
"""


# ════════════════════════════════════════════════
# 순수 파이썬 수학 헬퍼 (numpy 없음)
# ════════════════════════════════════════════════

def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))

def _norm(v):
    return math.sqrt(sum(x * x for x in v))

def cosine_similarity(a, b):
    n = _norm(a) * _norm(b)
    return _dot(a, b) / n if n > 1e-8 else 0.0

def softmax_weights(scores, temperature):
    t = max(temperature, 1e-6)
    scaled = [s / t for s in scores]
    m = max(scaled)
    exps = [math.exp(s - m) for s in scaled]
    total = sum(exps)
    return [e / total for e in exps]

def random_unit_vector(dim=4):
    v = [random.gauss(0, 1) for _ in range(dim)]
    n = _norm(v)
    return [x / n for x in v] if n > 1e-8 else [1.0] + [0.0] * (dim - 1)

def clip_vector(v, lo=-1.0, hi=1.0):
    """Hourglass 범위 -1.0 ~ +1.0으로 클리핑"""
    return [max(lo, min(hi, x)) for x in v]

def weighted_mean_vectors(vectors, weights):
    dim = len(vectors[0])
    total_w = sum(weights)
    result = [0.0] * dim
    for v, w in zip(vectors, weights):
        for i in range(dim):
            result[i] += v[i] * w / total_w
    return result


# ════════════════════════════════════════════════
# 1팀 연동 헬퍼
# ════════════════════════════════════════════════

def load_blueprint_scene1(blueprint_path: str = "team1/output/assembled_blueprint.json") -> dict | None:
    """1팀 assembled_blueprint.json 첫 장면(기) 재료 로드.
    파일이 없거나 파싱 실패 시 None 반환 → 호출자가 폴백 처리.
    반환값: {"배경": [...str], "오브제": [...str], "감정": [...str]}
    """
    p = Path(blueprint_path)
    if not p.exists():
        print(f"  [blueprint] 파일 없음: {blueprint_path} → 폴백")
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        # assembled_blueprint는 {"scenes": [...]} 또는 리스트 형식 모두 허용
        scenes = data.get("scenes", data) if isinstance(data, dict) else data
        if not scenes:
            print("  [blueprint] 장면 데이터 없음 → 폴백")
            return None
        s = scenes[0]

        def names(value, place_key=None, extra_key=None):
            """문자열 / dict / 리스트가 섞여 오는 1팀 필드에서 이름만 꺼낸다.

            dict 항목의 이름은 '키워드'에 있다. '새_표현'은 새로 생성된 표현인지를
            뜻하는 boolean 플래그이므로 이름으로 쓰면 True가 섞여 들어온다.
            """
            if value is None:
                return []
            if isinstance(value, str):
                return [value.strip()] if value.strip() else []
            if isinstance(value, dict):
                # scene_handoff 형식: {"장소": ..., "분위기_상태": [...]}
                if place_key and place_key in value:
                    return names(value.get(place_key)) + names(value.get(extra_key))
                for k in ("키워드", "이름", "항목"):
                    v = value.get(k)
                    if isinstance(v, str) and v.strip():
                        return [v.strip()]
                return []
            if isinstance(value, list):
                out = []
                for item in value:
                    out += names(item)
                return out
            return []

        # 배경: 장소 + 분위기 상태
        bg_list = names(s.get("배경"), place_key="장소", extra_key="분위기_상태")
        bg_list += names(s.get("상태"))

        # 오브제: 주체(엔티티·사물) + 사운드
        obj_list = names(s.get("주체")) + names(s.get("엔티티_오브제")) + names(s.get("사운드"))

        # 감정
        emo_list = []
        for e in names(s.get("감정")):
            emo_list += [x.strip() for x in re.split(r"[,、]", e) if x.strip()]

        bg_list = list(dict.fromkeys(b for b in bg_list if b))
        obj_list = list(dict.fromkeys(o for o in obj_list if o))
        emo_list = list(dict.fromkeys(emo_list))

        if not bg_list and not obj_list and not emo_list:
            print("  [blueprint] 재료 추출 실패 → 폴백")
            return None

        print(f"  [blueprint] 로드 성공: 배경 {len(bg_list)}개, 오브제 {len(obj_list)}개, 감정 {len(emo_list)}개")
        return {"배경": bg_list, "오브제": obj_list, "감정": emo_list}
    except Exception as e:
        print(f"  [blueprint] 로드 오류: {e} → 폴백")
        return None


def extract_empathy_ratio(peaks_path: str = "team1/output/emotion_peaks.txt") -> float:
    """emotion_peaks.txt에서 공감 비율(%) 평균 추출.
    형식 예: "감정 : 슬픔  (1/1명, 100.0%)"
    파일 없거나 파싱 실패 시 기본값 50.0 반환.
    """
    p = Path(peaks_path)
    if not p.exists():
        print(f"  [공감률] 파일 없음: {peaks_path} → 기본값 50.0 사용")
        return 50.0
    text = p.read_text(encoding="utf-8")
    ratios = [float(m) for m in re.findall(r"\([\d]+/[\d]+명,\s*([\d.]+)%\)", text)]
    if not ratios:
        print("  [공감률] 수치 파싱 실패 → 기본값 50.0 사용")
        return 50.0
    avg = sum(ratios) / len(ratios)
    print(f"  [공감률] {len(ratios)}개 구간 평균: {avg:.1f}%")
    return avg


def calc_material_counts(P: float) -> tuple:
    """공감 비율 P(0~100) → (n_bg, n_obj, n_emo).
    q = max(0, min(1, (P-50)*2/100))
    N_c = L_c + Binomial(U_c - L_c, q)
    """
    q = max(0.0, min(1.0, (P - 50.0) * 2.0 / 100.0))

    def binom_sample(lo, hi):
        trials = hi - lo
        if trials <= 0:
            return lo
        successes = sum(1 for _ in range(trials) if random.random() < q)
        return lo + successes

    n_bg  = binom_sample(*BG_RANGE)
    n_obj = binom_sample(*OBJ_RANGE)
    n_emo = binom_sample(*EMO_RANGE)
    print(f"  [재료 개수] q={q:.3f}  배경={n_bg}  오브제={n_obj}  감정={n_emo}")
    return n_bg, n_obj, n_emo


# ════════════════════════════════════════════════
# Claude API 호출
# ════════════════════════════════════════════════

def extract_elements(client, scene_desc: str, sound: str) -> dict:
    """타임테이블 장면 → 배경/오브제 추출 (장면 공통 후보, 벡터 없음)"""
    prompt = f"""아래 장면 설명과 사운드 특성에서 배경과 오브제를 추출해라.

장면 설명: {scene_desc}
사운드 특성: {sound}

[정의]
- 배경: 공간, 장소, 날씨, 시간대, 분위기적 환경
- 오브제: 구체적인 사물이나 요소

[출력 형식 — JSON만 출력]
{{
  "배경": ["항목1", "항목2"],
  "오브제": ["항목1", "항목2"]
}}"""
    message = client.messages.create(
        model=MODEL_EXTRACT, max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = next((b.text for b in message.content if hasattr(b, "text")), "").strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise ValueError(f"JSON 파싱 실패:\n{raw}")
    return json.loads(m.group())


def extract_peaks_pool(client, scenes: list) -> dict:
    """타임테이블 전체 → 배경/오브제/감정 후보 풀 (최초 한 번 추출하여 재사용)."""
    all_bg, all_obj, all_emo = [], [], []
    print(f"[추출] {len(scenes)}개 타임테이블에서 요소 추출 중...")
    for scene in scenes:
        elements = extract_elements(client, scene["설명"], scene["사운드"])
        all_bg.extend(elements.get("배경",  []))
        all_obj.extend(elements.get("오브제", []))
        all_emo.extend([
            e.strip()
            for e in scene["감정"].replace("(", ",").replace(")", ",").split(",")
            if e.strip()
        ])
    return {
        "배경":   list(dict.fromkeys(all_bg)),
        "오브제": list(dict.fromkeys(all_obj)),
        "감정":   list(dict.fromkeys(all_emo)),
    }


def extract_from_story(client, story: str, max_tries: int = 3) -> dict:
    """완성된 글 → 배경/오브제/감정 + 각 요소의 Hourglass 4D 벡터"""
    prompt = f"""아래 글에서 배경, 오브제, 감정, 물리법칙을 추출하고 각 항목의 분위기를 Hourglass of Emotions 4D 벡터로 점수화해라.

글:
{story}

{VECTOR_AXES}

[대표 요소와 감정 평가]
- main_emotion은 요소 벡터의 평균과 별개로, 이야기 본문에서 주인공의 대표 감정을 직접 판정한다.
- label은 기쁨, 혐오, 공포, 분노, 슬픔, 놀람 중 하나를 선택한다. 차분한 안도와 감사, 희망도 맥락에 따라 기쁨으로 판정한다.
- 핵심 사건의 개인적 의미, 중반 이후 지속되는 마음, 마지막 선택을 함께 근거로 삼는다. 마지막 한 문장이나 순간적인 충격만으로 정하지 않는다.
- 반전이 있어도 그 뒤 안도와 재회의 희망이 충분히 전개되면 기쁨이 중심이다. 눈물도 상실의 슬픔인지 안도와 기쁨의 눈물인지 맥락으로 구별한다.
- 놀람은 예상이 뒤집힌 반응 자체가 장면의 마음과 행동을 지배할 때 선택한다. 서로 다른 감정이 섞였다는 이유만으로 놀람을 선택하지 않는다.
- intensity는 확신도가 아니라 대표 감정의 강도를 0.0~1.0으로 평가한다.
- main_emotion_evidence에는 판정의 근거가 되는 본문의 실제 구절 하나를 그대로, main_emotion_reason에는 그 감정이 중심인 이유를 쓴다.
- 입력 후보나 원하는 그룹 전환보다 실제 완성된 본문에 근거하여 판정한다.
- main_background: 주인공이 핵심 사건을 겪는 주요 배경 하나를 배경 배열의 항목 이름과 정확히 일치하게 선택한다.
- main_object: 사건의 핵심이면서 한 장의 그림에서 독립된 형태로 식별할 수 있는 물리적인 사물 하나를 오브제 배열의 항목 이름과 정확히 일치하게 선택한다.
- 후보들을 사건에서의 중요성, 시각적으로 구별되는 형태, 주인공과의 직접적인 상호작용 순으로 비교한다. 등장 횟수보다 선택과 결과를 바꾸는 사물을 우선한다.
- 인물이나 신체 부위, 장소, 감정, 추상적인 현상은 각각 인물·배경·감정 묘사로 다루고 주요 오브제는 캡슐, 레버, 계기판, 케이블 같은 사물에서 고른다.
- 서로 독립된 사물은 별도 항목으로 추출한다. '패널과 전선'처럼 묶기보다 실제 행동의 대상이 된 하나를 고른다. 하나의 조립된 사물은 고유한 이름으로 부른다.
- 이름은 본문에 나타난 구체적인 종류와 색·형태 등 식별 특징을 간결하게 담는다. 본문에 없는 외형을 추가하지 않는다.
- main_object_evidence는 해당 사물에 대한 행동이나 상태가 드러나는 본문의 실제 구절, main_object_reason은 시각적 중심으로 선택한 이유다. 적합한 사물이 없으면 main_object는 null, 근거는 빈 문자열로 둔다.
- 등장 횟수뿐 아니라 사건에서의 역할을 기준으로 고르고, 해당 요소가 없으면 null을 쓴다.
- 각 배열은 이야기에서 중요한 항목부터 정렬한다.
- 벡터는 실제 본문에서 각 요소가 갖는 정서적 의미로 평가한다. 배경과 오브제도 주인공에게 위협인지, 상실의 대상인지, 희망이나 안도의 근거인지 구별한다.
- 높은 긴장이나 낯섦만으로 감정을 놀람으로 해석하지 않는다. 놀람은 예상 밖의 일을 마주하는 반응이며, 공포·슬픔·기쁨 등 지속되는 감정과 구별한다.
- 감정 배열에는 주인공의 중심 감정을 먼저 두고, 짧은 반응과 오래 지속되는 마음을 판단근거에 구별해서 설명한다.
- 공간의 차가움이나 사물의 기계적인 재질 자체와, 본문에서 그 요소가 지닌 감정적 의미를 구별한다. 판단은 실제 근거문장에 따른다.

[물리법칙 정의]
- 이 글에서 현실과 어긋난 꿈의 논리를 짧게 서술 (예: "거리가 걸어도 좁혀지지 않음", "물체가 위로 떨어짐")
- 없으면 빈 배열

[출력 형식 — JSON만 출력, 주석 없이 순수 JSON]
{{
  "main_emotion": {{"label": "기쁨", "intensity": 0.8}},
  "main_emotion_evidence": "본문에서 그대로 가져온 근거 구절",
  "main_emotion_reason": "핵심 사건과 지속되는 마음을 근거로 한 판정 이유",
  "main_background": "배경 배열에서 선택한 항목 이름 또는 null",
  "main_object": "오브제 배열에서 선택한 항목 이름 또는 null",
  "main_object_evidence": "해당 사물과 행동을 보여 주는 본문의 실제 구절",
  "main_object_reason": "사건에서의 역할과 시각적 식별성을 근거로 한 이유",
  "배경": [{{
    "항목": "...",
    "벡터": [Pleasantness, Attention, Sensitivity, Aptitude],
    "근거문장": "글에서 가져온 실제 구절",
    "평가상태": "정상",
    "판단근거": "왜 이 값인지 한 줄"
  }}, ...],
  "오브제": [{{
    "항목": "...",
    "벡터": [Pleasantness, Attention, Sensitivity, Aptitude],
    "근거문장": "...",
    "평가상태": "정상",
    "판단근거": "..."
  }}, ...],
  "감정": [{{
    "항목": "...",
    "벡터": [Pleasantness, Attention, Sensitivity, Aptitude],
    "근거문장": "...",
    "평가상태": "정상",
    "판단근거": "..."
  }}, ...],
  "물리법칙": ["법칙1", ...]
}}

모든 벡터 값은 -1.0~+1.0 사이의 소수로. 판단 근거가 불충분하면 벡터를 null로 출력하고 평가상태를 "미확정"으로 표기. 문자열 안에 쌍따옴표를 쓰지 않는다."""
    for attempt in range(1, max_tries + 1):
        message = client.messages.create(
            model=MODEL_STORY, max_tokens=6144,
            messages=[{"role": "user", "content": prompt}],
        )
        if message.stop_reason == "max_tokens":
            print(f"  [추출 재시도 {attempt}/{max_tries}] max_tokens 초과로 JSON이 잘렸습니다.")
            continue
        raw = next((b.text for b in message.content if hasattr(b, "text")), "").strip()
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            print(f"  [추출 재시도 {attempt}/{max_tries}] JSON 없음")
            continue
        try:
            elements = json.loads(m.group())
            elements["main_emotion"] = validate_story_emotion(elements, story)
            validate_visual_object(elements, story)
            elements["main_background"] = select_main_element(elements, "배경", "main_background")
            elements["main_object"] = select_main_element(elements, "오브제", "main_object")
            return elements
        except (ValueError, TypeError, AttributeError) as e:
            print(f"  [추출 재시도 {attempt}/{max_tries}] 추출 결과 오류: {e}")

    # 실패한 판정을 벡터 라벨로 대체하지 않고 명시적으로 미판정으로 남긴다.
    print("  ※ 추출 재시도를 모두 사용했습니다. 요소는 비우고 대표 감정은 미판정으로 남깁니다.")
    return {"배경": [], "오브제": [], "감정": [], "물리법칙": [],
            "main_background": None, "main_object": None,
            "main_emotion": {"label": None, "intensity": 0.0},
            "main_object_evidence": "", "main_object_reason": "추출 재시도 실패로 미판정",
            "main_emotion_evidence": "", "main_emotion_reason": "추출 재시도 실패로 미판정"}


def validate_visual_object(elements: dict, story: str) -> None:
    """주요 오브제가 추출 항목에 속하고 실제 본문 근거를 갖는지 확인한다."""
    selected = elements.get("main_object")
    if selected is None:
        return
    names = [item.get("항목") for item in elements.get("오브제", [])]
    evidence = elements.get("main_object_evidence")
    reason = elements.get("main_object_reason")
    if selected not in names:
        raise ValueError("주요 오브제는 추출된 사물 중 하나여야 합니다.")
    if not isinstance(evidence, str) or not evidence.strip() or evidence not in story:
        raise ValueError("주요 오브제의 실제 본문 근거가 필요합니다.")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("주요 오브제의 선택 이유가 필요합니다.")


def validate_story_emotion(elements: dict, story: str) -> dict:
    """본문 기반 감정 판정의 라벨, 강도, 실제 근거를 검증한다."""
    emotion = elements.get("main_emotion")
    if not isinstance(emotion, dict) or emotion.get("label") not in {
        "기쁨", "혐오", "공포", "분노", "슬픔", "놀람"
    }:
        raise ValueError("본문 대표 감정의 라벨이 누락되었거나 유효하지 않습니다.")
    intensity = emotion.get("intensity")
    if isinstance(intensity, bool) or not isinstance(intensity, (int, float)) or not 0 <= intensity <= 1:
        raise ValueError("대표 감정 강도는 0~1의 수여야 합니다.")
    evidence = elements.get("main_emotion_evidence")
    reason = elements.get("main_emotion_reason")
    if not isinstance(evidence, str) or not evidence.strip() or evidence not in story:
        raise ValueError("대표 감정의 실제 본문 근거가 필요합니다.")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("대표 감정의 판정 이유가 필요합니다.")
    return {"label": emotion["label"], "intensity": round(float(intensity), 3)}


def select_main_element(elements: dict, category: str, field: str) -> str | None:
    """대표 요소를 추출된 항목으로 제한하고, 누락 시 중요도순 첫 항목을 쓴다."""
    if field in elements and elements[field] is None:
        return None
    names = [item["항목"] for item in elements.get(category, []) if item.get("항목")]
    selected = elements.get(field)
    return selected if selected in names else (names[0] if names else None)


# ════════════════════════════════════════════════
# Dream State Machine
# ════════════════════════════════════════════════

def _is_valid_vector(v) -> bool:
    """벡터가 유효한지 확인 (null 또는 None 포함 시 False)"""
    return v is not None and len(v) == 4 and all(x is not None for x in v)


def compute_scene_vector(elements: dict) -> list:
    """장면 요소 전체의 가중 평균 벡터 계산. null 벡터 항목은 제외.

    카테고리 안에서 먼저 평균을 낸 다음 VECTOR_WEIGHTS 비율로 합친다.
    항목별로 카테고리 가중치를 그대로 매기면(예: 오브제 1개당 0.5) 오브제가
    많이 뽑힌 장면일수록 오브제 카테고리의 실제 영향력이 의도한 비율(0.5)보다
    훨씬 커지는 문제가 있었다.
    """
    category_means, category_weights = [], []
    for category, weight in VECTOR_WEIGHTS.items():
        items = [
            [float(x) for x in item.get("벡터")]
            for item in elements.get(category, [])
            if _is_valid_vector(item.get("벡터"))
        ]
        if not items:
            continue
        mean = weighted_mean_vectors(items, [1.0] * len(items))
        category_means.append(mean)
        category_weights.append(weight)
    if not category_means:
        return [0.0, 0.0, 0.0, 0.0]
    return weighted_mean_vectors(category_means, category_weights)


# 1팀 7종 감정의 Hourglass 좌표 (Pleasantness, Attention, Sensitivity, Aptitude).
# Cambria 논문이 이 7종(1팀 자체 분류)의 정확한 좌표를 못박진 않으므로, Hourglass의
# 일반 원리로 추정한 휴리스틱이다. 숫자는 조정 가능.
EMOTION_ARCHETYPES = {
    "분노": (-0.6,  0.7,  0.5,  0.3),
    "혐오": (-0.7,  0.3,  0.6, -0.3),
    "공포": (-0.6,  0.6,  0.6, -0.6),
    "기쁨": ( 0.7,  0.3, -0.2,  0.5),
    "슬픔": (-0.5, -0.5, -0.2, -0.5),
    "놀람": ( 0.0,  0.8,  0.5,  0.0),
    "중립": ( 0.0,  0.0,  0.0,  0.0),
}
_MAX_VECTOR_NORM = _norm([1.0, 1.0, 1.0, 1.0])  # 강도 정규화 기준


def classify_emotion(vector: list) -> dict:
    """장면 벡터를 7종 감정 중 가장 가까운 것으로 분류한다.

    Claude에게 또 묻지 않고 이미 계산된 벡터로 결정한다. "중립"의 좌표가
    원점이라, 벡터가 거의 중립이면 자동으로 "중립"이 가장 가까운 점이 된다 —
    글 내용이 아무리 기이해도 벡터가 평온하면 라벨도 평온해진다.
    """
    best_label, best_dist = "중립", float("inf")
    for label, coord in EMOTION_ARCHETYPES.items():
        dist = math.sqrt(sum((v - c) ** 2 for v, c in zip(vector, coord)))
        if dist < best_dist:
            best_label, best_dist = label, dist
    intensity = min(1.0, _norm(vector) / _MAX_VECTOR_NORM)
    return {"label": best_label, "intensity": round(intensity, 3)}


def dream_drift(current_vector: list, reversal: bool = False) -> list:
    """현재 벡터에서 다음 장면 목표 벡터를 정한다.

    reversal=True (클라이맥스, "전" 장면)면 쾌적감(축0)·적합감(축3)만 부호
    반전시킨다 — 위협↔편안, 무력↔자신감처럼 "정서의 질"은 뒤집되, 주의감·
    민감감(축1·2)은 일반 drift로 둔다. 이 두 축은 "꿈의 어긋남"(규칙3, 모든
    장면에 필수)이 구조적으로 밀어올리는 낯섦·각성을 나타내서, 전부 반전시키면
    글쓰기 규칙과 목표 벡터가 서로를 깎아먹는다 — 아무리 따뜻하게 써도
    어긋난 요소가 들어가는 순간 주의감·민감감은 올라갈 수밖에 없기 때문이다.
    """
    direction = random_unit_vector(4)
    distance  = (1 - COHERENCE) * MAX_DRIFT
    target    = [c + d * distance for c, d in zip(current_vector, direction)]
    if reversal:
        # 글쓰기+사후추출을 거치면 반전 목표가 항상 어느 정도 희석된다(실측상 절반
        # 정도로 줄어듦). 목표를 미리 증폭해서(REVERSAL_BOOST) 실제 결과가
        # 의도한 반전에 더 가깝게 도착하도록 한다.
        target[0] = -current_vector[0] * REVERSAL_BOOST
        target[3] = -current_vector[3] * REVERSAL_BOOST
    return clip_vector(target)



# 목표 벡터(수치)를 글쓰기 모델에게 숫자가 아니라 말로 전달하기 위한 축별 라벨.
# 숫자를 그대로 주면 모델이 어색하게 숫자를 의식한 문장을 쓰는 경향이 있어 피한다.
_AXIS_LABELS = [
    ("쾌적감", "불쾌·혐오·공포", "편안·기쁨·아름다움"),
    ("주의감", "무관심·멍함",   "각성·긴장·호기심"),
    ("민감감", "둔감·익숙함",   "예민·낯섦"),
    ("적합감", "무력감·좌절",   "자신감·유능함"),
]


def describe_target_vector(v: list, threshold: float = 0.15, strong: float = 0.5) -> str:
    """목표 벡터를 '쾌적감은 강하게 편안한 쪽' 같은 말로 번역한다.

    크기(strong 이상)에 따라 "강하게"를 붙여, 세게 밀어야 하는 축과 살짝만
    기울면 되는 축을 모델이 구분할 수 있게 한다.
    """
    parts = []
    for (name, neg, pos), val in zip(_AXIS_LABELS, v):
        mag = abs(val)
        if val > threshold:
            parts.append(f"{name}은 {'강하게 ' if mag > strong else ''}{pos} 쪽")
        elif val < -threshold:
            parts.append(f"{name}은 {'강하게 ' if mag > strong else ''}{neg} 쪽")
        else:
            parts.append(f"{name}은 중립")
    return ", ".join(parts)


_MODIFIER_RE = re.compile(r"[은는]$")


def _tokens(name: str) -> set:
    """항목 이름에서 사물의 정체를 가리키는 2글자 이상 토큰 추출"""
    raw = {t for t in re.findall(r"[가-힣A-Za-z0-9]+", name) if len(t) >= 2}
    # '낡은', '깜빡이는', '붉은' 같은 수식어는 사물이 아니라 상태를 가리킨다.
    # 이것까지 비교하면 '낡은 스피커'와 '낡은 종이'가 같은 것으로 잡힌다.
    core = {t for t in raw if not _MODIFIER_RE.search(t)}
    return core or raw


def is_same_thing(a: str, b: str) -> bool:
    """추출될 때마다 이름이 바뀌는 같은 사물을 같다고 판정.

    장면이 넘어갈 때마다 Claude가 같은 사물을 다르게 적는다.
    '전구' → '깜빡이는 전구' → '전구(필라멘트)',  '바닥 홈' → '바닥의 홈과 쇠 끌리는 소리'
    정확히 비교하면 교집합이 늘 공집합이 되어 반복 억제가 작동하지 않는다.

    조사가 붙어 형태가 달라지는 건('바닥' ~ '바닥의') 접두 일치로 흡수하고,
    짧은 쪽 토큰의 절반 이상이 맞으면 같은 것으로 본다.
    """
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return a == b
    short, other = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    matched = sum(1 for x in short
                  if any(x.startswith(y) or y.startswith(x) for y in other))
    return matched / len(short) >= 0.5


def has_banned(name: str) -> bool:
    """재료 이름 자체에 금지표현이 있으면 글에 쓸 수 없다"""
    return any(w in name for w in BANNED)


def combine_elements(elements_list: list) -> dict:
    """여러 장면의 추출 요소를 하나로 합친다 (먼저 나온 항목을 우선, 중복은 버림).

    클라이맥스 장면에서 직전 장면 하나만 보면 후보가 전부 '방금 그 분위기'
    재료뿐이라 반전 목표와 코사인 유사도를 비교해도 다 비슷하게 낮게 나온다.
    지금까지 나온 모든 장면을 합쳐야 그중 반전 쪽에 그나마 가까운 게 섞여 들어올 여지가 생긴다.
    """
    combined = {"배경": [], "오브제": [], "감정": []}
    for elements in elements_list:
        for cat in combined:
            existing = [i["항목"] for i in combined[cat]]
            for item in elements.get(cat, []):
                if not any(is_same_thing(item["항목"], e) for e in existing):
                    combined[cat].append(item)
                    existing.append(item["항목"])
    return combined


def merge_candidates(prev_elements: dict, bg_pool: list,
                     obj_pool: list, emo_pool: list) -> dict:
    """직전 장면 추출 요소에 원본 후보 풀을 더한다.

    직전 장면 것만 쓰면 후보가 2~5개뿐이고 그게 전부 직전 장면에서 온 것이라,
    무슨 수를 써도 같은 공간을 벗어날 수 없다. 원본 풀 항목은 벡터가 없어
    코사인 유사도 0(중립)으로 취급되므로, 패널티 받은 반복 항목과 경쟁하게 된다.
    """
    def extend(items, names):
        existing = [i["항목"] for i in items]
        fresh = [{"항목": n, "벡터": None} for n in names
                 if not any(is_same_thing(n, e) for e in existing)]
        return items + fresh

    return {
        "배경":   extend(prev_elements.get("배경",  []), bg_pool),
        "오브제": extend(prev_elements.get("오브제", []), obj_pool),
        "감정":   extend(prev_elements.get("감정",  []), emo_pool),
    }


def sample_elements(elements: dict, target_vector: list,
                    n_bg: int = 1, n_obj: int = 2, n_emo: int = 2,
                    used_backgrounds: list = None,
                    used_objects: list = None,
                    used_emotions: list = None) -> tuple:
    """코사인 유사도 기반 가중치 샘플링 → (배경, 오브제, 감정) 리스트"""
    def sample_category(items, n, used=None, force_new=False):
        candidates = [i for i in items if not has_banned(i["항목"])] or items
        if not candidates:
            return []

        # null 벡터 항목은 [0.0]*4 로 대체 (코사인 유사도 0 근방)
        sims = [
            cosine_similarity(
                [float(x) for x in item.get("벡터")] if _is_valid_vector(item.get("벡터")) else [0.0]*4,
                target_vector
            )
            for item in candidates
        ]
        weights = softmax_weights(sims, TEMPERATURE)

        # 이미 쓴 재료는 이름이 변형됐어도 찾아내 가중치를 낮춘다.
        # 하드 제외를 쓰지 않는 이유: 후보 풀이 작아 전부 제외되는 경우가 생기고,
        # 그때 fallback으로 되돌아가면 억제가 통째로 무효화된다.
        if used:
            weights = [
                w * REPEAT_PENALTY
                if any(is_same_thing(item["항목"], u) for u in used) else w
                for item, w in zip(candidates, weights)
            ]
            total = sum(weights)
            if total > 1e-8:
                weights = [w / total for w in weights]

        chosen = random.choices(candidates, weights=weights, k=min(n, len(candidates)))
        seen, result = set(), []
        for item in chosen:
            name = item["항목"]
            if name not in seen:
                seen.add(name)
                result.append(name)

        # 복원 추출이라 중복이 나와 개수가 모자랄 수 있다. 부족분도 target_vector를
        # 무시한 균등 무작위(random.sample)가 아니라, 같은 가중치로 비복원 추출해 채운다 —
        # 안 그러면 코사인 점수가 가장 나쁜 재료도 1위와 똑같은 확률로 뽑힌다.
        remaining_idx = [i for i, item in enumerate(candidates) if item["항목"] not in seen]
        while len(result) < n and remaining_idx:
            sub_weights = [weights[i] for i in remaining_idx]
            pick = (random.choices(remaining_idx, weights=sub_weights, k=1)[0]
                    if sum(sub_weights) > 1e-8 else random.choice(remaining_idx))
            remaining_idx.remove(pick)
            name = candidates[pick]["항목"]
            if name not in seen:
                seen.add(name)
                result.append(name)

        # 교수님 피드백: 재료가 획기적으로 바뀌어야 한다. 패널티만으로는 재료 풀이
        # 좁을 때 전부 재사용 재료로만 채워질 수 있다. 결과 전부가 이미 쓴 것이면
        # 가중치가 가장 낮았던 하나를, 안 쓴 재료 중 가장 점수 높은 것으로 강제 교체한다.
        if force_new and used and result:
            is_new = lambda nm: not any(is_same_thing(nm, u) for u in used)
            if not any(is_new(r) for r in result):
                weight_by_name = {c["항목"]: w for c, w in zip(candidates, weights)}
                new_candidates = [c for c in candidates if is_new(c["항목"])]
                if new_candidates:
                    best_new = max(new_candidates, key=lambda c: weight_by_name.get(c["항목"], 0.0))
                    weakest = min(result, key=lambda r: weight_by_name.get(r, 0.0))
                    result[result.index(weakest)] = best_new["항목"]
        return result

    bg  = sample_category(elements.get("배경",  []), n_bg,  used=used_backgrounds, force_new=True)
    obj = sample_category(elements.get("오브제", []), n_obj, used=used_objects,     force_new=True)
    emo = sample_category(elements.get("감정",  []), n_emo, used=used_emotions,    force_new=True)
    return bg, obj, emo


def build_context(previous_stories: list) -> str:
    """CONTEXT_LEVEL에 따라 이전 이야기 컨텍스트 구성.

    기본 설정에서는 지금까지 생성한 모든 장면의 전문을 순서대로 전달한다.
    """
    if not previous_stories or CONTEXT_LEVEL <= 0:
        return ""
    last = previous_stories[-1].strip()
    if CONTEXT_LEVEL < 1.0:
        last_para = last.split("\n\n")[-1]
        return f"[직전 장면 마지막 문단]\n{last_para}\n\n"
    scenes = "\n\n".join(
        f"[장면 {i}]\n{story.strip()}"
        for i, story in enumerate(previous_stories, start=1)
    )
    return (
        f"[이전까지 생성된 이야기 — 장면 순서대로 전문]\n{scenes}\n\n"
        "위 이야기의 같은 주인공, 목표, 인물 관계와 사건의 결과를 이어받는다. "
        "직전 행동의 결과에서 이번 장면을 시작하고, "
        "이전 전체의 단서와 선택을 발전시켜 하나의 스토리로 연결한다.\n\n"
    )


def extract_opening(story: str, n_sentences: int = 2) -> str:
    """직전 장면의 시작 문장(들)을 뽑아낸다. 다음 장면이 같은 문형을 베끼지 않게
    모델에게 구체적으로 보여주는 용도."""
    sentences = re.split(r"(?<=[.!?…])\s+", story.strip())
    return " ".join(sentences[:n_sentences]).strip()


# ════════════════════════════════════════════════
# 글 검사 및 생성
# ════════════════════════════════════════════════

def count_no_space(text: str) -> int:
    return len(re.sub(r"\s", "", text))

def human_subject_ratio(story: str) -> tuple:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", story) if s.strip()]
    if not sentences:
        return 0, 0, 0.0
    human = sum(1 for s in sentences if _HUMAN_SUBJECT_RE.match(s))
    return human, len(sentences), human / len(sentences)

def check_story(story: str, truncated: bool = False) -> list:
    problems = []
    n = count_no_space(story)
    if n < MIN_CHARS:
        problems.append(f"분량이 부족하다({n}자). 공백 제외 {TARGET_CHARS}자 이상으로 쓸 것.")
    if n > MAX_CHARS:
        problems.append(f"분량이 너무 길다({n}자). 공백 제외 {TARGET_CHARS}자 안팎으로 줄일 것.")
    hits = sorted({m.group() for w in BANNED
                   for m in re.finditer(r"\S*" + re.escape(w) + r"\S*", story)})
    if hits:
        problems.append(f"금지 표현이 들어 있다: {hits}. 이 표현 없이 단정적으로 쓸 것.")
    if truncated or (story and story.rstrip()[-1] not in SENTENCE_ENDS):
        problems.append("글이 문장 중간에서 끊겼다. 마지막 문장까지 완결해서 쓸 것.")
    return problems


def story_penalty(story: str, truncated: bool = False) -> float:
    """초안끼리 우열을 가리는 벌점. 낮을수록 좋다.

    문제 '개수'로 비교하면 분량 30자 미달과 금지표현 위반이 같은 무게가 되어,
    규칙을 어긴 글이 채택될 수 있다. 위반 종류별로 무게를 다르게 둔다.
    """
    if not story.strip():
        return 1e6                                  # 빈 글은 절대 채택하지 않는다
    score = 0.0
    if truncated or story.rstrip()[-1] not in SENTENCE_ENDS:
        score += 1000.0                             # 문장이 끊긴 글은 사용 불가
    score += 500.0 * sum(story.count(w) for w in BANNED)
    n = count_no_space(story)
    if n < MIN_CHARS:
        score += MIN_CHARS - n                      # 분량은 벗어난 만큼만
    elif n > MAX_CHARS:
        score += n - MAX_CHARS
    return score


def generate_scene(client, scene_num: int,
                   backgrounds: list, objects: list, emotions: list,
                   previous_stories: list,
                   used_physics: list = None,
                   previous_backgrounds: list = None,
                   target_vector: list = None,
                   previous_main_emotion: dict = None,
                   previous_main_emotions: list = None) -> str:
    context = build_context(previous_stories)

    lines = []
    if used_physics or previous_backgrounds:
        lines.append("[이전에 확립된 세계와 공간 — 이야기의 연속성을 위한 참고]")
        if used_physics:
            lines.append(f"- 세계의 작동 방식: {', '.join(used_physics)}")
        if previous_backgrounds:
            lines.append(f"- 주인공이 거쳐 온 배경: {', '.join(previous_backgrounds)}")
        lines.append("→ 인물의 동선과 사건의 원인에 맞춰 공간과 사물을 이어서 활용한다. 새로운 장소는 이동의 이유와 과정을 연결하고, 세계의 작동 방식은 일관되게 유지한다.")

    if previous_stories:
        lines.append("[연속 장면 지시]")
        if previous_main_emotion and previous_main_emotion.get("label"):
            lines.append(
                f"직전 장면의 본문 기반 대표 감정: {previous_main_emotion['label']}. "
                "이 감정이 속한 그룹을 출발 기준으로 삼고 이번 장면은 다른 그룹의 감정이 중심이 되게 한다. "
                "이전 감정은 초반의 연결에 활용하고 새 감정이 중반 이후와 마지막 행동을 이끌게 한다."
            )
        lines.append("같은 주인공의 현재 위치, 소지품, 신체 상태, 알고 있는 사실을 이전 본문에서 확인한다. 직전 행동의 결과에 대응하는 다음 행동으로 시작한다.")

    if scene_num == 4 and previous_main_emotions:
        groups = {"기쁨": "A", "혐오": "B", "공포": "B", "분노": "B", "슬픔": "B", "놀람": "C"}
        history = [label for label in previous_main_emotions if label in groups]
        if history:
            last_group = groups[history[-1]]
            unused = [label for label in groups if label not in history]
            preferred = [label for label in unused if groups[label] != last_group]
            lines.append("[마지막 장면의 감정 다양성 — 감정 방향 안내보다 우선]")
            lines.append(f"앞선 장면의 실제 대표 감정 순서: {' → '.join(history)}")
            lines.append(f"지금까지 쓰지 않은 감정: {', '.join(unused) or '없음'}")
            lines.append(f"우선 검토할 감정: {', '.join(preferred or unused) or '맥락에 맞는 가장 적게 사용한 감정'}")
            lines.append(
                "직전과 다른 그룹이면서 아직 쓰지 않은 감정을 결말의 중심으로 우선 검토한다. "
                "후보 중 기존 단서와 인물의 선택에서 가장 자연스럽게 도출되는 감정을 정한다. "
                "이전 감정은 초반에 짧게 이어받고 중반부터 선택한 새 감정의 이유와 행동을 충분히 펼친다. "
                "사건의 해결이 곧 기쁨을 뜻하지는 않는다. 해결 과정에서 치른 대가와 잃은 것, 새로 알게 된 사실도 결말의 마음이 될 수 있다. "
                "마지막 한 문장에 감정 이름을 붙이는 대신 장면 전체의 중심 정서가 달라지게 구성한다. "
                "다양성은 우선순위이며 앞선 사실과 인물의 동기를 유지하면서 하나의 이야기를 완결한다."
            )

    prev_constraint = ("\n".join(lines) + "\n\n") if lines else ""

    role_note = ROLE_PROMPTS.get(scene_num, "")
    if target_vector:
        role_note = (
            f"[사건과 선택을 통해 향할 감정 방향]\n{describe_target_vector(target_vector)}\n"
            "이 방향은 참고이며, 직전 메인 감정과의 대비 및 장면 역할의 감정 전환 지시를 우선한다. 주인공이 겪는 사건에서 변화의 계기를 만든다.\n\n"
            + role_note
        )

    base_prompt = SCENE_PROMPT.format(
        이전_장면_컨텍스트=context,
        이전_장면_제약=prev_constraint,
        역할_지시=role_note,
        장면번호=scene_num,
        배경=", ".join(backgrounds),
        오브제=", ".join(objects),
        감정=", ".join(emotions),
        목표글자수=TARGET_CHARS,
        최소글자수=MIN_CHARS,
        최대글자수=MAX_CHARS,
    )
    prompt = base_prompt
    best_story, best_penalty = "", None

    for attempt in range(1, MAX_TRIES + 1):
        # max_tokens 초과인데 본문은 몇 십 자뿐이거나 아예 빈 경우가 있었다 —
        # 모델이 답을 쓰기 전에 내부적으로 길게 사고하면 그 분량이 먼저
        # max_tokens를 깎아먹어 정작 본문 쓸 예산이 안 남는 것으로 보인다.
        # 예산을 넉넉히 올려서 본문이 잘릴 여지를 줄인다.
        message = client.messages.create(
            model=MODEL_STORY, max_tokens=16000,
            messages=[{"role": "user", "content": prompt}],
        )
        story     = next((b.text for b in message.content if hasattr(b, "text")), "").strip()
        truncated = message.stop_reason == "max_tokens"
        if truncated:
            print("  ※ max_tokens에 걸려 글이 잘렸습니다.")

        # 텍스트 블록 없이 돌아오는 경우가 있다. 같은 프롬프트로 바로 다시 시도한다.
        if not story:
            print(f"  [재시도 {attempt}/{MAX_TRIES}] 빈 응답(텍스트 블록 없음)")
            continue

        problems = check_story(story, truncated)
        if not problems:
            return story

        print(f"  [재시도 {attempt}/{MAX_TRIES}] {problems}")
        penalty = story_penalty(story, truncated)
        if best_penalty is None or penalty < best_penalty:
            best_story, best_penalty = story, penalty

        prompt = (
            base_prompt
            + "\n\n[직전 초안]\n" + story
            + "\n\n[직전 초안의 문제점]\n" + "\n".join(f"- {p}" for p in problems)
            + "\n\n위 초안을 바탕으로 문제를 고쳐서 처음부터 끝까지 다시 써라. "
              "분량이 부족하면 주인공의 시도, 상대의 반응, 선택의 이유와 결과를 구체화한다. "
              "같은 주인공과 앞선 사건의 인과관계를 유지하여 이번 장면 본문 전체를 출력한다."
        )

    print(f"  ※ 재시도 횟수를 모두 사용했습니다. 벌점이 가장 낮은 결과를 사용합니다 (벌점 {best_penalty}).")
    return best_story


# ════════════════════════════════════════════════
# 메인
# ════════════════════════════════════════════════

def main(input_path: str = "team2/output/parsed_scenes.json",
         output_dir: str = "team2/output",
         blueprint_path: str = "team1/output/assembled_blueprint.json",
         peaks_path: str = "team1/output/emotion_peaks.txt"):

    scenes = json.loads(Path(input_path).read_text(encoding="utf-8"))
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    out    = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # ── 공감 비율 → 재료 개수 결정 ──────────────────────
    P = extract_empathy_ratio(peaks_path)
    n_bg, n_obj, n_emo = calc_material_counts(P)

    # ── 장면1 재료: 1팀 blueprint 우선, 빈 카테고리만 emotion_peaks로 보충 ──
    pool = load_blueprint_scene1(blueprint_path) or {"배경": [], "오브제": [], "감정": []}
    # 설계도가 완전해도 타임테이블 전체를 추출하여 후속 장면의 후보를 넓힌다.
    peaks_pool = extract_peaks_pool(client, scenes)

    missing = [c for c in ("배경", "오브제", "감정") if not pool.get(c)]
    if missing:
        print(f"  [폴백] blueprint에서 비어 있는 카테고리: {missing}")
        for c in missing:
            pool[c] = peaks_pool[c]

    all_bg, all_obj, all_emo = pool["배경"], pool["오브제"], pool["감정"]
    print(f"  배경 후보 {len(all_bg)}개: {all_bg}")
    print(f"  오브제 후보 {len(all_obj)}개: {all_obj}")
    print(f"  감정 후보 {len(all_emo)}개: {all_emo}")

    previous_stories = []
    previous_main_emotions = []
    current_vector   = None
    all_used_physics = []
    used_bg_names    = []   # 실제 글에 쓴 배경 — 프롬프트 금지 + 샘플링 패널티 공용
    used_obj_names   = []   # 실제 글에 쓴 오브제 — 샘플링 패널티용
    used_emo_names   = []   # 실제 글에 쓴 감정 재료 — 샘플링 패널티용

    for scene_num in range(1, 5):
        print(f"\n{'═'*50}")
        print(f"  장면 {scene_num} 생성")
        print(f"{'═'*50}")

        # ── 재료 선택 ──────────────────────────────────────
        if scene_num == 1:
            target_vector = None   # 초기 장면이라 아직 목표 방향이 없음
            bg  = random.sample(all_bg,  min(n_bg,  len(all_bg)))
            obj = random.sample(all_obj, min(n_obj, len(all_obj)))
            emo = random.sample(all_emo, min(n_emo, len(all_emo)))
        else:
            prev_elements_path = out / f"scene{scene_num-1}_elements.json"
            prev_elements = json.loads(prev_elements_path.read_text(encoding="utf-8"))
            is_climax = (scene_num == CLIMAX_SCENE)
            target_vector = dream_drift(current_vector, reversal=is_climax)

            print(f"  현재 벡터: {[round(x, 2) for x in current_vector]}")
            if is_climax:
                print(f"  ※ 클라이맥스(전) — 반전 drift 적용")
            print(f"  목표 벡터: {[round(x, 2) for x in target_vector]}")

            if is_climax:
                # 직전 장면 하나가 아니라 지금까지 나온 모든 장면의 재료를 후보로 넓힌다.
                all_prev_elements = [
                    json.loads((out / f"scene{i}_elements.json").read_text(encoding="utf-8"))
                    for i in range(1, scene_num)
                ]
                source_elements = combine_elements(all_prev_elements)
                print(f"  [클라이맥스] 장면 1~{scene_num-1} 재료를 전부 후보로 넓힘 "
                      f"(배경 {len(source_elements['배경'])} · 오브제 {len(source_elements['오브제'])} · "
                      f"감정 {len(source_elements['감정'])})")
            else:
                source_elements = prev_elements

            merged = merge_candidates(
                source_elements,
                peaks_pool["배경"], peaks_pool["오브제"], peaks_pool["감정"],
            )

            bg, obj, emo = sample_elements(
                merged, target_vector,
                n_bg=n_bg, n_obj=n_obj, n_emo=n_emo,
                used_backgrounds=used_bg_names or None,
                used_objects=used_obj_names or None,
                used_emotions=used_emo_names or None,
            )

        print(f"  배경: {bg}")
        print(f"  오브제: {obj}")
        print(f"  감정: {emo}")

        # ── 글 생성 ────────────────────────────────────────
        print(f"\n[생성] 장면{scene_num} 글 작성 중...")
        story = generate_scene(
            client, scene_num, bg, obj, emo, previous_stories,
            used_physics=all_used_physics or None,
            previous_backgrounds=used_bg_names or None,
            target_vector=target_vector,
            previous_main_emotion=prev_elements.get("main_emotion") if scene_num > 1 else None,
            previous_main_emotions=previous_main_emotions,
        )

        # ── 저장 ───────────────────────────────────────────
        story_path = out / f"scene{scene_num}_story.txt"
        story_path.write_text(story, encoding="utf-8")

        n = count_no_space(story)
        print(f"\n  저장 → {story_path} (공백 제외 {n}자)")

        h, total, ratio = human_subject_ratio(story)
        print(f"  [참고] 사람이 주어인 문장: {h}/{total} ({ratio:.0%})")
        if ratio > HUMAN_WARN_RATIO:
            print("  [참고] 인물 중심 서술 비중이 높습니다. 현재 이야기 구성 방향에 부합합니다.")

        print(f"\n{'─'*40}")
        print(story)
        print(f"{'─'*40}")

        # ── elements + 벡터 추출 ───────────────────────────
        print(f"\n[벡터 추출] 장면{scene_num} 요소 분석 중...")
        elements = extract_from_story(client, story)
        elements_path = out / f"scene{scene_num}_elements.json"
        elements_path.write_text(json.dumps(elements, ensure_ascii=False, indent=2), encoding="utf-8")

        for cat in ("배경", "오브제", "감정"):
            items = elements.get(cat, [])
            print(f"  {cat}: {[i['항목'] for i in items]}")

        physics = elements.get("물리법칙", [])
        if physics:
            print(f"  물리법칙: {physics}")
            all_used_physics.extend(physics)

        used_bg_names.extend(bg)
        used_obj_names.extend(obj)
        used_emo_names.extend(emo)

        current_vector = compute_scene_vector(elements)
        main_emotion = elements["main_emotion"]  # 본문 판정: 재료 선택용 벡터와 분리
        elements_path.write_text(json.dumps(elements, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  장면{scene_num} 벡터: {[round(x, 2) for x in current_vector]}")
        print(f"  장면{scene_num} 감정: {main_emotion['label']} ({main_emotion['intensity']})")
        print(f"  주요 배경: {elements['main_background']}")
        print(f"  주요 오브제: {elements['main_object']}")

        previous_stories.append(story)
        previous_main_emotions.append(main_emotion["label"])

    print(f"\n{'═'*50}")
    print("  4개 장면 생성 완료")
    print(f"{'═'*50}")
    for i in range(1, 5):
        print(f"  scene{i}_story.txt / scene{i}_elements.json")

    # ── 전체 결과 단일 JSON으로 취합 ───────────────────
    export = []
    for i in range(1, 5):
        story_text = (out / f"scene{i}_story.txt").read_text(encoding="utf-8")
        elem       = json.loads((out / f"scene{i}_elements.json").read_text(encoding="utf-8"))
        scene_vector = compute_scene_vector(elem)
        export.append({
            "scene": i,
            "story": story_text,
            "backgrounds": [e["항목"] for e in elem.get("배경",  [])],
            "objects":     [e["항목"] for e in elem.get("오브제", [])],
            "emotions":    [e["항목"] for e in elem.get("감정",  [])],
            "physics_laws": elem.get("물리법칙", []),
            "main_emotion": elem["main_emotion"],
            "main_emotion_evidence": elem["main_emotion_evidence"],
            "main_emotion_reason": elem["main_emotion_reason"],
            "main_background": select_main_element(elem, "배경", "main_background"),
            "main_object": select_main_element(elem, "오브제", "main_object"),
            "main_object_evidence": elem.get("main_object_evidence", ""),
            "main_object_reason": elem.get("main_object_reason", ""),
            "vector":      [round(x, 3) for x in scene_vector],
        })

    export_path = out / "dream_scenes.json"
    export_path.write_text(
        json.dumps({
            "축순서": ["Pleasantness", "Attention", "Sensitivity", "Aptitude"],
            "평가기준버전": "Hourglass of Emotions (Cambria et al., 2012)",
            "scenes": export,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"\n  취합 완료 → {export_path}")


if __name__ == "__main__":
    inp        = sys.argv[1] if len(sys.argv) > 1 else "team2/output/parsed_scenes.json"
    out        = sys.argv[2] if len(sys.argv) > 2 else "team2/output"
    blueprint  = sys.argv[3] if len(sys.argv) > 3 else "team1/output/assembled_blueprint.json"
    peaks      = sys.argv[4] if len(sys.argv) > 4 else "team1/output/emotion_peaks.txt"
    main(inp, out, blueprint, peaks)
