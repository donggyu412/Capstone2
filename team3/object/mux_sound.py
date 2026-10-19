"""
통합 영상에 1팀 사운드 붙이기 — 영상은 다시 인코딩하지 않고(화질 그대로) 소리만 얹는다.

  python mux_sound.py                     (D:\\renders 기준 1~3판 모두)
  python mux_sound.py --only 2            (2판만)
  python mux_sound.py --gain 3            (소리를 3dB 키워서 붙이기)

폴더 규칙 (--dir 로 바꿀 수 있음)
  D:\\renders\\dream_integrated_1.mp4    통합 영상 (오브제 엔진 결과 · 소리 없음)
  D:\\renders\\sound\\dream_sound_1.wav  1팀 사운드
  → D:\\renders\\dream_final_1.mp4       소리 붙은 최종본

붙이기 전에 영상과 소리 길이가 같은지(5분) 확인하고, 다르면 멈춘다.
필요 패키지: imageio-ffmpeg · opencv-python (오브제 엔진과 같은 환경이면 이미 있다)
"""
import argparse
import subprocess
import sys
import wave
from pathlib import Path

import cv2


def ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def video_sec(p):
    cap = cv2.VideoCapture(str(p))
    if not cap.isOpened():
        return None
    n, fps = cap.get(cv2.CAP_PROP_FRAME_COUNT), cap.get(cv2.CAP_PROP_FPS) or 30
    cap.release()
    return n / fps


def wav_sec(p):
    with wave.open(str(p)) as w:
        return w.getnframes() / w.getframerate(), w.getframerate(), w.getnchannels()


def main():
    ap = argparse.ArgumentParser(description="통합 영상에 사운드 붙이기")
    ap.add_argument("--dir", default=r"D:\renders")
    ap.add_argument("--only", type=int, nargs="+", default=[1, 2, 3])
    ap.add_argument("--gain", type=float, default=0.0, help="소리 크기 조정(dB) · 기본 0 = 그대로")
    ap.add_argument("--bitrate", default="192k")
    args = ap.parse_args()
    d = Path(args.dir)
    ok_all = True
    for k in args.only:
        vid, snd, out = d / f"dream_integrated_{k}.mp4", d / "sound" / f"dream_sound_{k}.wav", d / f"dream_final_{k}.mp4"
        print(f"\n=== {k}판 ===")
        if not vid.exists() or not snd.exists():
            print(f"  ! 파일이 없습니다: {vid if not vid.exists() else snd}")
            ok_all = False
            continue
        vs = video_sec(vid)
        try:
            ss, sr, ch = wav_sec(snd)
        except Exception as e:
            print(f"  ! 소리 파일을 읽을 수 없습니다(손상?): {e}")
            ok_all = False
            continue
        print(f"  영상 {vs:.2f}초 · 소리 {ss:.2f}초 ({sr}Hz · {ch}ch)")
        if vs is None or abs(vs - ss) > 0.5:
            print("  ! 영상과 소리 길이가 0.5초 넘게 달라 멈춥니다 — 판 번호가 맞는지 확인하세요")
            ok_all = False
            continue
        cmd = [ffmpeg(), "-y", "-loglevel", "error", "-i", str(vid), "-i", str(snd),
               "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", args.bitrate]
        if args.gain:
            cmd += ["-af", f"volume={args.gain}dB"]
        cmd += ["-shortest", "-movflags", "+faststart", str(out)]
        r = subprocess.run(cmd)
        if r.returncode != 0 or not out.exists():
            print("  ! 붙이기 실패")
            ok_all = False
            continue
        print(f"  완료 → {out}  ({out.stat().st_size / 1e6:.0f}MB · {video_sec(out):.2f}초)")
    print("\n모두 끝났습니다." if ok_all else "\n일부 판에서 문제가 있었습니다 — 위 메시지를 확인하세요.")
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
