# 관객 감정 추출 파이프라인 (1단계: 기억추출)

캡스톤 프로젝트 1단계 - MediaPipe + DeepFace 기반 관객 표정 감정 추출 프로토타입

## 폴더 구조

```
emotion_capture/
├── requirements.txt
├── capture/          # 원본 영상 저장 (git에는 올리지 않는 걸 추천)
├── output/           # 분석 결과 csv 저장
└── src/
    ├── step1_test_camera.py       # DroidCam 연결 테스트
    ├── step2_face_detect_test.py  # MediaPipe 얼굴 검출 확인
    └── step3_emotion_pipeline.py  # 크롭 + 감정분류 + csv 저장 (메인)
```

## 실행 순서

### 0. 환경 준비
```bash
python -m venv venv
source venv/bin/activate        # Windows는 venv\Scripts\activate
pip install -r requirements.txt
```

### 1. DroidCam USB 연결 후 인덱스 확인
```bash
cd src
python step1_test_camera.py
```
화면에 폰 영상이 뜨면 `y`를 눌러 인덱스를 확인하세요. 이 숫자를 이후 명령어의 `--camera` 값으로 사용합니다.

### 2. 얼굴 검출 테스트 (몇 명까지 잡히는지 확인)
```bash
python step2_face_detect_test.py --camera 0
```
검출 수가 목표(20명)보다 많이 부족하면 카메라 거리/화각을 먼저 조정하세요.

### 3. 샘플 영상으로 전체 파이프라인 리허설 (8단계)
실제 20명을 모으기 전에, 짧게 찍은 샘플 영상으로 먼저 테스트:
```bash
python step3_emotion_pipeline.py --video ../capture/sample.mp4 --output ../output/rehearsal.csv --sample_rate 10
```

### 4. 실제 세션 (실시간 카메라)
```bash
python step3_emotion_pipeline.py --camera 0 --output ../output/session1.csv --sample_rate 10
```
`q`를 누르면 종료되고 결과가 csv로 저장됩니다.

## 결과 csv 형식

| timestamp_sec | face_id | emotion_en | emotion_kr | confidence |
|---|---|---|---|---|
| 3.21 | 0 | happy | 기쁨 | 82.4 |
| 3.21 | 1 | neutral | 중립 | 65.1 |

이 데이터가 이후 "N명 이상이 같은 시간대에 같은 감정으로 수렴하는 구간" 집계 및
내레이션/사운드 타임라인 매칭의 원본이 됩니다.

## 알아둘 점

- DeepFace 기본 모델은 7가지 감정만 지원 (`angry, disgust, fear, happy, sad, surprise, neutral`).
  8가지 감정 분류 기준이 확정되면 `step3_emotion_pipeline.py`의 `EMOTION_MAP`을 수정하세요.
- `--sample_rate`는 부하 조절용입니다. 값이 클수록 분석 빈도가 낮아져 가벼워지지만
  타임라인 해상도가 떨어집니다. 카메라 FPS와 하드웨어 성능을 보고 조정하세요.
- `SimpleTracker`는 좌석이 고정된 상황을 가정한 단순 트래커입니다.
  관객이 자유롭게 움직이는 세팅이면 더 정교한 트래킹(SORT 등)이 필요합니다.
