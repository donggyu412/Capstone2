# GridModel 사용 방법

GridModel은 `storyboard`의 배경 이미지, 스토리 JSON, 사운드와 `objects`의 오브제 PNG를 읽어  
**배경 + 오브제에 Cellular Automata(CA) 효과를 적용해 1920×1080 / 30fps 영상**을 생성합니다.

## 1. 필요한 프로그램

### Python
Python 3.10 이상을 권장합니다.

필요 라이브러리 설치:

```powershell
py -m pip install numpy opencv-python librosa soundfile scipy tqdm
```

### FFmpeg
최종 영상에 사운드를 합치기 위해 필요합니다.

Windows:

```powershell
winget install Gyan.FFmpeg
```

설치 후에는 터미널을 새로 열어주세요.

---

## 2. 폴더 구조

```text
team4/
├─ GridModel/
│  ├─ config.py
│  └─ pythonimagemodel.py
│
├─ input/
│  ├─ objects/
│  │  ├─ scene_01/
│  │  │  ├─ obj_1_....png
│  │  │  ├─ obj_2_....png
│  │  │  └─ ...
│  │  ├─ scene_02/
│  │  ├─ scene_03/
│  │  └─ scene_04/
│  │
│  └─ storyboard/
│     ├─ scene_01.png
│     ├─ scene_02.png
│     ├─ scene_03.png
│     ├─ scene_04.png
│     ├─ scenes.json
│     ├─ dream_scenes.json
│     └─ music.wav
│
└─ Videos/
```

- 배경은 `scene_01.png ~ scene_04.png`
- 오브제는 각 `scene_0N` 폴더 안에 넣습니다.
- 오브제 순서는 `dream_scenes.json`의 `objects` 배열 순서를 따릅니다.
- 오브제 PNG는 **투명 배경(RGBA)** 사용을 권장합니다.
- 사운드는 `storyboard` 폴더에 넣습니다. (`wav`, `mp3`, `ogg`, `flac`, `m4a` 지원)

---

## 3. 실행 방법

`team4` 폴더에서 터미널을 열고:

```powershell
py GridModel/pythonimagemodel.py
```

또는 `GridModel` 폴더 안에서 실행한다면:

```powershell
py pythonimagemodel.py
```

---

## 4. 결과물

기본 설정에서는 결과가 `Videos` 폴더에 생성됩니다.

```text
gridmodel_v2_silent.mp4
gridmodel_v2_final.mp4
gridmodel_v2_log.txt
```

- `silent.mp4` : 영상만 있는 파일
- `final.mp4` : 사운드가 합쳐진 최종 영상
- `log.txt` : Scene / Story / CA / Object 진행 로그

저장 폴더를 바꾸고 싶다면 `config.py`의 아래 값을 수정하면 됩니다.

```python
OUT_DIR = ROOT / "Videos"
```

예를 들어 `output` 폴더를 사용하려면:

```python
OUT_DIR = ROOT / "output"
```

---

## 5. 기본 작품 설정

현재 기본 설정:

- Scene 수: **4개**
- Scene당 시간: **75초**
- 총 상영시간: **5분**
- 해상도: **1920×1080**
- 프레임: **30fps**
- Story: `dream_scenes.json`
- 오브제: Scene별 순차 표시
- 배경과 오브제 모두 Story / Sound / Cellular Automata의 영향을 받음

대부분의 작품 설정은 `GridModel/config.py`에서 변경할 수 있습니다.
