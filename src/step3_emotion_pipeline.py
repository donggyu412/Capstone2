"""
[6~7단계] 얼굴 크롭 + DeepFace 감정 분류 + 시간축 데이터 저장

목적:
- MediaPipe(Tasks API)로 검출한 얼굴들을 크롭
- 각 얼굴을 DeepFace로 감정 분류
- (타임스탬프, 얼굴ID, 감정라벨, 확률)을 csv로 누적 저장
- 프레임 간 얼굴에 대략적인 ID를 부여하는 간단한 트래킹 포함
  (좌석 고정 세팅을 가정 - 얼굴 중심 좌표가 가장 가까운 기존 얼굴에 매칭)

사용법:
    python step3_emotion_pipeline.py --camera 0 --output ../output/session1.csv
    python step3_emotion_pipeline.py --video ../capture/sample.mp4 --output ../output/rehearsal.csv --interval 10

주의:
- DeepFace 기본 모델은 7가지 감정(angry, disgust, fear, happy, sad, surprise, neutral)만 지원합니다.
  8가지 감정 분류 기준이 정해지면 EMOTION_MAP에서 매핑을 조정하세요.
- 얼굴 검출은 매 프레임 수행하고, DeepFace 감정 분석만 --interval 초마다 실행합니다.
  분석 사이 프레임에서는 마지막으로 분석된 감정을 계속 표시합니다.
- detector_backend="skip"으로 DeepFace의 자체 얼굴 검출을 끕니다 (이미 MediaPipe로 찾았으므로).
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

MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "models", "blaze_face_short_range.tflite")


def play_narration_video(path):
    """
    관객에게 보여줄 내레이션/사운드 영상을 OS 기본 플레이어로 재생.
    Windows: os.startfile, Mac: open, Linux: xdg-open
    """
    if not os.path.exists(path):
        print(f"[경고] 재생할 영상 파일을 찾을 수 없습니다: {path}")
        return

    if sys.platform.startswith("win"):
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])

EMOTION_MAP = {
    "angry": "분노",
    "disgust": "혐오",
    "fear": "공포",
    "happy": "기쁨",
    "sad": "슬픔",
    "surprise": "놀람",
    "neutral": "중립",
}


def build_detector():
    if not os.path.exists(MODEL_PATH):
        raise FileNotFoundError(
            f"모델 파일을 찾을 수 없습니다: {MODEL_PATH}\n"
            "blaze_face_short_range.tflite를 models 폴더에 넣어주세요."
        )
    base_options = mp_python.BaseOptions(model_asset_path=MODEL_PATH)
    options = vision.FaceDetectorOptions(
        base_options=base_options,
        running_mode=vision.RunningMode.IMAGE,
        min_detection_confidence=0.5,
    )
    return vision.FaceDetector.create_from_options(options)


class SimpleTracker:
    """
    좌석이 고정되어 있다는 가정 하에, 얼굴 중심 좌표가 가장 가까운
    기존 트랙에 매칭하는 아주 단순한 트래커.
    정교한 트래킹이 필요하면 SORT/DeepSORT 등으로 교체하세요.
    """

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
    bbox = detection.bounding_box  # Tasks API: 픽셀 단위 (origin_x, origin_y, width, height)

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


def analyze_emotion(face_crop):
    try:
        result = DeepFace.analyze(
            face_crop,
            actions=["emotion"],
            enforce_detection=False,
            detector_backend="skip",  # 이미 MediaPipe로 얼굴을 찾았으므로 DeepFace가 다시 찾지 않도록 함
            silent=True,
        )
        if isinstance(result, list):
            result = result[0]
        dominant = result["dominant_emotion"]
        confidence = result["emotion"][dominant]
        return dominant, confidence
    except Exception as e:
        print(f"[emotion analysis failed] {e}")
        return None, None


def main(source, output_path, interval_sec, narration_path=None):
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        print(f"입력 소스를 열 수 없습니다: {source}")
        return

    tracker = SimpleTracker()
    detector = build_detector()

    last_emotion = {}  # face_id -> (emotion_en, confidence)
    last_analysis_time = -999.0  # 마지막으로 감정 분석을 실행한 시각(초)

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp_sec", "face_id", "emotion_en", "emotion_kr", "confidence"])

        # 내레이션 영상이 지정되어 있으면 여기서 재생 시작하고, 그 순간을 타임스탬프 0초로 잡음
        if narration_path:
            print(f"[재생 시작] {narration_path}")
            play_narration_video(narration_path)

        start_time = time.time()

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            timestamp_sec = round(time.time() - start_time, 2)

            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
            result = detector.detect(mp_image)

            # 마지막 분석 후 interval_sec 이상 지났으면 이번 프레임에서 분석 실행
            do_analysis = (timestamp_sec - last_analysis_time) >= interval_sec
            if do_analysis:
                last_analysis_time = timestamp_sec

            if result.detections:
                centroids = []
                crops = []
                boxes = []

                for detection in result.detections:
                    face_crop, centroid, box = crop_face(frame, detection)
                    if face_crop.size == 0:
                        continue
                    centroids.append(centroid)
                    crops.append(face_crop)
                    boxes.append(box)

                face_ids = tracker.update(centroids)

                for face_id, face_crop, box in zip(face_ids, crops, boxes):
                    if do_analysis:
                        emotion_en, confidence = analyze_emotion(face_crop)
                        if emotion_en is not None:
                            last_emotion[face_id] = (emotion_en, confidence)
                            emotion_kr = EMOTION_MAP.get(emotion_en, emotion_en)
                            writer.writerow([timestamp_sec, face_id, emotion_en, emotion_kr, round(confidence, 1)])

                    x1, y1, x2, y2 = box
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)

                    if face_id in last_emotion:
                        emotion_en, confidence = last_emotion[face_id]
                        label = f"ID{face_id}: {emotion_en} ({confidence:.0f}%)"
                        cv2.putText(frame, label, (x1, max(20, y1 - 10)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

            cv2.imshow("Emotion Pipeline (press q to quit)", frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    detector.close()
    cap.release()
    cv2.destroyAllWindows()
    print(f"\nDone. Saved to: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--camera", type=int, help="실시간 카메라 인덱스")
    parser.add_argument("--video", type=str, help="저장된 영상 파일 경로")
    parser.add_argument("--output", type=str, default="../output/session.csv")
    parser.add_argument("--interval", type=float, default=10.0,
                        help="감정 분석을 몇 초 간격으로 실행할지 (기본 10초)")
    parser.add_argument("--narration", type=str, default=None,
                        help="관객에게 자동 재생할 내레이션/사운드 영상 경로 (선택)")
    args = parser.parse_args()

    if args.video:
        source = args.video
    elif args.camera is not None:
        source = args.camera
    else:
        source = 0

    main(source, args.output, args.interval, args.narration)
