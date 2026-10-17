# 1 → 4팀 실행 순서 (10/22 시연용 · 10-17 실측)

> 저장소 루트에서 실행. 시간은 10-17 이 노트북(i5 · 8GB · GPU 없음)에서 잰 값.
> 🙋 = 사람 손 / 다른 PC 가 필요한 단계. 나머지는 명령 한 줄.

| # | 단계 | 명령 | 어디서 | 걸린 시간 |
|---|---|---|---|---|
| 1 | 1팀 감정 → 2팀 꿈 이야기 4장면 | `python run_pipeline.py --emotion-csv <감정 CSV>` (실제 촬영이면 `--sources 0 1 --narration ...`) | 진행 PC | 약 5분 (Claude API) |
| 2 | 받기 → 프롬프트(배경 글 포함) → 배경 사진 4장 | `python team3/run_team3.py` | 진행 PC | 약 2분 (OpenAI · 장당 25~29초) |
| 3 | 5분 배경 영상 + 배경판 4장 | `python team3/run_team3.py --record` | 진행 PC (다른 프로그램 닫기) | 40~50분 (시험: 장면당 5초 → 1.3분) |
| 4 🙋 | 오브제 생성 + 통합 렌더(아날로그) | 3단계가 출력하는 명령 그대로 (`generate_objects_comfy.py` → `object_engine.py --bg ...`) | 오브제 담당 PC (GPU) | 오브제만 15분 30초 · 통합 약 30분 (10-12 담당 측정) |
| 5 | 사운드(1팀 아피찻퐁 · 자동) | `python team3/sound/generate_sound.py --style apichatpong` (공용 자리 스토리보드 + 사진을 스스로 읽음 · 오브제는 `--objects <이 판 오브제 폴더>`) | 진행 PC 가능 (10-17 실측) · 고품질은 1팀 PC | **약 3분**(182초) · 이 PC 는 그림 인식 꺼짐(`transformers` 없음) |
| 6 | 소리 붙이기 | `python team3/run_team3.py --mux <dream_integrated.mp4> <dream_sound.wav>` | 진행 PC | 수십 초 (다시 인코딩 안 함) |
| 7 | 4팀에 넘기기 (배경판 · 오브제 · 5분 통합 영상) | `python team3/run_team3.py --to-team4 --check` → `--to-team4 --video <통합_sound.mp4>` | 진행 PC | 수 초 |
| 8 | 4팀 애니메이션 | 4팀 코드 (`team4/`) | 4팀 | 4팀 측정 |

**안전장치(10-17 확인):** 7단계는 대본 · 배경판 · 오브제가 한 판이 아니면 4팀 자리를 건드리지 않고 멈춘다(다른 판 오브제 4장면 모두 잡아냄).
**⚠ 사운드의 오브제(10-17 시험):** 기본은 `team3/object/output_objects/` 를 읽는다 — 거기 있는 것이 **다른 판 오브제면 소리도 그 판 오브제(예: 항해일지 · 서류철)로 만들어진다.** 오브제가 새 판으로 나온 뒤에 돌리거나 `--objects` 로 그 판 폴더를 준다.
**시연 때 말할 것:** 1 → 3 · 5 · 6 → 7 은 명령 한 줄씩. GPU 가 필요한 4(오브제)만 담당 PC 에서 돈다. "완전 자동"이라고는 하지 않는다.

## 10-17 테스트 판 (미리 만든 결과물)
- 스토리보드: `team3/background/input/storyboards_1017_test/1_혐오공포놀람놀람/` — 감정 혐오 · 공포 · 놀람 · 놀람 · 2팀 이야기 글 4개 · 배경 글 · 프롬프트 · 사진 4장(깃에 포함 · 7.2MB — 팀원이 pull 하면 바로 씀).
- 짧은 배경 기록(장면당 5초 · 20초): `team3/background/output/20261017-210356_storyboard_mp4/` · 배경판 3장(`..._storyboard/` — 짧은 시험이라 마지막 장면을 못 찍음 · 5분 기록 3번은 모두 4장).
- 다른 판으로 바꿔 돌리기: `python team3/run_team3.py --storyboard <판>/dream_scenes.json` (그 자리의 옛 판은 `input/storyboard_archive/` 로 자동 보관).
