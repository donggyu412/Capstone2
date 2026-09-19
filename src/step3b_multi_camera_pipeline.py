"""
[6~7단계 - 멀티 카메라 버전] 노트북 내장캠 + 폰(DroidCam) 등 여러 카메라를 동시에 사용

목적:
- 카메라 하나의 화각 한계를 넘어, 여러 대의 카메라로 더 많은 관객을 커버
- 각 카메라에서 독립적으로 얼굴 검출 + 감정 분류를 수행
- 결과 csv에 어느 카메라에서 잡힌 얼굴인지 구분하는 'source' 컬럼 추가
- face_id는 카메라별로 별도 네임스페이스 사용 (예: cam0_0, cam1_0 는 서로 다른 사람)

사용법:
    # 노트북 내장캠(보통 0번)과 DroidCam(예: 1번)을 동시에 사용
    python step3b_multi_camera_pipeline.py --sources 0 1 --output ../output/multi_test.csv --interval 10

    # 내레이션 영상을 관객에게 자동 재생하면서 동시에 촬영
    python step3b_multi_camera_pipeline.py --sources 0 1 --output ../output/multi_test.csv --narration ../capture/narration_video.mp4

    # 카메라 3대도 가능
    python step3b_multi_camera_pipeline.py --sources 0 1 2 --output ../output/multi_test.csv

주의:
- 각 소스 번호는 step1_test_camera.py로 미리 확인해두세요 (어떤 카메라가 몇 번인지).
- 카메라마다 별도 창이 뜹니다. 아무 창에서나 'q'를 누르면 전체 종료됩니다.
- 노트북 성능에 따라 카메라 수가 늘수록 느려질 수 있습니다. 느려지면 --interval을 늘리세요.
"""

import argparse
import csv
import math
import os
import subprocess
import sys
import time

import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision
from deepface import DeepFace

MODEL_FILES = {
    "short": "blaze_face_short_range.tflite",   # 근거리(~2m) 최적화, 가벼움
    "full": "blaze_face_full_range.tflite",     # 원거리까지 대응, 약간 무거움
}


def play_narration_video(path):
    """
    관객에게 보여줄 내레이션/사운드 영상을 OS 기본 플레이어로 재생.
    Windows: os.startfile, Mac: open, Linux: xdg-open
    """
    abs_path = os.path.abspath(path)  # 상대경로를 절대경로로 변환 (os.startfile이 상대경로를 못 찾는 경우 대비)

    if not os.path.exists(abs_path):
        print(f"[경고] 재생할 영상 파일을 찾을 수 없습니다: {abs_path}")
        return

    if sys.platform.startswith("win"):
        os.startfile(abs_path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", abs_path])
    else:
        subprocess.Popen(["xdg-open", abs_path])

EMOTION_MAP = {
    "angry": "분노",
    "disgust": "혐오",
    "fear": "공포",
    "happy": "기쁨",
    "sad": "슬픔",
    "surprise": "놀람",
    "neutral": "중립",
}


def build_detector(model_variant="full"):
    model_filename = MODEL_FILES.get(model_variant, MODEL_FILES["full"])
    model_path = os.path.join(os.path.dirname(__file__), "..", "models", model_filename)

    if not os.path.exists(model_path):
        raise FileNotFoundError(
            f"모델 파일을 찾을 수 없습니다: {model_path}\n"
            f"{model_filename}을 models 폴더에 넣어주세요."
        )
    base_options = mp_python.BaseOptions(model_asset_path=model_path)
    options = vision.FaceDetectorOptions(
        base_options=base_options,
        running_mode=vision.RunningMode.IMAGE,
        min_detection_confidence=0.5,
    )
    return vision.FaceDetector.create_from_options(options)


class SimpleTracker:
    def __init__(self, max_distance=80):
        self.next_id = 0
        self.tracks = {}
        self.max_distance = max_distance

    def update(self, centroids):
        assigned_ids = []
        used_ids = set()

        for cx, cy in centroids:
            best_id = None
            best_dist = self.max_distance

            for track_id, (tx, ty) in self.tracks.items():
                if track_id in used_ids:
                    continue
                dist = math.hypot(cx - tx, cy - ty)
                if dist < best_dist:
                    best_dist = dist
                    best_id = track_id

            if best_id is None:
                best_id = self.next_id
                self.next_id += 1

            self.tracks[best_id] = (cx, cy)
            used_ids.add(best_id)
            assigned_ids.append(best_id)

        return assigned_ids


def crop_face(frame, detection, padding_ratio=0.2):
    h, w, _ = frame.shape
    bbox = detection.bounding_box

    x1 = bbox.origin_x
    y1 = bbox.origin_y
    bw = bbox.width
    bh = bbox.height

    pad_x = int(bw * padding_ratio)
    pad_y = int(bh * padding_ratio)

    x1 = max(0, x1 - pad_x)
    y1 = max(0, y1 - pad_y)
    x2 = min(w, x1 + bw + 2 * pad_x)
    y2 = min(h, y1 + bh + 2 * pad_y)

    face_crop = frame[y1:y2, x1:x2]
    centroid = (x1 + (x2 - x1) // 2, y1 + (y2 - y1) // 2)
    return face_crop, centroid, (x1, y1, x2, y2)


_emotion_call_times_ms = []  # 얼굴 1명 분석에 걸린 시간(ms)들을 기록해두는 리스트


def analyze_emotion(face_crop, exclude_neutral=True):
    _t0 = time.time()  # 시작 시각 기록
    try:
        result = DeepFace.analyze(
            face_crop,
            actions=["emotion"],
            enforce_detection=False,
            detector_backend="skip",
            silent=True,
        )
        if isinstance(result, list):
            result = result[0]

        scores = dict(result["emotion"])  # {"angry": 2.1, "neutral": 42.0, ...}

        if exclude_neutral:
            scores.pop("neutral", None)  # 중립을 후보에서 아예 제거

        if not scores:
            return None, None

        dominant = max(scores, key=scores.get)
        confidence = scores[dominant]
        return dominant, confidence
    except Exception as e:
        print(f"[emotion analysis failed] {e}")
        return None, None
    finally:
        elapsed_ms = (time.time() - _t0) * 1000
        _emotion_call_times_ms.append(elapsed_ms)
        print(f"[감정분석 소요시간] {elapsed_ms:.1f} ms")


class CameraSource:
    """카메라 한 대에 대한 상태(캡처, 트래커, 마지막 감정, 창 이름)를 묶어서 관리"""

    def __init__(self, index, token):
        self.index = index
        self.token = token  # 예: "0" 또는 "cam1"
        self.label = f"cam{index}"
        self.cap = cv2.VideoCapture(token)
        self.tracker = SimpleTracker()
        self.last_emotion = {}  # local_face_id -> (emotion_en, confidence)
        self.last_analysis_time = -999.0
        self.window_name = f"Source {index}: {token}"

    def is_opened(self):
        return self.cap.isOpened()

    def release(self):
        self.cap.release()
        cv2.destroyWindow(self.window_name) if cv2.getWindowProperty(
            self.window_name, cv2.WND_PROP_VISIBLE
        ) >= 1 else None


def main(source_tokens, output_path, interval_sec, narration_path=None, model_variant="full"):
    sources = []
    for idx, token in enumerate(source_tokens):
        # 숫자면 카메라 인덱스로, 아니면 파일 경로로 취급
        cam_token = int(token) if str(token).isdigit() else token
        cs = CameraSource(idx, cam_token)
        if not cs.is_opened():
            print(f"[경고] 소스를 열 수 없습니다: {token} (건너뜁니다)")
            continue
        sources.append(cs)

    if not sources:
        print("열 수 있는 카메라/영상이 하나도 없습니다.")
        return

    detector = build_detector(model_variant)

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp_sec", "source", "face_id", "emotion_en", "emotion_kr", "confidence"])

        # 내레이션 영상이 지정되어 있으면 여기서 재생 시작하고, 그 순간을 타임스탬프 0초로 잡음
        if narration_path:
            print(f"[재생 시작] {narration_path}")
            play_narration_video(narration_path)

        start_time = time.time()

        try:
            while True:
                any_frame_read = False
                quit_requested = False

                for cs in sources:
                    ret, frame = cs.cap.read()
                    if not ret:
                        continue
                    any_frame_read = True

                    timestamp_sec = round(time.time() - start_time, 2)

                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
                    result = detector.detect(mp_image)

                    do_analysis = (timestamp_sec - cs.last_analysis_time) >= interval_sec
                    if do_analysis:
                        cs.last_analysis_time = timestamp_sec

                    if result.detections:
                        centroids, crops, boxes = [], [], []
                        for detection in result.detections:
                            face_crop, centroid, box = crop_face(frame, detection)
                            if face_crop.size == 0:
                                continue
                            centroids.append(centroid)
                            crops.append(face_crop)
                            boxes.append(box)

                        local_ids = cs.tracker.update(centroids)

                        for local_id, face_crop, box in zip(local_ids, crops, boxes):
                            global_face_id = f"{cs.label}_{local_id}"

                            if do_analysis:
                                emotion_en, confidence = analyze_emotion(face_crop)
                                if emotion_en is not None:
                                    cs.last_emotion[local_id] = (emotion_en, confidence)
                                    emotion_kr = EMOTION_MAP.get(emotion_en, emotion_en)
                                    writer.writerow([
                                        timestamp_sec, cs.label, global_face_id,
                                        emotion_en, emotion_kr, round(confidence, 1),
                                    ])

                            x1, y1, x2, y2 = box
                            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)

                            if local_id in cs.last_emotion:
                                emotion_en, confidence = cs.last_emotion[local_id]
                                label = f"{global_face_id}: {emotion_en} ({confidence:.0f}%)"
                                cv2.putText(frame, label, (x1, max(20, y1 - 10)),
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

                    cv2.imshow(cs.window_name, frame)

                if not any_frame_read:
                    break  # 모든 소스가 끝남 (영상 파일 재생 종료 등)

                if cv2.waitKey(1) & 0xFF == ord('q'):
                    quit_requested = True

                if quit_requested:
                    break
        finally:
            for cs in sources:
                cs.cap.release()
            cv2.destroyAllWindows()

    print(f"\nDone. Saved to: {output_path}")

    # 감정분석 처리 시간 통계 요약
    if _emotion_call_times_ms:
        n = len(_emotion_call_times_ms)
        avg = sum(_emotion_call_times_ms) / n
        print(f"\n[감정분석 속도 요약] 총 {n}회 호출")
        print(f"  평균: {avg:.1f} ms   최소: {min(_emotion_call_times_ms):.1f} ms   최대: {max(_emotion_call_times_ms):.1f} ms")
        print(f"  참고: 한 프레임에 동시에 있는 얼굴 수만큼 이 시간이 곱해집니다.")
        print(f"        예) 이 평균값 x 20명 = 한 번의 --interval 주기에 필요한 최소 시간")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", nargs="+", required=True,
                        help="카메라 인덱스 또는 영상 경로를 공백으로 구분해서 나열 (예: --sources 0 1)")
    parser.add_argument("--output", type=str, default="../output/multi_session.csv")
    parser.add_argument("--interval", type=float, default=10.0,
                        help="감정 분석을 몇 초 간격으로 실행할지 (기본 10초)")
    parser.add_argument("--narration", type=str, default=None,
                        help="관객에게 자동 재생할 내레이션/사운드 영상 경로 (선택)")
    parser.add_argument("--model", type=str, default="full", choices=["short", "full"],
                        help="얼굴 검출 모델: short(근거리, 가벼움) / full(원거리 대응, 기본값)")
    args = parser.parse_args()

    main(args.sources, args.output, args.interval, args.narration, args.model)
