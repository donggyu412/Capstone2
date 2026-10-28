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
| 배경 영상 | `input/background/` | 지원 확장자 `.mp4`, `.mov`, `.mkv`, `.avi`, `.webm` 중 하나의 영상만 둡니다. DreamModel용 장면 이미지 4장은 이 영상의 10%, 35%, 65%, 90% 지점에서 자동 추출됩니다. |
| 장면 감정 설정 | `input/background/scenes.json` | `scenes` 배열에 장면 4개가 있어야 합니다. 각 장면의 `emotion`은 `기쁨`, `슬픔`, `분노`, `공포`, `놀람`, `혐오`, `중립` 중 하나여야 합니다. |
| DreamModel 장면 서사 | `input/background/dream_scenes.json` | DreamModel의 `--from-input` 실행에 필요한 JSON입니다. |
| 오브제 영상 | `input/object/object_line_1.mp4` | 검은 배경의 오브제 영상입니다. GridModel은 검은 영역을 비우고 오브제 실루엣 안에서만 셀룰러 오토마타를 적용합니다. |
| 음악 | `input/sound/` | `.wav`, `.mp3`, `.m4a`, `.aac`, `.flac`, `.ogg` 지원. 여러 파일이 있으면 파일명순 첫 번째 파일을 사용하므로 사용할 음악 하나만 둡니다. |

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

배경 영상이 있어도 두 JSON 파일이 빠지면 실행되지 않습니다. 이 두 JSON의 장면 순서와 배경 영상에서 추출되는 네 장면의 순서를 맞춰 주세요.

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
2. `input/background/`의 배경 영상에서 프레임 4장을 추출하고 `scenes.json`, `dream_scenes.json`과 함께 DreamModel의 기존 입력 실행 옵션으로 전달합니다.
3. DreamModel이 장면 감정과 음악을 사용해 배경 영상을 렌더링합니다.
4. GridModel이 `input/object/object_line_1.mp4`의 오브제 실루엣 안에 CA 효과를 적용해 검은 바탕의 오브제 레이어를 만듭니다.
5. DreamModel 배경과 입력 배경 영상을 혼합하고, GridModel 오브제를 합성합니다. 최종 영상의 음악은 `input/sound/`에서 선택된 곡입니다.

최종 영상:

```text
output/team4_output.mp4
```

최종 출력은 최대 300초이며, DreamModel과 GridModel 중간 영상은 합성이 성공하면 삭제됩니다. 실행 도중 오류가 나면 원인 확인을 위해 중간 결과가 `output/`에 남을 수 있습니다. DreamModel이 별도로 저장하는 검수용 자료가 있다면 같은 `output/` 폴더에서 확인할 수 있습니다.

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
