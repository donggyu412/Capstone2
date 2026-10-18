# DreamModel · Collective Dreaming

DreamModel은 이야기·감정·사운드를 생성 조건으로 사용해 배경과 오브제가 서서히 형성·변형·소멸하는 꿈 애니메이션을 만든다. 배경과 오브제는 별도의 생성·진화 엔진을 사용하며, 장면 사이에 형태·색·이동 흔적(Relic / Trace)을 상속한다.

완성본 규격은 **1920×1080 / 30fps / 300초 / 9,000프레임**이다. 기 0–75초, 승 75–150초, 전 150–225초(클라이맥스 반전 `195.0초` / `3:15`), 결 225–300초로 구성한다. 전환에서는 앞 장면의 기억과 다음 장면의 형성이 겹친다.

## 설치

저장소 루트에서 Python 3.12 기준으로 실행한다.

```powershell
python -m venv team4/DreamModel/.venv
.\team4\DreamModel\.venv\Scripts\python.exe -m pip install -r team4/DreamModel/requirements.txt
```

## 입력 및 배경 구현 전달 슬롯 (`team4/input/`)

| 입력 구분 | 위치 / 내용 |
|---|---|
| 이야기·장면 (공통) | `team4/input/storyboard/scenes.json`, `dream_scenes.json`, `scene_01~04.png` (원본 유지) |
| 오브제 (공통) | `team4/input/objects/objects.json`과 장면별 RGBA 이미지 13개 (원본 유지) |
| **배경 구현 전달 슬롯** | `team4/input/background/` — 오브제 합성 전달용 1·2·3번 시나리오 5분 배경 MP4 영상 3종(`1~3번_꿈재현_배경_사운드.mp4`) 및 시나리오별 원본 에셋·사운드(`scenarios/`) |
| 구도 | `configs/assumed_layout.json`의 정규화 좌표 |
| 집단 감응 | `--audience-arousal`, `--audience-tension`, `--audience-coherence` |

## 1. 꿈 재현 — 배경 애니메이션(MemoryCA + Open-Ended Evolution) 실행

1·2·3번 시나리오별 원본 배경판 4계층 분해, 기억 셀룰러 오토마타(`MemoryCA`), 다중 스케일 점묘 격자(`Lattice`), 변형장 진화(`FieldEvolution`), 그리고 시나리오별 고유 사운드 동기화가 결합된 배경 애니메이션 렌더러를 실행한다.

```powershell
# [빠른 프리뷰] 15개 핵심 시각 프레임 흐름 시트 및 원본 대비 비교 시트 생성
python -m team4.DreamModel.tools.render_background_ca --film 1 --preview
python -m team4.DreamModel.tools.render_background_ca --film 2 --preview
python -m team4.DreamModel.tools.render_background_ca --film 3 --preview

# [본 렌더링] 5분(300초, 1920x1080, 30fps, 9,000프레임) 시나리오별 사운드 결합 배경 영상 생성
python -m team4.DreamModel.tools.render_background_ca --film 1
python -m team4.DreamModel.tools.render_background_ca --film 2
python -m team4.DreamModel.tools.render_background_ca --film 3

# 1·2·3번 시나리오 연속 일괄 렌더링
python -m team4.DreamModel.tools.render_background_ca --films 1,2,3
```

## 2. 오브제·배경 통합 파이프라인 실행 (`main.py`)

```powershell
# 원래 시간축의 65–90초 전환을 1배속으로 검수
.\team4\DreamModel\.venv\Scripts\python.exe -m team4.DreamModel.main --preview --preview-start 65 --preview-seconds 25 --audio "received_sound.wav" --output team4/DreamModel/output/transition_v1.mp4

# 배경 단독 / 오브제 단독 / 통합 프리뷰
.\team4\DreamModel\.venv\Scripts\python.exe -m team4.DreamModel.tools.preview_layers --audio "received_sound.wav" --output team4/DreamModel/output/review_v1

# 기승전결 각 75초, 전체 300초 통합 렌더
.\team4\DreamModel\.venv\Scripts\python.exe -m team4.DreamModel.main --final --audio "received_sound.wav" --output team4/DreamModel/output/Collective_Dreaming_Final_1080p_300s.mp4
```

## 검증

```powershell
.\team4\DreamModel\.venv\Scripts\python.exe -m unittest discover -s team4/DreamModel/tests -q
.\team4\DreamModel\.venv\Scripts\python.exe -m team4.DreamModel.tools.validate_conditions --audio "received_sound.wav" --output team4/DreamModel/output/validation_v1
```

1·2·3번 시나리오 배경 완성본의 정량 검증 보고서(`1~3번_제작검증_v3.json`)와 15프레임 흐름 시트·원본 대비 비교 시트는 [`docs/verification/`](docs/verification/)에 수록되어 있다.

## 활성 코드

| 파일 | 책임 |
|---|---|
| [background_ca_engine.py](runtime/background_ca_engine.py) | 기억 셀룰러 오토마타(`MemoryCA`), 다중 스케일 점묘 격자(`Lattice`), 부유 입자계(`Particles`), 다대역 사운드 분석기(`analyze_sound`) |
| [background_scene_decomposer.py](runtime/background_scene_decomposer.py) | 원본 배경판 4계층 분해(`extract_plate_layers`), Open-Ended 변형장 진화(`FieldEvolution`), 시나리오 1·2·3번 서사 물리 및 `3:15` 반전 합성 |
| [render_background_ca.py](tools/render_background_ca.py) | 1·2·3번 시나리오 배경 애니메이션 단독 렌더링 및 프리뷰 시트 생성 CLI |
| [main.py](main.py) | 통합 실행 옵션과 프리뷰 / 완성본 분기 |
| [dream_pipeline.py](runtime/dream_pipeline.py) | 공통 입력·생성 상태 준비, 단일 시간창 프리뷰 |
| [render_final.py](runtime/render_final.py) | 4구간 상태 전달, 전체 렌더와 음원 포함 |
| [background_openended.py](runtime/background_openended.py) | 영역 그래프 기반 기억 조건 반응·확산, 파라미터 진화, 다중 규모 경쟁 |
| [dream_world.py](runtime/dream_world.py) | 오브제 구조 진화·선택·기억 상속, 공통 세계 시계 |
| [dream_surfaces.py](runtime/dream_surfaces.py) | 소스의 윤곽·색 통계 추출, 성장 표면과 소멸 렌더 |
| [dream_score.py](runtime/dream_score.py) | 4장면의 이야기·physics_laws를 시각적 동작과 시간으로 연결 |
| [input_loader.py](runtime/input_loader.py) / [semantic_conditioning.py](runtime/semantic_conditioning.py) | 공유 입력 계약과 감정·스토리 조건 |
| [audio_analyzer.py](runtime/audio_analyzer.py) | 음원의 에너지와 변화량 분석 |

전체 프로젝트에 대한 쉬운 포괄 설명과 배경·오브제 작동 원리는 [통합 가이드](docs/GUIDE.md)에, 세부 생성·진화 수식과 검증 결과는 [구현 명세](docs/IMPLEMENTATION.md)에 정리되어 있다.
