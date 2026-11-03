# GridModel 오브제 영상 확인

GridModel은 `team4/input/object/object_line_1.mp4`의 오브제 실루엣 안에 셀룰러 오토마타(CA)를 적용합니다. `team4/input/sound/`의 음악과 `team4/input/background/scenes.json`의 장면 감정을 읽어 오브제 크기 변화를 만듭니다. 배경 영상과 DreamModel은 단독 실행에 사용하지 않습니다.

## 입력

- 오브제: `team4/input/object/object_line_1.mp4` (검은 배경)
- 음악: `team4/input/sound/`의 WAV, MP3, M4A, AAC, FLAC, OGG 중 한 파일. 여러 개면 파일명순 첫 파일을 사용합니다.

## 5분짜리 오브제만 렌더링하기

PowerShell에서 `team4` 폴더로 이동한 뒤 실행합니다.

```powershell
.\DreamModel\.venv\Scripts\python.exe .\Grid_Model\GridModel\pythonimagemodel.py --preview
```

가상환경에 `numpy`, `opencv-python`이 필요합니다. 음악 분석과 확인용 영상의 오디오 결합에는 FFmpeg가 필요하며, 시스템의 `ffmpeg` 또는 가상환경의 `imageio-ffmpeg`를 사용합니다.

## 결과

| 파일 | 내용 |
|---|---|
| `team4/output/gridmodel_object_ca.mp4` | 검은 배경의 오브제 전용 레이어. `main.py`가 최종 합성에 사용합니다. |
| `team4/output/gridmodel_object_ca_preview.mp4` | 위 레이어에 입력 음악을 결합한 확인용 영상. `--preview` 실행 시 생성됩니다. |

입력 오브제 영상의 프레임을 최대 300초까지 처리합니다. 입력 영상이 5분이면 결과도 약 5분입니다. 확인용 영상에는 DreamModel 배경이 포함되지 않습니다.

## 시작 연출

영상 시작 뒤 5초는 오브제를 완전히 검게 유지합니다. 이후 3초 동안 부드럽게 밝아지며 오브제가 드러납니다. 이 연출은 오브제 레이어와 `--preview` 결과에 모두 적용됩니다.

## 감정·음악에 따른 움직임

음악은 50ms 단위로 분석하지만, 2.5초 동안 평활화해 매 프레임 흔들리는 움직임을 제거합니다. 큰 소리는 최소 10초 간격으로만 감지해 짧은 크기 반응을 만들고, 장면의 감정은 전체 움직임의 성격을 정합니다.

- 기쁨: 비교적 밝고 완만한 확장
- 슬픔·혐오: 작고 느린 호흡
- 분노: 조금 더 빠른 반응
- 공포·놀람: 드문 큰 소리 뒤의 짧은 반응
- 중립: 가장 약하고 안정적인 호흡

오브제의 중심을 기준으로 크기를 **98~103%** 범위에서 제한해 원래 형태를 알아볼 수 있도록 합니다. 장면 경계에서는 4초 동안 다음 감정의 움직임으로 부드럽게 전환합니다.

회전은 상위 2% 수준의 큰 음악 피크가 있을 때만 적용합니다. 감정별 회전 상한은 놀람 25도, 분노 16도, 공포 14도, 혐오 7도, 기쁨 4도이며 슬픔·중립은 회전하지 않습니다. 회전은 약 0.18초에 걸쳐 나타난 뒤 약 4초 이내에 사라지고, 다음 회전까지 최소 10초를 둡니다.

음악 에너지가 높은 구간에서는 오브제 원본 프레임을 조금 더 빠르게 진행하고, 낮은 구간에서는 프레임을 유지해 느리게 진행합니다. 이 속도 변화는 각 75초 장면 안에서 누적 이동량을 다시 정규화하므로, 네 장면은 각각 정확히 75초를 유지합니다. 현재 속도 범위는 약 `0.82×~1.18×`입니다.

`scenes.json`이 없거나 읽을 수 없고 배경 영상이 하나 있으면, GridModel은 그 영상의 네 지점에서 색·밝기·대비를 읽어 보조 움직임을 만듭니다. 감정이 일부 누락된 장면은 해당 장면만 이 보조 규칙을 사용합니다. 감정 정보와 읽을 수 있는 배경 영상이 모두 없으면 오브제 크기는 100%로 고정됩니다.

이 범위와 반응 속도는 `config.py`의 `OBJECT_MIN_SCALE`, `OBJECT_MAX_SCALE`, `AUDIO_SMOOTH_SECONDS`, `BEAT_MIN_GAP_SECONDS`, `BEAT_DECAY_SECONDS`, `MAX_ROTATION_DEGREES`, `PLAYBACK_SPEED_MIN`, `PLAYBACK_SPEED_MAX`, `PLAYBACK_SPEED_RESPONSE`에서 조정할 수 있습니다.

`main.py`로 통합 영상을 만들 때는 `--preview` 없이 GridModel이 실행되므로 합성용 오브제 레이어만 생성됩니다.
