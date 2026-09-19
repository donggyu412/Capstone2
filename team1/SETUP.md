# 환경 세팅 가이드 (관객 감정 추출 - 1단계)

이 문서는 처음 세팅할 팀원을 위한 가이드입니다. 실제로 세팅하면서 겪었던
문제와 해결법을 그대로 정리했으니, 순서대로 따라가면 됩니다.

---

## 0. 준비물

- Python 3.10 (다른 3.x 버전도 대체로 되지만, 3.10 기준으로 테스트됨)
- VS Code (권장) + Python 확장
- 안드로이드 스마트폰 (관객 촬영용, DroidCam 앱 설치)
- USB 케이블 (데이터 전송 지원되는 케이블 — 충전 전용 케이블은 안 됨)

---

## 1. 프로젝트 열기

1. 압축 풀고 VS Code에서 `File → Open Folder`로 `emotion_capture` 폴더 전체 열기
2. VS Code Extensions에서 "Python" (Microsoft) 확장 설치 확인

---

## 2. 가상환경 세팅

터미널(`Terminal → New Terminal`)에서:

```powershell
python -m venv venv
```

**활성화 (Windows / PowerShell):**
```powershell
.\venv\Scripts\Activate.ps1
```

> ⚠️ **실행 정책 에러가 뜨면** ("이 시스템에서 스크립트를 실행할 수 없으므로..."):
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> ```
> `Y` 입력 후 다시 활성화 명령어 실행.

활성화되면 프롬프트 앞에 `(venv)`가 붙습니다. **이후 모든 명령어는 이 상태에서 실행하세요.**

---

## 3. 라이브러리 설치

```powershell
pip install -r requirements.txt
```

DeepFace가 TensorFlow까지 같이 설치해서 1~2GB 정도 되고 몇 분 걸릴 수 있습니다.

**설치 확인:**
```powershell
python -c "import cv2, mediapipe, deepface; print('ALL OK')"
```

### 겪을 수 있는 에러 1: `AttributeError: module 'mediapipe' has no attribute 'solutions'`

→ 무시하세요. 이 프로젝트 코드는 최신 mediapipe의 새 API(Tasks API)를 쓰도록 이미
수정되어 있어서 `mp.solutions`를 아예 사용하지 않습니다. requirements.txt에 명시된
대로 설치했다면 이 문제는 애초에 발생하지 않습니다.

### 겪을 수 있는 에러 2: `ValueError: You have tensorflow ... and this requires tf-keras`

→ requirements.txt에 이미 `tf-keras`가 포함되어 있어서 정상 설치하면 발생하지 않습니다.
혹시 뜨면: `pip install tf-keras`

---

## 4. 얼굴 검출 모델 파일 다운로드 (필수)

브라우저로 아래 링크를 열어 `.tflite` 파일을 다운로드하세요:

https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite

다운로드한 파일을 프로젝트의 `models` 폴더 안에 넣으세요:
```
emotion_capture/models/blaze_face_short_range.tflite
```

(mediapipe의 새 API는 이 모델 파일을 직접 로드해서 얼굴을 찾습니다. 파일이 없으면
스크립트가 친절하게 "모델 파일을 찾을 수 없습니다" 에러를 냅니다.)

---

## 5. 카메라 연결 (DroidCam, USB)

1. 폰: Play Store에서 "DroidCam" 앱 설치
2. 노트북: [dev47apps.com](https://www.dev47apps.com)에서 DroidCam Client(Windows) 설치
3. 폰을 USB로 연결
4. **폰에서 USB 연결 모드를 "파일 전송(MTP)"로 변경** (기본값 "충전만"이면 PC가 인식 못 함 — 연결 시 알림 바에서 변경)
5. **폰 설정 → 개발자 옵션 → USB 디버깅 ON**
   (개발자 옵션이 안 보이면: 설정 → 휴대폰 정보 → 빌드번호 7번 연속 탭)
6. 케이블 다시 꽂았을 때 폰에 뜨는 "USB 디버깅을 허용하시겠습니까?" 팝업에서 **허용**
7. DroidCam Client 실행 → "Connect over USB" → 폰 화면이 노트북에 뜨면 성공

**"No devices detected"가 뜨면** → 위 4~6번(파일 전송 모드, USB 디버깅, 허용 팝업)을
순서대로 다시 확인하세요. 대부분 이 중 하나를 놓쳐서 생깁니다.

---

## 6. 실행 순서

```powershell
cd src

# 6-1. DroidCam이 어느 인덱스인지 확인 (창이 여러 개 뜨며, 폰 화면 보이면 y)
python step1_test_camera.py

# 6-2. 얼굴 검출 확인 (아래 --camera 값은 6-1에서 확인한 번호로)
python step2_face_detect_test.py --camera 0

# 6-3. 감정 분류까지 포함된 메인 파이프라인
python step3_emotion_pipeline.py --camera 0 --output ../output/test1.csv --sample_rate 10
```

`step3` 실행 화면에 얼굴 박스 + `ID0: happy (76%)` 같은 라벨이 뜨고, `q`로 종료하면
`output/` 폴더에 csv가 저장됩니다.

---

## 결과 csv 형식

| timestamp_sec | face_id | emotion_en | emotion_kr | confidence |
|---|---|---|---|---|
| 3.21 | 0 | happy | 기쁨 | 82.4 |

---

## 알아둘 점 (팀 내 공유용)

- **8가지 감정 분류 기준 미확정**: 지금 코드는 DeepFace 기본 7가지 감정
  (`angry, disgust, fear, happy, sad, surprise, neutral`)을 그대로 씁니다.
  기준이 정해지면 `step3_emotion_pipeline.py`의 `EMOTION_MAP`을 수정하면 됩니다.
- **얼굴 트래킹은 단순한 방식**: 좌석이 고정된 상황을 가정한 거리 기반 트래킹입니다
  (`SimpleTracker` 클래스). 관객이 자유롭게 움직이면 더 정교한 트래킹이 필요합니다.
- **--sample_rate로 부하 조절**: 값이 작을수록 감정이 자주 갱신되지만 CPU 부하가
  커집니다. 노트북 성능에 따라 5~15 사이에서 조절하세요.
- **DeepFace는 첫 실행 시 모델 가중치를 자동 다운로드**합니다 (`~/.deepface` 폴더 생성).
  인터넷 연결이 필요하고, 처음 한 번만 시간이 걸립니다.
