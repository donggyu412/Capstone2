# DreamModel · Collective Dreaming

DreamModel은 이야기·감정·받은 사운드를 생성 조건으로 사용해 배경과 오브제가 서서히 형성·변형·소멸하는 꿈 애니메이션을 만든다. 배경과 오브제는 별도의 생성·진화 엔진을 사용하며, 장면 사이에 형태·색·이동 흔적을 상속한다.

완성본 규격은 **1920×1080 / 30fps / 300초 / 9,000프레임**이다. 기 0–75초, 승 75–150초, 전 150–225초, 결 225–300초로 구성한다. 전환에서는 앞 장면의 기억과 다음 장면의 형성이 겹친다.

## 설치

저장소 루트에서 Python 3.12 이상으로 실행한다.

```powershell
python -m venv team4/DreamModel/.venv
.\team4\DreamModel\.venv\Scripts\python.exe -m pip install -r team4/DreamModel/requirements.txt
```

## 입력

| 입력 | 위치 / 내용 |
|---|---|
| 이야기·장면 | `team4/input/storyboard/scenes.json`, `dream_scenes.json` |
| 배경의 공간 기억 | `team3/background/input/storyboard/scene_01.png` ~ `scene_04.png` |
| 오브제 | `team4/input/objects/objects.json`과 장면별 RGBA 이미지 13개 |
| 사운드 | 별도로 전달받은 300초 음원을 `--audio`로 지정 |
| 구도 | `assumed_layout.json`의 정규화 좌표. 상류에서 확정한 배치가 아닌 명시적 가정 |
| 집단 감응 | `--audience-arousal`, `--audience-tension`, `--audience-coherence` |

배경·오브제·이야기 원본은 읽기 전용 입력으로 사용한다. 2팀 내부 vector는 사용하지 않는다. 실측 관객 데이터가 없는 기본 집단 조건은 `SIMULATION`으로 보고한다.

## 프리뷰와 완성본

아래 `--audio`의 예시 경로를 실제 전달받은 음원 경로로 바꾼다. 각 출력 경로는 아직 없는 새 이름을 사용한다. 생성물과 렌더 중간 상태는 Git에서 제외한다.

```powershell
# 원래 시간축의 65–90초 전환을 1배속으로 검수
.\team4\DreamModel\.venv\Scripts\python.exe -m team4.DreamModel.main --preview --preview-start 65 --preview-seconds 25 --audio "received_sound.wav" --output team4/DreamModel/output/transition_v1.mp4

# 배경 단독 / 오브제 단독 / 통합 프리뷰
.\team4\DreamModel\.venv\Scripts\python.exe -m team4.DreamModel.urgent_previews --audio "received_sound.wav" --output team4/DreamModel/output/review_v1

# 기승전결 각 75초, 전체 300초
.\team4\DreamModel\.venv\Scripts\python.exe -m team4.DreamModel.main --final --audio "received_sound.wav" --output team4/DreamModel/output/Collective_Dreaming_Final_1080p_300s.mp4
```

완성본은 2개 작업 프로세스로 4구간을 계산한다. 각 구간 첫 프레임 직전의 시뮬레이션 상태를 이어받고, 모든 프레임을 1080p에서 렌더한다. 영상을 재인코딩 없이 연결한 뒤 제공 음원 0–300초를 AAC로 포함한다. 보고서는 MP4 옆 `*_run_report.json`에 저장한다. 기존 영상이나 동일 이름의 렌더 중간 폴더가 있으면 덮어쓰지 않고 종료한다.

## 검증

```powershell
.\team4\DreamModel\.venv\Scripts\python.exe -m unittest discover -s team4/DreamModel/tests -q
.\team4\DreamModel\.venv\Scripts\python.exe -m team4.DreamModel.validate_urgent --audio "received_sound.wav" --output team4/DreamModel/output/validation_v1
```

`validate_urgent`는 동일 seed에서 story/emotion/sound/collective 및 진화·경쟁·기억·선택 조건을 하나씩 제거해 상태와 실제 프레임 차이를 비교한다. 같은 seed 재실행의 재현성도 확인한다.

2026-10-08 생성한 완성본은 9,000프레임 전체 디코딩, H.264/AAC, 300초, 원본 음원 동기 검증을 통과했다. 당시 음량 곡선 상관은 0.999864였다. MP4와 상세 실행·검증 JSON은 로컬 생성물이며 저장소에 포함하지 않는다. `verify_final_delivery.py`는 해당 제작 기록용 도구로, 기본적으로 로컬 보호 파일 해시 목록도 요구한다. 다른 환경에서는 `--protected`로 그 환경의 기준 목록을 지정해야 한다.

## 활성 코드

| 파일 | 책임 |
|---|---|
| [main.py](main.py) | 실행 옵션과 프리뷰 / 완성본 분기 |
| [dream_pipeline.py](dream_pipeline.py) | 공통 입력·생성 상태 준비, 단일 시간창 프리뷰 |
| [render_final.py](render_final.py) | 4구간 상태 전달, 전체 렌더와 음원 포함 |
| [background_openended.py](background_openended.py) | 기억 조건 반응·확산, 파라미터 진화, 다중 규모 경쟁 |
| [dream_world.py](dream_world.py) | 오브제 구조 진화·선택·기억 상속, 공통 세계 시계 |
| [dream_surfaces.py](dream_surfaces.py) | 소스의 윤곽·색 통계 추출, 성장 표면과 소멸 렌더 |
| [dream_score.py](dream_score.py) | 4장면의 이야기·physics_laws 20개를 시각적 동작과 시간으로 연결 |
| [input_loader.py](input_loader.py) / [semantic_conditioning.py](semantic_conditioning.py) | 공유 입력 계약과 공개 감정·스토리 조건 |
| [audio_analyzer.py](audio_analyzer.py) | 받은 음원의 에너지와 변화량 분석 |

7가지 기법의 규칙과 구현 범위는 [구현 설명](docs/IMPLEMENTATION.md)에 정리했다. 이전 `emergence_*`, `developmental_*`, `geometric_*` 등은 비교 실험과 회귀 테스트를 위해 보존하며, 현재 `main.py`의 최종 렌더 경로는 위 표를 따른다.

## 구현 범위

유한한 입력 자산과 문법 안에서의 생성·탐색이며 무제한 Open-endedness를 입증한 것은 아니다. 오브제 결합은 내부 제어 구조의 재조합으로 구현했고, 완성된 물체 간 물리적 충돌·융합은 구현하지 않았다. 일부 제공 오브제의 각진 접기 형태는 유지한다. 수치 검증은 관객의 시각적 평가를 대신하지 않는다.
