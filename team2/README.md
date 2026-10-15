# 2팀 — 꿈 장면 생성

1팀이 측정한 관객 공감 반응을 입력으로 받아, 서로 이어지는 꿈 장면 4편을 생성하고
3팀이 쓸 구조화된 데이터로 넘긴다. 장면과 장면은 4차원 감정 벡터로 연결된다.

```
1팀 emotion_peaks.txt ─┬─> step1_parse.py ─> parsed_scenes.json
1팀 assembled_blueprint.json ─┘                      │
                                                      v
                                        step2_story_v2.py
                                                      │
                                      dream_scenes.json ─> 3팀
```

---

## 실행

저장소 루트(`Capstone2`)에서 실행한다. 상대 경로를 쓰므로 반드시 루트에서 실행해야 한다.

```bash
# 전체 (촬영 건너뛰고 테스트 CSV 사용)
python run_pipeline.py --emotion-csv team1/testdata/session_20261005_005030.csv
```

| 단계 | 하는 일 | 소요 |
|---|---|---|
| 1/5 step3b | 관객 감정 측정 (CSV를 주면 건너뜀) | — |
| 2/5 step4 | 공감 피크 탐지 | 4초 |
| 3/5 step5·6 | 키워드 풀 + 설계도 진화 | 26초 |
| 4/5 step1 | 피크 파싱 | 2초 |
| 5/5 step2 | 꿈 이야기 4장면 생성 | 7~9분 |

### 중간에서 멈추기

```bash
--until peaks       # 공감 피크까지만 (LLM 호출 없음)
--until blueprint   # 1팀 설계도까지만
--until parse       # 파싱까지만
```

### 같은 결과를 다시 얻기

```bash
--seed 7            # 설계도 고정 (시연용)
--curiosity 0.6     # 더 기묘한 설계도 선호 (기본 0.3)
--iters 5000        # 진화 횟수 축소 (기본 20000)
```

`--seed`를 주지 않으면 진화 탐색과 글 생성 양쪽에 무작위성이 있어 **실행마다 다른 결과**가 나온다.

### step2만 다시 돌리기

```bash
python team2/step2_story_v2.py team2/output/parsed_scenes.json team2/output
```

### 환경

- Python 3.10 venv (`venv/Scripts/python.exe`)
- `.env`에 `ANTHROPIC_API_KEY` 필요 (저장소 루트 또는 `team2/`)
- Windows에서 한글 출력이 깨지면 `PYTHONIOENCODING=utf-8`
- VS Code는 `.vscode/launch.json`에 설정이 있어 `F5`로 실행된다

---

## 출력 포맷 — `team2/output/dream_scenes.json`

```json
{
  "축순서": ["Pleasantness", "Attention", "Sensitivity", "Aptitude"],
  "평가기준버전": "Hourglass of Emotions (Cambria et al., 2012)",
  "scenes": [
    {
      "scene": 1,
      "story": "배관 입구가 쪽, 소리를 낸다. ...",
      "backgrounds": ["배관 입구", "얼음벽과 균열"],
      "objects": ["잿빛 새", "점성 액체와 거품"],
      "emotions": ["얼어붙은 정지의 공포", "끈적함에 대한 혐오"],
      "physics_laws": ["떨어진 액체가 공중에서 멈춤"],
      "main_emotion": { "label": "공포", "intensity": 0.7 },
      "vector": [-0.57, 0.42, 0.567, -0.3]
    }
  ]
}
```

| 필드 | 설명 |
|---|---|
| `scene` | 장면 번호 1~4 |
| `story` | 공백 제외 500~650자 본문 |
| `backgrounds` / `objects` / `emotions` | 글에서 역추출한 요소 이름 |
| `physics_laws` | 현실과 어긋난 꿈의 논리 |
| `main_emotion` | 지배 감정. `label`은 1팀 7종(분노·혐오·공포·기쁨·슬픔·놀람·중립), `intensity`는 0.0~1.0 |
| `vector` | 장면 대표 감정 벡터. 요소별 벡터의 가중 평균 |

---

## 3팀 연동 시 주의사항

이전 버전에서 두 군데가 달라졌다.

### 장면 객체 8개 필드 — 변경 없음

`scene` `story` `backgrounds` `objects` `emotions` `physics_laws` `main_emotion` `vector`
추가·삭제된 필드가 없다. **장면 단위로 읽는 코드는 수정이 필요 없다.**

### 최상위 키 2개 추가

```jsonc
// 이전
{ "scenes": [...] }

// 현재
{ "축순서": [...], "평가기준버전": "...", "scenes": [...] }
```

`data["scenes"]`로 접근하면 영향이 없다. 키를 순회하거나 개수를 검사하는 코드는 확인이 필요하다.

### `vector` 값 범위 변경 — `0.0 ~ 1.0` → `-1.0 ~ +1.0`

**가장 주의할 변경이다.** 축 체계를 Hourglass of Emotions로 교체하면서 0이 중립이 되고 음수가 생겼다.

```
이전  긴장도 / 이질감 / 밀도 / 온도            0.0 ~ 1.0
현재  Pleasantness / Attention /
      Sensitivity / Aptitude                 -1.0 ~ +1.0
```

실측 범위는 `-0.756 ~ 0.762`이고 값의 절반 정도가 음수다. `vector` 값을 밝기·채도 같은
파라미터에 그대로 곱하는 코드가 있으면 음수에서 깨진다. 0~1이 필요하면 다음과 같이 변환한다.

```python
normalized = [(v + 1) / 2 for v in vector]
```

### 축의 의미

| 축 | −1 | +1 |
|---|---|---|
| Pleasantness | 불쾌 · 혐오 · 공포 | 기쁨 · 편안 · 아름다움 |
| Attention | 무관심 · 멍함 | 각성 · 호기심 · 긴장 |
| Sensitivity | 둔감 · 익숙함 | 예민 · 날카로움 · 낯섦 |
| Aptitude | 무력감 · 좌절 | 자신감 · 유능함 · 성취 |

근거: Cambria et al., 2012 (Hourglass of Emotions) / Cambria, 2014 (SenticNet 3 — 감정 단어가
아닌 일반 개념에 4차원 벡터를 적용한 선례)

---

## 동작 구조

1~2는 한 번만, 3~6은 장면마다 반복된다. 6의 출력이 다시 3의 입력이 되는 순환이다.

1. **재료 개수 결정** — 공감 비율 `P`로 `q = max(0, min(1, (P-50)×2/100))`,
   `N = 최소값 + Binomial(최대값 - 최소값, q)`. 관객이 많이 공감한 작품일수록 재료가 많아진다.
2. **장면1 재료 확보** — 1팀 `assembled_blueprint.json` 우선. 없거나 특정 종류만 비어 있으면
   그 종류만 `emotion_peaks`에서 추출하는 대안 경로로 채운다.
3. **글 생성** — Claude Sonnet. 재료 + 작성 규칙 10개. 분량·금지표현·문장 완결을 검사하고
   실패하면 문제점을 적어 최대 3회 재시도한다.
4. **역분석** — 완성된 글에서 요소를 다시 뽑고 각 요소에 Hourglass 벡터를 매긴다.
   요소별로 `근거문장`·`평가상태`·`판단근거`를 함께 남기고, 판단이 불가하면 벡터를 비워
   평균 계산에서 제외한다. 가중 평균(배경 0.2 / 오브제 0.5 / 감정 0.3)으로 장면 벡터를 만든다.
5. **Dream Drift** — `목표 = 현재 + 무작위 단위벡터 × (1 - COHERENCE) × MAX_DRIFT`
6. **코사인 유사도 샘플링** — 목표 벡터에 가까운 재료를 softmax 확률로 뽑는다.
   후보는 직전 장면 요소 + 원본 풀이고, 이미 쓴 재료는 가중치를 낮춘다.

### 반복 억제

- 추출될 때마다 이름이 바뀌는 같은 사물(`전구` → `깜빡이는 전구` → `전구(필라멘트)`)을
  `is_same_thing()`이 접두 일치로 판정해 가중치를 `REPEAT_PENALTY`배로 낮춘다.
- 하드 제외를 쓰지 않는 이유: 후보 풀이 작아 전부 제외되는 경우가 생기고, 그때 fallback으로
  되돌아가면 억제가 통째로 무효화된다.
- 이름 자체에 금지표현이 든 재료(`닿을 듯 닿지 않는 긴장감`)는 샘플링에서 제외한다.
  모델이 "재료를 모두 쓰라"와 "`듯` 금지"를 동시에 만족할 수 없기 때문이다.

### 품질 검사 벌점

재시도를 모두 소진하면 벌점이 가장 낮은 초안을 쓴다. 문제 개수가 아니라 종류별 무게로 비교한다.

| 위반 | 벌점 |
|---|---|
| 빈 글 | 1,000,000 (채택 불가) |
| 문장 중간 끊김 | 1,000 |
| 금지표현 (`듯` `것 같` `느낌`) | 건당 500 |
| 분량 이탈 | 벗어난 글자 수만큼 |

---

## 조정 가능한 값

`team2/step2_story_v2.py` 상단에 있다.

| 상수 | 기본값 | 의미 |
|---|---|---|
| `COHERENCE` | 0.9 | 벡터 drift 크기. 낮추면 장면마다 분위기가 크게 튄다 |
| `MAX_DRIFT` | 0.2 | 분위기 변화 최대폭. 축 범위가 −1~1(폭 2.0)이라 0~1 시절의 2배 값 |
| `CONTEXT_LEVEL` | 0.5 | 이전 글 전달량. 0=없음 / 0.5=직전 마지막 문단 / 1.0=직전 전문 |
| `TEMPERATURE` | 0.3 | 샘플링 무작위성. 낮으면 유사도 1위를 자주 고른다 |
| `REPEAT_PENALTY` | 0.1 | 이미 쓴 재료의 가중치 배수 |
| `BG_RANGE` / `OBJ_RANGE` / `EMO_RANGE` | (1,2) / (1,3) / (1,3) | 재료 개수 (최소, 최대) |
| `VECTOR_WEIGHTS` | 배경 0.2 / 오브제 0.5 / 감정 0.3 | 장면 벡터 가중 평균 비율 |
| `MIN_CHARS` / `TARGET_CHARS` / `MAX_CHARS` | 500 / 580 / 650 | 분량 기준 (공백 제외) |
| `MAX_TRIES` | 3 | 글 생성 재시도 횟수 |

`COHERENCE`와 `CONTEXT_LEVEL`은 분리되어 있다. 이전에는 한 값이 drift와 컨텍스트 전달량을
겸해서, 높이면 프롬프트에 이전 장면 전체가 누적돼 모델이 같은 장면을 계속 이어썼다.

사용 모델: 요소 추출 `claude-haiku-4-5-20251001`, 글 생성 `claude-sonnet-5`

---

## 파일

| 파일 | 역할 |
|---|---|
| `step1_parse.py` | `emotion_peaks.txt` → `parsed_scenes.json` |
| `step2_story_v2.py` | 4장면 생성 + 벡터 추출 + `dream_scenes.json` 취합 |
| `step5_image.py` | 이미지 생성 (ComfyUI 연동) |
| `output/scene{N}_story.txt` | 장면별 본문 |
| `output/scene{N}_elements.json` | 장면별 요소 + 벡터 + 근거문장 |
| `output/dream_scenes.json` | 3팀 전달용 취합 결과 |

`output/`은 `.gitignore` 대상이다. 실행하면 생성된다.
