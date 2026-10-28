# -*- coding: utf-8 -*-
"""
[6~7단계 - 멀티 카메라 + 배치/디바이스 선택 + 표정 변화(델타) 판정 버전]

노트북 내장캠 + 폰(DroidCam) + 영상 파일 등 여러 소스를 동시에 사용

[이 버전의 핵심: 감정 판정 방식]

기존 방식(absolute): 7개 감정 점수 중 가장 높은 것 하나를 그대로 기록.
  → 중립을 빼면 "무표정"이 남은 6개 중 점수가 가장 높은 감정(DeepFace에서는 주로 슬픔)으로
    강제 분류되어, 모든 얼굴이 같은 감정으로 쏠리는 문제가 생깁니다.

델타 방식(delta, 기본값): 얼굴마다 "평소 표정(기준선)"을 기억해 두고,
  기준선보다 가장 많이 "올라간" 감정을 그 순간의 감정으로 기록합니다.
  → 얼굴이 원래 갖고 있는 고정된 쏠림(슬픔 편향 등)이 상쇄되고,
    살짝만 표정이 바뀌어도 그 방향의 감정이 바로 기록됩니다.

  - 처음 --warmup 번의 분석은 기준선을 만드는 데만 쓰고 CSV에는 기록하지 않습니다.
  - 기준선은 지수이동평균(--ema)으로 천천히 갱신됩니다.
    (너무 빠르면 오래 지속되는 표정이 기준선에 흡수되어 변화로 안 잡힘)
  - --min-delta 보다 작은 변화만 있으면 직전 감정을 유지합니다 (기본 0 = 항상 새로 판정).
  - 중립은 기본으로 제외합니다. (--keep-neutral 로 포함)
  - confidence 는 기존과 같은 의미(7개 전체 대비 해당 감정의 퍼센트)입니다.

[진단용] --dump-scores 파일.csv
  분석할 때마다 7개 감정의 원본 점수를 따로 저장합니다.
  결과가 이상할 때 모델이 실제로 어떤 점수를 냈는지 확인할 수 있습니다.

사용법:

    # 기본 (델타 방식, 중립 제외)
    python step3b_multi_camera_pipeline.py --sources 0 1 --output ../output/session.csv --interval 0.5

    # 원본 점수도 같이 저장 (진단용)
    python step3b_multi_camera_pipeline.py --sources 0 1 --output ../output/session.csv --interval 0.5 --dump-scores ../output/scores.csv

    # 예전 방식(절대 점수 1등)으로
    python step3b_multi_camera_pipeline.py --sources 0 1 --output ../output/session.csv --mode absolute --sensitivity 0

    # CPU로 강제 / 배치 없이
    python step3b_multi_camera_pipeline.py --sources 0 1 --output ../output/session.csv --device cpu
    python step3b_multi_camera_pipeline.py --sources 0 1 --output ../output/session.csv --no-batch
"""

import argparse
import csv
import math
import os
import subprocess
import sys
import time
from types import SimpleNamespace
from collections import Counter

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
    "short": "blaze_face_short_range.tflite",  # 근거리(~2m) 최적화, 가벼움
    "full": "blaze_face_full_range.tflite",    # 원거리까지 대응, 약간 무거움
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


# ─────────────────────────────────────────────────────────
# 감정 판정 설정  (__main__ 블록에서 명령행 옵션 값으로 덮어쓴다)
# ─────────────────────────────────────────────────────────
MODE = "delta"           # "delta": 기준선 대비 상승량으로 판정 / "absolute": 절대 점수 1등
EXCLUDE_NEUTRAL = True   # True: 중립을 후보에서 제외
EMA_ALPHA = 0.05         # 기준선이 새 값을 따라가는 속도 (0~1, 작을수록 기준선이 오래 유지됨)
WARMUP = 3               # (delta) 얼굴마다 처음 N번의 분석은 기준선 만들기에만 사용, 기록 안 함
MIN_DELTA = 0.0          # (delta) 이 값(퍼센트포인트)보다 작은 변화면 직전 감정 유지. 0이면 항상 새로 판정
SENSITIVITY = 3.0        # (absolute) 기준선 대비 올라간 양에 곱하는 가산 배수

_face_baselines = {}     # 얼굴(추적 ID)별 평소 표정 점수 {key: {emotion: score}}
_face_samples = {}       # 얼굴별 지금까지 분석된 횟수
_face_last = {}          # 얼굴별 직전에 기록한 감정
_emotion_counts = Counter()  # 기록된 감정 분포 (종료 시 출력)

_dump_writer = None      # --dump-scores 용 csv writer
_T0 = time.time()        # 촬영 시작 시각 (main에서 갱신)


def pick_emotion(scores, key=None, exclude_neutral=None):
    """
    감정 점수 딕셔너리에서 1등 감정을 고른다.

    scores : {"angry": .., "disgust": .., ... "neutral": ..}  (합계 100 또는 1, 단위 무관)
    key    : 얼굴 식별자 (예: "cam0_3"). 같은 얼굴의 평소 표정(기준선)을 기억하는 데 쓴다.

    반환   : (감정_영문, confidence)  - 기록하지 않을 때(준비 중/실패)는 (None, None)
             confidence 는 7개 전체 점수 대비 해당 감정의 퍼센트.
    """
    if exclude_neutral is None:
        exclude_neutral = EXCLUDE_NEUTRAL

    labels = [l for l in EMOTION_LABELS_ORDER if not (exclude_neutral and l == "neutral")]
    raw_total = sum(float(scores.get(l, 0.0)) for l in EMOTION_LABELS_ORDER)
    cand_total = sum(float(scores.get(l, 0.0)) for l in labels)
    if raw_total <= 0 or cand_total <= 0:
        return None, None

    # 진단용: 원본 7개 점수를 그대로 저장
    if _dump_writer is not None:
        _dump_writer.writerow(
            [round(time.time() - _T0, 2), key]
            + [round(float(scores.get(l, 0.0)), 3) for l in EMOTION_LABELS_ORDER]
        )

    # 후보 감정끼리 다시 100% 기준으로 재정규화
    norm = {l: 100.0 * float(scores.get(l, 0.0)) / cand_total for l in labels}

    if MODE == "delta" and key is not None:
        base = _face_baselines.get(key)
        if base is None:                       # 처음 보는 얼굴: 기준선 시작
            _face_baselines[key] = dict(norm)
            _face_samples[key] = 1
            return None, None

        n = _face_samples.get(key, 1)
        if n < WARMUP:                         # 준비 구간: 평균으로 기준선을 만들고 기록은 안 함
            for l in labels:
                base[l] = (base[l] * n + norm[l]) / (n + 1)
            _face_samples[key] = n + 1
            return None, None

        # 기준선 대비 올라간 양 (음수면 평소보다 내려간 것)
        dev = {l: norm[l] - base[l] for l in labels}
        for l in labels:                       # 기준선은 EMA로 천천히 갱신
            base[l] = (1.0 - EMA_ALPHA) * base[l] + EMA_ALPHA * norm[l]
        _face_samples[key] = n + 1

        dominant = max(dev, key=dev.get)
        if dev[dominant] < MIN_DELTA and key in _face_last:
            dominant = _face_last[key]         # 변화가 너무 작으면 직전 감정 유지
        _face_last[key] = dominant
    else:
        # absolute 방식: 재정규화 점수 (+ 선택적으로 기준선 대비 가산점) 1등
        adjusted = dict(norm)
        if key is not None:
            base = _face_baselines.get(key)
            if base is None:
                _face_baselines[key] = dict(norm)
            else:
                if SENSITIVITY > 0:
                    for l in labels:
                        adjusted[l] = norm[l] + SENSITIVITY * max(0.0, norm[l] - base[l])
                for l in labels:
                    base[l] = (1.0 - EMA_ALPHA) * base[l] + EMA_ALPHA * norm[l]
        dominant = max(adjusted, key=adjusted.get)

    confidence = 100.0 * float(scores.get(dominant, 0.0)) / raw_total
    return dominant, confidence


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


def scale_detection(detection, scale):
    """줄인 영상에서 얻은 검출 박스를 원본 영상 좌표로 되돌린다 (crop_face가 쓰는 속성만 복사)."""
    bb = detection.bounding_box
    return SimpleNamespace(bounding_box=SimpleNamespace(
        origin_x=int(bb.origin_x * scale), origin_y=int(bb.origin_y * scale),
        width=int(bb.width * scale), height=int(bb.height * scale)))


_emotion_call_times_ms = []  # 호출(또는 배치) 1회에 걸린 시간(ms)
_emotion_batch_sizes = []    # 그 호출에 포함된 얼굴 수 (배치 크기)
_emotion_model_cache = {"model": None}


def _get_emotion_model():
    """DeepFace 내부의 Emotion 모델을 직접 가져온다 (최초 1회만 로드, 이후 캐시 재사용)."""
    if _emotion_model_cache["model"] is None:
        _emotion_model_cache["model"] = _deepface_modeling.build_model(
            task="facial_attribute", model_name="Emotion"
        )
    return _emotion_model_cache["model"]


def analyze_emotion_single(face_crop, key=None, exclude_neutral=None):
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
        return pick_emotion(scores, key, exclude_neutral)
    except Exception as e:
        print(f"[emotion analysis failed] {e}")
        return None, None
    finally:
        elapsed_ms = (time.time() - _t0) * 1000
        _emotion_call_times_ms.append(elapsed_ms)
        _emotion_batch_sizes.append(1)
        print(f"[감정분석 소요시간] {elapsed_ms:.1f} ms (1명)")


def analyze_emotion_batch(face_crops, keys=None, exclude_neutral=None):
    """
    얼굴 여러 장을 한 번에 모델에 넣어 분석한다 (진짜 배치 추론).

    face_crops: BGR 얼굴 크롭 이미지의 리스트 (크기가 서로 달라도 됨 - 내부에서 통일시킴)
    keys      : 각 얼굴의 식별자 리스트 (기준선 기억용, 예: ["cam0_0", "cam0_1"])
    반환: [(dominant_emotion_en, confidence), ...] 입력 순서와 동일한 길이의 리스트
          기록하지 않을 항목(준비 중/실패)은 (None, None)
    """
    if not face_crops:
        return []
    if keys is None:
        keys = [None] * len(face_crops)

    _t0 = time.time()
    try:
        model = _get_emotion_model()

        # 모델 내부에서 np.array(리스트)로 한 번에 묶으려 하므로,
        # 크기가 제각각이면 실패한다 → 여기서 미리 동일 크기로 맞춘다.
        # DeepFace.analyze()는 내부에서 얼굴을 0~1로 정규화한 뒤 모델에 넣는다.
        # 모델을 직접 호출할 때도 똑같이 정규화해야 한다. (0~255 그대로 넣으면
        # 출력이 한 감정에 100%로 쏠려서 confidence가 0 아니면 100만 나옴)
        resized = [cv2.resize(c, (224, 224)).astype("float32") / 255.0 for c in face_crops]
        predictions = model.predict(resized)  # shape: (n, 7) — 각 행이 한 얼굴의 7개 감정 점수
        predictions = np.atleast_2d(predictions)

        results = []
        for row, key in zip(predictions, keys):
            scores = {label: float(row[i]) for i, label in enumerate(EMOTION_LABELS_ORDER)}
            results.append(pick_emotion(scores, key, exclude_neutral))
        return results
    except Exception as e:
        print(f"[배치 감정분석 실패, 1장씩 분석으로 대체] {e}")
        return [analyze_emotion_single(c, k, exclude_neutral) for c, k in zip(face_crops, keys)]
    finally:
        elapsed_ms = (time.time() - _t0) * 1000
        _emotion_call_times_ms.append(elapsed_ms)
        _emotion_batch_sizes.append(len(face_crops))
        per_face = elapsed_ms / len(face_crops)
        print(f"[감정분석 소요시간] {elapsed_ms:.1f} ms ({len(face_crops)}명 배치, 1명당 {per_face:.1f} ms)")


class ScreenCapture:
    """PC 화면을 카메라처럼 읽는다 (cv2.VideoCapture와 같은 isOpened/read/release 제공)

    --sources 에 넣는 형식
        screen            : 1번 모니터 전체
        screen:2          : 2번 모니터 전체
        screen:x,y,w,h    : 화면의 일부 영역 (예: screen:0,0,1280,720)
    """

    def __init__(self, token):
        self._ok = False
        try:
            import mss
        except ImportError:
            print("[오류] 화면 캡처에는 mss가 필요합니다: pip install mss")
            return
        try:
            # mss 10부터 mss.mss 대신 mss.MSS 권장 (구버전 호환 유지)
            self._sct = (getattr(mss, "MSS", None) or mss.mss)()
        except Exception as e:
            print(f"[오류] 화면 캡처를 시작할 수 없습니다: {e}")
            return

        spec = token.split(":", 1)[1] if ":" in token else "1"
        try:
            if "," in spec:
                x, y, w, h = [int(v) for v in spec.split(",")]
                self._mon = {"left": x, "top": y, "width": w, "height": h}
            else:
                idx = int(spec)
                if not 1 <= idx < len(self._sct.monitors):
                    print(f"[오류] 모니터 {idx}번이 없습니다 (사용 가능: 1~{len(self._sct.monitors) - 1})")
                    return
                self._mon = self._sct.monitors[idx]
        except ValueError:
            print(f"[오류] 화면 소스 형식이 잘못됐습니다: {token} (예: screen, screen:2, screen:0,0,1280,720)")
            return
        print(f"[화면 캡처] {token} → {self._mon['width']}x{self._mon['height']} "
              f"(좌상단 {self._mon['left']},{self._mon['top']})")
        self._ok = True

    def isOpened(self):
        return self._ok

    def read(self):
        if not self._ok:
            return False, None
        img = np.array(self._sct.grab(self._mon))  # BGRA
        return True, cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

    def release(self):
        if self._ok:
            self._sct.close()
            self._ok = False


def is_screen_token(token):
    return isinstance(token, str) and token.lower().startswith("screen")


class CameraSource:
    def __init__(self, index, token):
        self.index = index
        self.token = token
        self.is_screen = is_screen_token(token)
        self.label = f"screen{index}" if self.is_screen else f"cam{index}"
        self.cap = ScreenCapture(token) if self.is_screen else cv2.VideoCapture(token)
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
         model_variant="full", use_batch=True, dump_scores_path=None, preview_width=1280,
         det_width=1280):
    global _dump_writer, _T0

    if use_batch and not _BATCH_API_AVAILABLE:
        print("[경고] 배치 처리에 필요한 내부 API를 찾지 못했습니다. 기존 방식(1장씩)으로 진행합니다.")
        use_batch = False
    print(f"[설정] 배치 처리: {'사용' if use_batch else '미사용 (1장씩 분석)'}")
    print(f"[설정] 판정 방식: {MODE} / 중립: {'제외' if EXCLUDE_NEUTRAL else '포함'} / "
          f"기준선 EMA: {EMA_ALPHA:g} / 준비 {WARMUP}회 / 최소변화 {MIN_DELTA:g} / 민감도(absolute): {SENSITIVITY:g}")

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

    dump_f = None
    if dump_scores_path:
        dump_f = open(dump_scores_path, "w", newline="", encoding="utf-8-sig")
        _dump_writer = csv.writer(dump_f)
        _dump_writer.writerow(["timestamp_sec", "face_id"] + EMOTION_LABELS_ORDER)
        print(f"[설정] 원본 점수 저장: {dump_scores_path}")

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp_sec", "source", "face_id", "emotion_en", "emotion_kr", "confidence"])

        if narration_path:
            print(f"[재생 시작] {narration_path}")
            play_narration_video(narration_path)

        start_time = time.time()
        _T0 = start_time
        save_next = False
        capture_dir = os.path.dirname(os.path.abspath(output_path))
        print("[안내] 영상 창을 클릭한 뒤 's' = 현재 화면 저장(PNG), 'q' = 종료")

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
                    # 검출은 줄인 영상으로 한다 (4K는 색 변환·복사만으로도 느려짐).
                    # 검출 모델 입력이 원래 192px라서 줄여도 검출 결과는 거의 같고, 얼굴 크롭은 원본에서 자른다.
                    det_scale = 1.0
                    det_frame = frame
                    if det_width and frame.shape[1] > det_width:
                        det_scale = frame.shape[1] / det_width          # 원본 / 축소 비율
                        det_frame = cv2.resize(frame, (det_width, int(frame.shape[0] / det_scale)),
                                               interpolation=cv2.INTER_AREA)
                    rgb_frame = cv2.cvtColor(det_frame, cv2.COLOR_BGR2RGB)
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
                    result = detector.detect(mp_image)
                    if det_scale != 1.0:
                        detections = [scale_detection(d, det_scale) for d in result.detections]
                    else:
                        detections = list(result.detections)

                    do_analysis = (timestamp_sec - cs.last_analysis_time) >= interval_sec
                    if do_analysis:
                        cs.last_analysis_time = timestamp_sec

                    if detections:
                        centroids, crops, boxes = [], [], []
                        for detection in detections:
                            face_crop, centroid, box = crop_face(frame, detection)
                            if face_crop.size == 0:
                                continue
                            centroids.append(centroid)
                            crops.append(face_crop)
                            boxes.append(box)

                        local_ids = cs.tracker.update(centroids)

                        if do_analysis and crops:
                            keys = [f"{cs.label}_{lid}" for lid in local_ids]
                            if use_batch:
                                batch_results = analyze_emotion_batch(
                                    crops, keys, exclude_neutral=EXCLUDE_NEUTRAL)
                            else:
                                batch_results = [
                                    analyze_emotion_single(c, k, EXCLUDE_NEUTRAL)
                                    for c, k in zip(crops, keys)
                                ]
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
                                    _emotion_counts[emotion_kr] += 1

                            # 4K처럼 큰 영상에서도 박스/글자가 작아 보이지 않게 해상도에 비례해 키움
                            ds = max(1.0, frame.shape[1] / 1280.0)
                            x1, y1, x2, y2 = box
                            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), max(2, round(2 * ds)))
                            if local_id in cs.last_emotion:
                                emotion_en, confidence = cs.last_emotion[local_id]
                                label = f"{global_face_id}: {emotion_en} ({confidence:.0f}%)"
                                cv2.putText(frame, label, (x1, max(int(20 * ds), y1 - int(10 * ds))),
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.6 * ds, (0, 255, 0),
                                            max(2, round(2 * ds)))

                    # 's' 키: 박스/라벨이 그려진 "원본 해상도" 프레임을 PNG로 저장 (미리보기 축소 전)
                    if save_next:
                        cap_path = os.path.join(capture_dir, f"capture_{cs.label}_{timestamp_sec:.1f}s.png")
                        if cv2.imwrite(cap_path, frame):
                            print(f"[저장] {cap_path}")
                        else:
                            print(f"[저장 실패] {cap_path}")

                    if cs.is_screen and frame.shape[1] > 640:
                        # 화면 캡처는 미리보기를 작게 (미리보기 창이 다시 캡처되는 것 방지)
                        scale = 640 / frame.shape[1]
                        frame = cv2.resize(frame, None, fx=scale, fy=scale)
                    elif preview_width and frame.shape[1] > preview_width:
                        # 큰 영상(4K 등)은 미리보기만 줄여서 노트북 화면에 다 보이게 함 (분석은 원본으로)
                        scale = preview_width / frame.shape[1]
                        frame = cv2.resize(frame, None, fx=scale, fy=scale)

                    cv2.imshow(cs.window_name, frame)

                if not any_frame_read:
                    break

                key = cv2.waitKey(1) & 0xFF
                save_next = (key == ord('s'))      # 다음 프레임을 저장
                if key == ord('q'):
                    quit_requested = True

                if quit_requested:
                    break
        finally:
            for cs in sources:
                cs.cap.release()
            cv2.destroyAllWindows()
            if dump_f is not None:
                dump_f.close()

    print(f"\nDone. Saved to: {output_path}")

    if _emotion_counts:
        total = sum(_emotion_counts.values())
        print("\n[기록된 감정 분포]")
        for emo, cnt in _emotion_counts.most_common():
            print(f"  {emo}: {cnt}건 ({100.0 * cnt / total:.1f}%)")

    if _emotion_call_times_ms:
        n_calls = len(_emotion_call_times_ms)
        total_faces = sum(_emotion_batch_sizes)
        avg_call_ms = sum(_emotion_call_times_ms) / n_calls
        # 얼굴 1명 기준 평균 시간 (배치일 때는 "호출시간/배치크기"들의 평균)
        per_face_times = [t / n for t, n in zip(_emotion_call_times_ms, _emotion_batch_sizes)]
        avg_per_face_ms = sum(per_face_times) / len(per_face_times)
        print(f"\n[감정분석 속도 요약] 총 {n_calls}회 호출 (총 {total_faces}개 얼굴 처리)")
        print(f"  호출당 평균: {avg_call_ms:.1f} ms  호출당 최소: {min(_emotion_call_times_ms):.1f} ms  호출당 최대: {max(_emotion_call_times_ms):.1f} ms")
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
    parser.add_argument("--keep-neutral", action="store_true",
                        help="중립을 후보에 포함 (기본은 제외)")
    parser.add_argument("--mode", type=str, default="delta", choices=["delta", "absolute"],
                        help="delta(기본): 평소 표정 대비 가장 올라간 감정 / absolute: 절대 점수 1등")
    parser.add_argument("--ema", type=float, default=0.05,
                        help="평소 표정(기준선)이 새 값을 따라가는 속도 0~1 (기본 0.05, "
                             "작을수록 오래 유지되어 지속되는 표정도 변화로 잡힘)")
    parser.add_argument("--warmup", type=int, default=3,
                        help="(delta) 얼굴마다 처음 몇 번의 분석을 기준선 만들기에만 쓰고 기록하지 않을지 (기본 3)")
    parser.add_argument("--min-delta", type=float, default=0.0,
                        help="(delta) 이 값(퍼센트포인트)보다 작은 변화면 직전 감정을 유지 "
                             "(기본 0 = 항상 새로 판정, 노이즈로 감정이 튀면 2~3으로 올리세요)")
    parser.add_argument("--sensitivity", type=float, default=3.0,
                        help="(absolute) 기준선 대비 올라간 양에 곱하는 배수 (기본 3.0, 0이면 가산점 없음)")
    parser.add_argument("--dump-scores", type=str, default=None,
                        help="진단용: 분석 때마다 7개 감정 원본 점수를 이 csv 파일에 저장")
    parser.add_argument("--preview-width", type=int, default=1280,
                        help="미리보기 창의 최대 가로 픽셀 (기본 1280, 0이면 원본 크기). 저장·분석은 원본 해상도")
    parser.add_argument("--det-width", type=int, default=1280,
                        help="얼굴 검출에 쓰는 영상의 최대 가로 픽셀 (기본 1280, 0이면 원본으로 검출). "
                             "4K 영상이 느릴 때 속도를 크게 올려 줌. 감정 분석용 얼굴 크롭은 항상 원본에서 자름")
    args = parser.parse_args()

    MODE = args.mode
    EXCLUDE_NEUTRAL = not args.keep_neutral
    EMA_ALPHA = min(1.0, max(0.0, args.ema))
    WARMUP = max(1, args.warmup)
    MIN_DELTA = max(0.0, args.min_delta)
    SENSITIVITY = max(0.0, args.sensitivity)

    main(args.sources, args.output, args.interval, args.narration,
         args.model, use_batch=args.use_batch, dump_scores_path=args.dump_scores,
         preview_width=args.preview_width, det_width=args.det_width)