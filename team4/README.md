# Team 4 영상 생성

Team 4 파이프라인은 배경 영상과 오브제 영상을 각각 처리한 뒤 합성하고, 음악을 포함한 최종 MP4를 만듭니다. 실행은 `main.py` 한 번으로 진행합니다.

```text
배경 MP4 + 장면 정보 ──> DreamModel ──> 애니메이션 배경 ─┐
                                                         ├─> 합성 + 음악 ─> output/team4_output.mp4
오브제 MP4 ────────────> GridModel ───> CA 오브제 레이어 ─┘
```

DreamModel과 GridModel의 모델 구현은 각각의 폴더에 있습니다. `main.py`는 입력 확인, 두 모델의 실행, 결과 영상 합성을 연결합니다.

## 폴더 구성

```text
team4/
├─ main.py
├─ DreamModel/
│  ├─ .venv/                         # 로컬 가상환경, 저장소에 공유하지 않음
│  └─ tools/render_background_ca.py
├─ Grid_Model/GridModel/
│  ├─ config.py
│  └─ pythonimagemodel.py
├─ input/
│  ├─ background/
│  │  ├─ <배경영상>.mp4
│  │  ├─ scenes.json
│  │  └─ dream_scenes.json
│  ├─ object/object_line_1.mp4
│  └─ sound/<음악 파일>
└─ output/
```

## 입력 파일 준비

| 입력 | 위치 | 조건 |
|---|---|---|
| 배경 영상 | `input/background/` | 지원 확장자 `.mp4`, `.mov`, `.mkv`, `.avi`, `.webm` 중 하나의 영상만 둡니다. 300초 영상의 각 75초 장면 중앙(37.5, 112.5, 187.5, 262.5초)을 목표 이미지로 추출하고, 전체 영상의 빛과 움직임 변화도 분석합니다. |
| 장면 감정 설정 | `input/background/scenes.json` | `scenes` 배열에 장면 4개가 있어야 합니다. 각 장면의 `emotion`은 `기쁨`, `슬픔`, `분노`, `공포`, `놀람`, `혐오`, `중립` 중 하나여야 합니다. |
| DreamModel 장면 서사 | `input/background/dream_scenes.json` | 배경 영상과 같은 판의 장면 서사 JSON입니다. |
| 오브제 영상 | `input/object/object_line_1.mp4` | 검은 배경의 오브제 영상입니다. GridModel은 검은 영역을 비우고 오브제 실루엣 안에서만 셀룰러 오토마타를 적용합니다. |
| 음악 | `input/sound/` | `.wav`, `.mp3`, `.m4a`, `.aac`, `.flac`, `.ogg` 지원. 사용할 음악 하나만 둡니다. 여러 파일이 있으면 통합 실행은 오류로 알립니다. |

`scenes.json`의 최소 구조 예시는 다음과 같습니다. 실제 입력에는 장면별 추가 설정이 포함될 수 있습니다.

```json
{
  "scenes": [
    {"emotion": "기쁨"},
    {"emotion": "슬픔"},
    {"emotion": "분노"},
    {"emotion": "중립"}
  ]
}
```

배경 영상이 있어도 두 JSON 파일이 빠지면 실행되지 않습니다. 배경 MP4·두 JSON·오브제·사운드는 같은 실행/전달 묶음의 파일을 사용하세요. 10/31 전달본을 재현하려면 ZIP의 다섯 입력을 함께 교체해야 합니다. `run_all.py`는 앞 단계에서 생성한 입력을 채운 뒤 이 통합 경로를 실행합니다.

## 실행 환경 설치

- Windows 10/11 64비트
- Python 3.12 64비트
- NVIDIA GPU 권장 (CUDA 지원 PyTorch 사용 시 자동으로 GPU를 선택)
- FFmpeg: 시스템에 설치되어 있으면 사용하고, 없으면 Python 패키지 `imageio-ffmpeg`에서 실행 파일을 찾습니다.

PowerShell에서 `team4` 폴더로 이동해 아래 명령을 한 줄씩 실행합니다. `py --list`에서 Python 3.12가 확인되어야 합니다.

```powershell
py -3.12 -m venv .\DreamModel\.venv
.\DreamModel\.venv\Scripts\python.exe -m pip install --upgrade pip
```

### NVIDIA GPU 사용

```powershell
.\DreamModel\.venv\Scripts\python.exe -m pip install "torch==2.14.1+cu126" --index-url https://download.pytorch.org/whl/cu126 --extra-index-url https://pypi.org/simple
.\DreamModel\.venv\Scripts\python.exe -m pip install opencv-python numpy imageio-ffmpeg
```

CUDA를 확인합니다.

```powershell
.\DreamModel\.venv\Scripts\python.exe -c "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'GPU 미사용')"
```

CUDA 확인 결과가 `True`이고 GPU 이름이 표시되면 GPU를 사용할 수 있습니다. CUDA용 PyTorch가 설치되어 있지 않거나 GPU가 없으면 아래 CPU용 설치 명령을 사용합니다.

```powershell
.\DreamModel\.venv\Scripts\python.exe -m pip install torch opencv-python numpy imageio-ffmpeg
```

CPU 렌더링은 GPU보다 오래 걸릴 수 있습니다. 가상환경 폴더 `DreamModel/.venv/`는 컴퓨터마다 다시 만들어야 하며 공유하지 않습니다.

## 실행

PowerShell 현재 위치를 `team4` 폴더로 맞춘 뒤 다음 중 한 방법으로 실행합니다.

```powershell
# 가상환경을 활성화한 다음 실행
.\DreamModel\.venv\Scripts\Activate.ps1
python .\main.py
```

또는 가상환경 Python을 직접 지정합니다.

```powershell
.\DreamModel\.venv\Scripts\python.exe .\main.py
```

가상환경을 활성화하지 않아도 `main.py`는 `DreamModel/.venv/Scripts/python.exe`가 있으면 해당 Python으로 모델들을 실행합니다. 가상환경이 없으면 현재 PowerShell의 Python을 사용합니다.

## 처리 순서와 결과

1. `main.py`가 모델 Python에서 `torch`, `cv2`, `numpy`를 불러올 수 있는지 확인합니다.
2. 배경 MP4와 두 JSON을 DreamModel v13의 `--background-video --silent` 경로로 전달합니다.
3. DreamModel이 감정별 리듬·가변 셀 크기·전체 입력 영상의 시간 변화를 사용해 배경을 생성합니다.
4. 기존 GridModel이 오브제 실루엣 안에 CA를 적용하고, 감정과 음악에 따른 크기·회전 반응을 만듭니다.
5. DreamModel 배경에 GridModel 오브제와 음악을 합성합니다. 입력 배경을 추가로 덮지 않으며, 오브제의 반투명 경계색을 보정합니다. 음악은 2dB 여유와 짧은 시작·종료 페이드를 적용합니다.

최종 영상:

```text
output/team4_output.mp4
```

최종 출력은 1920×1080, 30fps, 300초(9,000프레임)입니다. 중간 레이어와 검증 JSON을 보존합니다. 짧은 시험 영상은 자동으로 늘이거나 반복하지 않습니다. 전체 디코딩 검사를 통과한 파일만 최종 이름으로 저장합니다.

## 최종 전달 인코딩과 기존 영상 압축

`video_encoding.py`에서 H.264 `medium`, CRF 20 설정을 공유합니다. `grain` 튜닝은 사용하지 않습니다. 촘촘한 셀이 빠르게 움직일 때 질감이 뭉개지지 않도록 순간 비트레이트 상한은 두지 않습니다. 일반 통합 실행도 이 설정을 사용합니다.

이미 완성한 5분 통합본의 용량만 줄일 때는 모델을 다시 돌리지 않습니다. `team4` 폴더에서:

```powershell
.\DreamModel\.venv\Scripts\python.exe .\tools\compact_video.py "기존_5분_통합본.mp4" --output ".\output\team4_output_compact.mp4"
```

이 도구는 해상도·프레임 수·장면 순서·시간축을 유지하고, 오디오는 비트스트림 그대로 복사합니다. 영상은 손실 압축이므로 픽셀이 완전히 같지는 않으며 미세 입자에는 차이가 생길 수 있습니다. 기존 마스터를 보존하도록 별도 출력 파일을 요구합니다. 파일 규격·전체 디코딩·1GB 용량 예산 검사를 통과한 결과와 SHA-256을 저장합니다. 용량 검사는 큰 파일을 알리는 검증 단계이며, 자동으로 화질을 더 낮추지 않습니다.

실제 검증 결과: 기존 2.43GB → 756.1MB (68.90% 감소). 9,000프레임 전체 비교와 디코딩 검사를 완료했고, 오디오 비트스트림 해시가 원본과 같습니다. 수치·파일 해시는 [검증 기록](verification/compact_delivery.json)에 있습니다.

배경/오브제 레이어가 이미 준비된 경우에는 `main.py --background-layer <배경.mp4> --object-layer <GridModel.mp4>`로 합성만 다시 할 수 있습니다.

생성 영상은 기존 저장소 설정에 따라 Git 추적 대상에서 제외됩니다. 실행 코드와 검증 기록은 `team4` 브랜치에서 공유하고, 큰 MP4 입력/출력은 별도 전달합니다.

## 문제 해결

| 메시지/증상 | 확인할 내용 |
|---|---|
| `No module named 'torch'` | `DreamModel/.venv`에 패키지를 설치했는지, 실행에 같은 가상환경 Python을 쓰는지 확인합니다. |
| `No suitable Python runtime found` | Python 3.12 64비트를 설치하고 새 PowerShell에서 `py --list`로 확인합니다. |
| `input/background`에 배경 영상이 없다는 오류 | 배경 MP4를 해당 폴더에 넣고, 배경 영상은 하나만 남깁니다. |
| `scenes.json` 또는 `dream_scenes.json` 오류 | 파일명이 정확한지, 두 파일이 배경 영상과 함께 `input/background/`에 있는지 확인합니다. `scenes.json`에는 감정이 지정된 장면 4개가 있어야 합니다. |
| 감정 라벨 오류 | `emotion` 값이 `기쁨`, `슬픔`, `분노`, `공포`, `놀람`, `혐오`, `중립` 중 하나인지 확인합니다. |
| 오브제 MP4를 찾지 못함 | `input/object/object_line_1.mp4`의 경로와 파일명을 확인합니다. |
| CUDA가 `False` | GPU 미사용 CPU 모드로 실행됩니다. NVIDIA 드라이버와 CUDA용 PyTorch 설치를 확인합니다. |
| FFmpeg를 찾을 수 없음 | 가상환경에 `imageio-ffmpeg`가 설치되어 있는지 확인합니다. |
