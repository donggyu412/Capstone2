"""
[5단계] MediaPipe 얼굴 검출 최소 구현 (Tasks API 버전)

목적:
- 카메라 프레임에서 몇 명의 얼굴이 실제로 검출되는지 눈으로 확인
- 20명을 목표로 한다면, 이 단계에서 검출 수가 부족하면
  카메라 거리/화각을 먼저 조정해야 함
- short-range / full-range 두 모델을 --model 옵션으로 바꿔가며 비교 가능

사전 준비 (필요한 모델만 받으면 됨):
- short-range: https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite
- full-range : https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_full_range/float16/1/blaze_face_full_range.tflite
  둘 다 ../models/ 폴더에 파일명 그대로 저장

사용법:
    python step2_face_detect_test.py --camera 0                  # 기본값: full-range 모델
    python step2_face_detect_test.py --camera 0 --model short    # short-range로 비교

주의:
- --camera 값은 step1에서 확인한 DroidCam 인덱스로 바꿔서 실행
- 화면에 각 얼굴의 검출 신뢰도(%)도 같이 표시됩니다 — 거리별로 이 값이
  얼마나 떨어지는지 보고 모델을 고르는 데 참고하세요.
"""

import argparse
import os
import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

MODEL_FILES = {
    "short": "blaze_face_short_range.tflite",   # 근거리(~2m) 최적화, 가벼움
    "full": "blaze_face_full_range.tflite",     # 원거리까지 대응, 약간 무거움
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


def main(camera_index: int, model_variant: str):
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        print(f"카메라 인덱스 {camera_index}를 열 수 없습니다.")
        return

    detector = build_detector(model_variant)
    print(f"[사용 모델] {model_variant} ({MODEL_FILES[model_variant]})")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        result = detector.detect(mp_image)

        num_faces = len(result.detections) if result.detections else 0
        for detection in result.detections:
            bbox = detection.bounding_box  # pixel 단위: origin_x, origin_y, width, height
            x1, y1 = bbox.origin_x, bbox.origin_y
            x2, y2 = x1 + bbox.width, y1 + bbox.height
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)

            score = detection.categories[0].score if detection.categories else 0.0
            cv2.putText(frame, f"{score*100:.0f}%", (x1, max(15, y1 - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        cv2.putText(frame, f"[{model_variant}] Detected faces: {num_faces}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        cv2.imshow("Face Detection Test (press q to quit)", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    detector.close()
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--camera", type=int, default=0, help="카메라 인덱스 (step1에서 확인한 값)")
    parser.add_argument("--model", type=str, default="full", choices=["short", "full"],
                        help="얼굴 검출 모델: short(근거리) / full(원거리 대응, 기본값)")
    args = parser.parse_args()
    main(args.camera, args.model)
