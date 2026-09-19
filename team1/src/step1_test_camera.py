"""
[4단계] DroidCam 연결 테스트

목적:
- USB로 연결한 DroidCam이 OpenCV에서 정상적으로 읽히는지 확인
- 어떤 인덱스(0, 1, 2...)가 DroidCam인지 찾기
- 해상도 / FPS를 확인해서 이후 단계 설계 기준값으로 사용

사용법:
    python step1_test_camera.py

동작:
- 인덱스 0부터 3까지 순서대로 열어보면서 화면을 띄움
- 현재 열린 카메라가 DroidCam인지 눈으로 확인 후, 창을 닫고
  다음 인덱스로 넘어감 (아무 키나 누르면 다음 인덱스 테스트)
- 'q'를 누르면 종료
"""

import cv2

def test_camera_index(index: int):
    print(f"\n[테스트] 카메라 인덱스 {index} 열기 시도...")
    cap = cv2.VideoCapture(index)

    if not cap.isOpened():
        print(f"  -> 인덱스 {index}: 열 수 없음")
        return False

    width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    fps = cap.get(cv2.CAP_PROP_FPS)
    print(f"  -> 인덱스 {index}: 열림 (해상도 {int(width)}x{int(height)}, FPS {fps:.1f})")
    print("  -> 화면을 보고 DroidCam 영상이 맞으면 'y', 아니면 아무 키나 누르세요 (종료: q)")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("  -> 프레임을 읽을 수 없음")
            break

        cv2.putText(frame, f"index={index}  press y=confirm, n=next, q=quit",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.imshow("Camera Test", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            cap.release()
            cv2.destroyAllWindows()
            return "quit"
        elif key == ord('y'):
            print(f"  ✅ 인덱스 {index}가 DroidCam으로 확인됨. 이 값을 이후 스크립트에서 사용하세요.")
            cap.release()
            cv2.destroyAllWindows()
            return True
        elif key == ord('n'):
            break

    cap.release()
    cv2.destroyAllWindows()
    return False


if __name__ == "__main__":
    for idx in range(4):
        result = test_camera_index(idx)
        if result == "quit":
            break
        if result is True:
            break
    print("\n테스트 종료.")
