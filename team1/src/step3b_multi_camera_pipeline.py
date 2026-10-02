# -*- coding: utf-8 -*-
"""
[6~7단계 - 멀티 카메라 + 배치/디바이스 선택 버전]
  노트북 내장캠 + 폰(DroidCam) + 영상 파일 등 여러 소스를 동시에 사용

[이 버전에서 달라진 점]
  1. --device {cpu, gpu, auto} 로 CPU/GPU를 선택할 수 있습니다.
     - cpu : TensorFlow가 GPU를 아예 못 보게 숨깁니다 (CUDA_VISIBLE_DEVICES=-1)
     - gpu : GPU를 그대로 사용합니다 (GPU가 없거나 드라이버 문제면 TensorFlow가 자동으로 CPU로 넘어갑니다)
     - auto: 아무것도 건드리지 않고 TensorFlow 기본 동작에 맡깁니다 (기본값)
  2. 감정 분석을 "한 명씩 DeepFace.analyze() 호출"이 아니라, 한 프레임에서 검출된
     얼굴 전체를 "하나의 배치"로 묶어 모델에 한 번만 넣습니다 (진짜 배치 추론).
     - DeepFace.analyze()에 리스트를 넣어도 내부적으로는 한 장씩 반복 호출하는 구조라
       배치 효과가 없습니다. 이 버전은 DeepFace 내부의 Emotion 모델을 직접 가져와
       model.predict(이미지_리스트)로 한 번에 넘깁니다 — GPU 배치 가속은 이 경로에서만 제대로 나옵니다.
     - 내부 API(모델 직접 접근)이므로 deepface 버전이 바뀌면 깨질 수 있어, 실패 시
       자동으로 기존 방식(한 장씩 DeepFace.analyze())으로 되돌아갑니다 (--no-batch로 강제도 가능).

사용법:
    # GPU로, 배치 처리로 (기본)
    python step3b_multi_camera_pipeline.py --sources 0 1 --output ../output/multi_test.csv --device gpu

    # CPU로 강제 (gpu_test 환경이 켜져 있어도 CPU만 쓰고 싶을 때)
    python step3b_multi_camera_pipeline.py --sources 0 1 --output ../output/multi_test.csv --device cpu

    # 배치 없이 기존 방식(한 명씩)으로 비교 테스트
    python step3b_multi_camera_pipeline.py --sources 0 1 --output ../output/multi_test.csv --no-batch
"""

import argparse
import csv
import math
import os
import subprocess
import sys
import time

# ─────────────────────────────────────────────────────────
# --device 는 TensorFlow/DeepFace를 import 하기 "전에" 반영해야 효과가 있다.
# 그래서 argparse보다 먼저, sys.argv를 직접 간단히 훑어서 처리한다.
# ─────────────────────────────────────────────────────────
def _prescan_device_arg():
    if "--device" in sys.argv:
        idx = sys.argv.index("--device")
        if idx + 1 < len(sys.argv):
            return sys.argv[idx + 1]
    return "auto"


_device = _prescan_device_arg()
if _device == "cpu":
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
    print("[device] CPU로 강제 설정 (GPU 숨김)")
elif _device == "gpu":
    os.environ.pop("CUDA_VISIBLE_DEVICES", None)
    print("[device] GPU 사용 시도 (GPU가 없거나 드라이버 문제면 자동으로 CPU로 전환됨)")
else:
    print("[device] auto (TensorFlow 기본 동작)")

import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision
from deepface import DeepFace

try:
    # 내부 API: 감정 모델을 직접 가져와 진짜 배치 추론에 사용
    from deepface.modules import modeling as _deepface_modeling
    _BATCH_API_AVAILABLE = True
except ImportError:
    _BATCH_API_AVAILABLE = False

# 실제로 GPU가 잡혔는지 확인하고 알려줌 (import 이후에 확인 가능)
try:
    import tensorflow as tf
    _gpu_list = tf.config.list_physical_devices("GPU")
    if _device == "gpu" and not _gpu_list:
        print("[device] 경고: --device gpu로 설정했지만 TensorFlow가 GPU를 찾지 못했습니다. CPU로 돕니다.")
    elif _gpu_list:
        print(f"[device] TensorFlow가 인식한 GPU: {[d.name for d in _gpu_list]}")
    else:
        print("[device] TensorFlow가 GPU를 쓰지 않습니다 (CPU로 동작)")
except Exception as e:
    print(f"[device] TensorFlow GPU 확인 중 경고(무시 가능): {e}")


MODEL_FILES = {
    "short": "blaze_face_short_range.tflite",   # 근거리(~2m) 최적화, 가벼움
    "full": "blaze_face_full_range.tflite",     # 원거리까지 대응, 약간 무거움
}


def play_narration_video(path):
    abs_path = os.path.abspath(path)
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
# DeepFace 내부 EMOTION_LABELS 순서와 맞춤 (modeling 모델의 predict() 출력 인덱스 순서)
EMOTION_LABELS_ORDER = ["angry", "disgust", "fear", "happy", "sad", "surprise", "neutral"]


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


_emotion_call_times_ms = []   # 호출(또는 배치) 1회에 걸린 시간(ms)
_emotion_batch_sizes = []     # 그 호출에 포함된 얼굴 수 (배치 크기)
_emotion_model_cache = {"model": None}


def _get_emotion_model():
    """DeepFace 내부의 Emotion 모델을 직접 가져온다 (최초 1회만 로드, 이후 캐시 재사용)."""
    if _emotion_model_cache["model"] is None:
        _emotion_model_cache["model"] = _deepface_modeling.build_model(
            task="facial_attribute", model_name="Emotion"
        )
    return _emotion_model_cache["model"]


def analyze_emotion_single(face_crop, exclude_neutral=True):
    """기존 방식: 얼굴 1장을 DeepFace.analyze()로 분석 (배치 미사용 / 폴백용)."""
    _t0 = time.time()
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
        scores = dict(result["emotion"])
        if exclude_neutral:
            scores.pop("neutral", None)
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
        _emotion_batch_sizes.append(1)
        print(f"[감정분석 소요시간] {elapsed_ms:.1f} ms (1명)")


def analyze_emotion_batch(face_crops, exclude_neutral=True):
    """
    얼굴 여러 장을 한 번에 모델에 넣어 분석한다 (진짜 배치 추론).
    face_crops: BGR 얼굴 크롭 이미지의 리스트 (크기가 서로 달라도 됨 - 내부에서 통일시킴)
    반환: [(dominant_emotion_en, confidence), ...] 입력 순서와 동일한 길이의 리스트
          실패한 항목은 (None, None)
    """
    if not face_crops:
        return []

    _t0 = time.time()
    try:
        model = _get_emotion_model()

        # 모델 내부에서 np.array(리스트)로 한 번에 묶으려 하므로,
        # 크기가 제각각이면 실패한다 → 여기서 미리 동일 크기로 맞춘다.
        resized = [cv2.resize(c, (224, 224)) for c in face_crops]
        predictions = model.predict(resized)   # shape: (n, 7) — 각 행이 한 얼굴의 7개 감정 점수
        predictions = np.atleast_2d(predictions)

        results = []
        for row in predictions:
            scores = {label: float(row[i]) for i, label in enumerate(EMOTION_LABELS_ORDER)}
            if exclude_neutral:
                scores.pop("neutral", None)
            if not scores:
                results.append((None, None))
                continue
            dominant = max(scores, key=scores.get)
            total = sum(scores.values()) if exclude_neutral else float(row.sum())
            # DeepFace.analyze()와 동일하게 "후보로 남은 감정들 중 비율(%)"로 환산
            confidence = 100 * scores[dominant] / total if total > 0 else 0.0
            results.append((dominant, confidence))
        return results
    except Exception as e:
        print(f"[배치 감정분석 실패, 1장씩 분석으로 대체] {e}")
        return [analyze_emotion_single(c, exclude_neutral) for c in face_crops]
    finally:
        elapsed_ms = (time.time() - _t0) * 1000
        _emotion_call_times_ms.append(elapsed_ms)
        _emotion_batch_sizes.append(len(face_crops))
        per_face = elapsed_ms / len(face_crops)
        print(f"[감정분석 소요시간] {elapsed_ms:.1f} ms ({len(face_crops)}명 배치, 1명당 {per_face:.1f} ms)")


class CameraSource:
    def __init__(self, index, token):
        self.index = index
        self.token = token
        self.label = f"cam{index}"
        self.cap = cv2.VideoCapture(token)
        self.tracker = SimpleTracker()
        self.last_emotion = {}
        self.last_analysis_time = -999.0
        self.window_name = f"Source {index}: {token}"

    def is_opened(self):
        return self.cap.isOpened()

    def release(self):
        self.cap.release()
        cv2.destroyWindow(self.window_name) if cv2.getWindowProperty(
            self.window_name, cv2.WND_PROP_VISIBLE
        ) >= 1 else None


def main(source_tokens, output_path, interval_sec, narration_path=None,
         model_variant="full", use_batch=True):
    if use_batch and not _BATCH_API_AVAILABLE:
        print("[경고] 배치 처리에 필요한 내부 API를 찾지 못했습니다. 기존 방식(1장씩)으로 진행합니다.")
        use_batch = False
    print(f"[설정] 배치 처리: {'사용' if use_batch else '미사용 (1장씩 분석)'}")

    sources = []
    for idx, token in enumerate(source_tokens):
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

                        if do_analysis and crops:
                            if use_batch:
                                batch_results = analyze_emotion_batch(crops)
                            else:
                                batch_results = [analyze_emotion_single(c) for c in crops]
                        else:
                            batch_results = [None] * len(crops)

                        for local_id, face_crop, box, emo_result in zip(local_ids, crops, boxes, batch_results):
                            global_face_id = f"{cs.label}_{local_id}"

                            if emo_result is not None:
                                emotion_en, confidence = emo_result
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
                    break

                if cv2.waitKey(1) & 0xFF == ord('q'):
                    quit_requested = True

                if quit_requested:
                    break
        finally:
            for cs in sources:
                cs.cap.release()
            cv2.destroyAllWindows()

    print(f"\nDone. Saved to: {output_path}")

    if _emotion_call_times_ms:
        n_calls = len(_emotion_call_times_ms)
        total_faces = sum(_emotion_batch_sizes)
        avg_call_ms = sum(_emotion_call_times_ms) / n_calls
        # 얼굴 1명 기준 평균 시간 (배치일 때는 "호출시간/배치크기"들의 평균)
        per_face_times = [t / n for t, n in zip(_emotion_call_times_ms, _emotion_batch_sizes)]
        avg_per_face_ms = sum(per_face_times) / len(per_face_times)

        print(f"\n[감정분석 속도 요약] 총 {n_calls}회 호출 (총 {total_faces}개 얼굴 처리)")
        print(f"  호출당 평균: {avg_call_ms:.1f} ms   호출당 최소: {min(_emotion_call_times_ms):.1f} ms   호출당 최대: {max(_emotion_call_times_ms):.1f} ms")
        print(f"  얼굴 1명당 평균 처리시간: {avg_per_face_ms:.1f} ms")
        print(f"  평균 배치 크기: {total_faces / n_calls:.1f}명/호출")


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
    parser.add_argument("--device", type=str, default="auto", choices=["cpu", "gpu", "auto"],
                        help="감정 분석에 쓸 디바이스 (기본 auto = TensorFlow가 알아서 결정)")
    parser.add_argument("--no-batch", dest="use_batch", action="store_false",
                        help="배치 처리를 쓰지 않고 기존 방식(얼굴 1장씩 분석)으로 실행")
    args = parser.parse_args()

    main(args.sources, args.output, args.interval, args.narration,
         args.model, use_batch=args.use_batch)