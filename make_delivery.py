"""
최종 전달물 모으기 — run_team3.py --object --alpha 로 5분 렌더한 뒤 실행
  ① object_line_1.mp4 (+ object_line_1_matte.mp4)  오브제만 + 투명도
  ② dream_final.mp4                               새 배경 + 오브제 + dream_sound.wav
  ③ .json                                         렌더 기록 (형상 목록 · GA 기록)
  ④ targets_preview/ · object_story.md            목표 선화 미리보기 · 설명서

  python make_delivery.py --sound D:\\renders\\dream_sound.wav --out D:\\renders\\final_1028
  (D:\\asd 에서 실행 · 가장 최근 render_… 폴더를 쓴다)
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OBJ = ROOT / 'team3' / 'object'


def ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return 'ffmpeg'


def duration(path):
    try:
        import cv2
        c = cv2.VideoCapture(str(path))
        n, fps = c.get(cv2.CAP_PROP_FRAME_COUNT), c.get(cv2.CAP_PROP_FPS) or 30
        return round(n / fps, 1)
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sound', required=True, help='합칠 사운드 (dream_sound.wav)')
    ap.add_argument('--out', default=r'D:\renders\final_1028')
    ap.add_argument('--render', help='렌더 폴더 (생략하면 가장 최근 render_… 중 _quick 이 아닌 것)')
    a = ap.parse_args()

    if a.render:
        rd = Path(a.render)
    else:
        runs = [d for d in (OBJ / 'output').glob('render_*') if d.is_dir() and not d.name.endswith('_quick')]
        if not runs:
            sys.exit('[중단] team3/object/output 에 render_… 폴더가 없습니다. 먼저 run_team3.py --object --alpha 를 돌리세요.')
        rd = max(runs, key=lambda d: d.stat().st_mtime)
    print(f'렌더 폴더: {rd}')
    need = {'통합(배경+오브제)': rd / 'dream_integrated.mp4', '오브제만': rd / 'object_line_alpha.mp4',
            '투명도': rd / 'object_line_alpha_matte.mp4'}
    miss = [k for k, p in need.items() if not p.exists()]
    if miss:
        sys.exit(f'[중단] 렌더 폴더에 없는 것: {", ".join(miss)} — run_team3.py --object --alpha 로 렌더했는지 확인하세요.')
    snd = Path(a.sound)
    if not snd.exists():
        sys.exit(f'[중단] 사운드가 없습니다: {snd}')

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    # ① 오브제만 + 투명도
    shutil.copyfile(need['오브제만'], out / 'object_line_1.mp4')
    shutil.copyfile(need['투명도'], out / 'object_line_1_matte.mp4')
    # ② 새 배경 + 오브제 + 사운드
    cmd = [ffmpeg(), '-y', '-v', 'error', '-i', str(need['통합(배경+오브제)']), '-i', str(snd),
           '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '256k', '-shortest',
           str(out / 'dream_final.mp4')]
    r = subprocess.run(cmd)
    if r.returncode != 0:
        sys.exit('[중단] 사운드를 합치지 못했습니다.')
    # ③ 렌더 기록
    for js in ('dream_integrated.json', 'object_line_alpha.json'):
        if (rd / js).exists():
            shutil.copyfile(rd / js, out / js.replace('object_line_alpha', 'object_line_1'))
    # ④ 목표 선화 미리보기 · 설명서
    prev = OBJ / 'output_objects' / 'targets_preview'
    if prev.is_dir():
        shutil.copytree(prev, out / 'targets_preview', dirs_exist_ok=True)
    for f in ('object_story.md', 'targets.json'):
        if (OBJ / 'output_objects' / f).exists():
            shutil.copyfile(OBJ / 'output_objects' / f, out / f)

    print('\n모았습니다 →', out)
    for p in sorted(out.iterdir()):
        if p.is_dir():
            print(f'  {p.name}/  ({len(list(p.glob("*.png")))}장)')
        else:
            d = duration(p) if p.suffix == '.mp4' else None
            print(f'  {p.name}  {p.stat().st_size / 1048576:.1f}MB' + (f'  · {d}초' if d else ''))


if __name__ == '__main__':
    main()
