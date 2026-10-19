# Team 4 영상 생성 안내

이 프로젝트는 DreamModel로 배경을 만들고 GridModel로 오브제 영상을 만든 뒤, 두 레이어를 합성해 최종 영상을 생성합니다.

## 실행 환경

- Windows 10/11 64비트
- Python 3.12 64비트
- NVIDIA GPU 권장
- 인터넷 연결은 최초 패키지 설치 때 필요합니다.

DreamModel은 PyTorch를 사용합니다. CUDA를 사용할 수 있는 PyTorch가 설치되어 있으면 GPU를 자동으로 선택합니다. GPU가 없거나 CUDA가 활성화되지 않으면 CPU로 실행되며 렌더링에 오래 걸릴 수 있습니다.

## 입력 파일

아래 파일을 준비합니다.

| 용도 | 위치 | 조건 |
|---|---|---|
| 오브제 영상 | `input/object/object_line_1.mp4` | 검은 배경 권장. GridModel이 검은 영역을 제거해 배경에 합성합니다. |
| 음악 | `input/sound/` | WAV, MP3, M4A, AAC, FLAC, OGG 지원. 여러 파일이 있으면 이름순 첫 번째 파일을 사용하므로 음악은 하나만 두는 것을 권장합니다. |

DreamModel 배경은 `DreamModel/configs/scenarios/1_놀람공포중립공포/`의 장면 이미지와 설정을 사용합니다. 현재 통합 실행은 이 배경 설정으로 고정되어 있습니다. `input/background/`에 둔 MP4는 현재 `main.py`에서 입력으로 사용하지 않습니다.

## 최초 설치

PowerShell에서 `Capstone2/team4` 폴더로 이동합니다. Python 3.12가 설치되어 있지 않으면 먼저 Python 3.12 64비트를 설치한 뒤 PowerShell을 다시 엽니다.

아래 명령을 한 줄씩 실행합니다.

```powershell
py --list
py -3.12 -m venv .\DreamModel\.venv
.\DreamModel\.venv\Scripts\python.exe -m pip install --upgrade pip
```

### NVIDIA GPU 사용

```powershell
.\DreamModel\.venv\Scripts\python.exe -m pip install "torch==2.14.1+cu126" --index-url https://download.pytorch.org/whl/cu126 --extra-index-url https://pypi.org/simple
.\DreamModel\.venv\Scripts\python.exe -m pip install opencv-python numpy imageio-ffmpeg
```

GPU 사용 여부를 확인합니다.

```powershell
.\DreamModel\.venv\Scripts\python.exe -c "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'GPU 미사용')"
```

`True`와 GPU 이름이 나오면 CUDA를 사용할 수 있습니다.

### NVIDIA GPU가 없는 경우

```powershell
.\DreamModel\.venv\Scripts\python.exe -m pip install torch opencv-python numpy imageio-ffmpeg
```

이 설치는 CPU로 렌더링합니다. 실행 방법은 같지만 완료까지 훨씬 오래 걸릴 수 있습니다.

## 실행

현재 위치가 `Capstone2/team4`인지 확인한 다음 실행합니다.

```powershell
py .\main.py
```

통합 실행 순서:

1. `input/sound/`에서 음악을 선택합니다.
2. DreamModel이 고정된 장면 설정으로 음악이 포함된 배경 영상을 렌더링합니다.
3. GridModel이 `input/object/object_line_1.mp4`에 오브제 CA를 적용합니다.
4. 오브제와 배경을 합성하고 최종 영상을 저장합니다.

## 결과물

최종 영상은 다음 위치에 생성됩니다.

```text
output/team4_output.mp4
```

DreamModel은 검수용 장면 흐름 이미지, 원본 대비 이미지와 JSON 보고서도 `output/`에 저장합니다. 배경·오브제 중간 영상은 최종 합성이 성공하면 정리됩니다. 실행이 중간에 실패하면 디버깅을 위해 중간 영상이 남을 수 있습니다.

## 공유할 때

`DreamModel/.venv/`는 공유하지 않습니다. 각 팀원이 위 설치 명령으로 자기 PC에 가상환경을 만듭니다. 가상환경에는 PyTorch와 PC별 실행 파일이 들어 있어 용량이 크고 다른 컴퓨터에서 그대로 사용할 수 없습니다.

입력 음악·영상과 최종 MP4는 코드와 별도로 공유 권한을 확인합니다. `.venv`, `__pycache__`, `*.pyc`는 소스 공유본에서 제외합니다.

## 문제 해결

- `No module named 'torch'`: Python 3.12 가상환경에 패키지를 설치했는지 확인합니다.
- CUDA 확인 결과가 `False`: CPU 모드로 실행됩니다. CUDA용 PyTorch 설치 명령을 다시 실행하고 GPU 드라이버가 정상인지 확인합니다.
- `input/sound`에 음악이 없다는 오류: 지원되는 음악 파일을 해당 폴더에 넣습니다.
- 입력 영상 오류: `input/object/object_line_1.mp4`의 파일명과 위치를 확인합니다.
- FFmpeg 오류: 가상환경에서 `imageio-ffmpeg`가 설치되어 있는지 확인합니다.