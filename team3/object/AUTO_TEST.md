# 오브제 자동화 시험 (오브제 담당 PC · 10-19)

명령 한 줄로 **대본 확인 → 오브제 PNG 생성(ComfyUI) → 오브제 영상 렌더**까지 이어지는지 확인하는 시험입니다.

## 준비
1. 최신 코드 받기 (저장소 폴더에서)
   ```
   git checkout team3
   git pull origin team3
   ```
2. ComfyUI 켜기 (`run_nvidia_gpu.bat`) — `models/loras` 에 `dream_object_lora.safetensors` 가 있어야 합니다.

## 시험 (저장소 맨 위 폴더에서)
```
python team3/run_team3.py --object --quick
```
- 대본은 저장소에 들어 있는 시험 판을 씁니다: `team3/background/input/storyboard/dream_scenes.json` (공포 · 공포 · 중립 · 중립 · 오브제 16개)
- 지금 `output_objects` 는 예전 판(아르카디아)이라 다른 판으로 판단하고, PNG 를 새로 만듭니다.
  - 예전 판은 지우지 않고 `team3/object/output/objects_archive/<시각>/` 로 옮겨 둡니다.
  - 생성이 중간에 실패하면 예전 판을 제자리로 돌려놓고 멈춥니다.
- `--quick` = 장면 10초 · 절반 해상도 → 40초짜리 시험 영상

결과: `team3/object/output/render_<시각>_quick/object_line.mp4`

## 시험이 끝나면 알려 주세요
1. 걸린 시간 (PNG 생성 · 렌더)
2. 화면 마지막 10줄쯤 (멈췄으면 `[중단]` 줄)
3. 시험 영상 (`object_line.mp4`)

※ 새로 만든 `output_objects` 는 **아직 커밋하지 마세요** — 통합 담당이 확인한 뒤 정합니다.

## 그 밖의 명령
| 명령 | 하는 일 |
|---|---|
| `python team3/run_team3.py --object` | 실제 5분 오브제 영상 (배경 영상이 있으면 배경 위 통합) |
| `python team3/run_team3.py --object --alpha` | 위 + 4팀 합성용 오브제만 + 투명도(`_matte.mp4`) |
| `python team3/run_team3.py --object --no-gen` | PNG 는 만들지 않음 — 다른 판이면 렌더하지 않고 멈춤 |

대본과 오브제가 다른 판이면 렌더하지 않습니다 (오브제 엔진은 이름이 안 맞아도 같은 번호의 옛 PNG 를 쓰기 때문).
