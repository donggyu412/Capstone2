"""
4팀 전달용 오브제 영상 만들기 — 두 가지를 한 번에 준비한다 (1팀 1~3판)

  A. 4팀 배경 위에 합성한 영상     team4_integrated_<판>.mp4   (4팀 배경 영상의 소리 그대로)
  B. 오브제만 + 투명도             object_line_<판>.mp4 + object_line_<판>_matte.mp4
     → 4팀이 자기 배경에 직접 합성:  out = bg × (1 − matte) + fill

  python render_team4.py                 (1~3판 · A와 B 모두)
  python render_team4.py --only 2 --mode alpha

순서
  1) 4팀 배경 영상 3개를 저장소의 origin/team4 브랜치에서 꺼내 영어 이름(bg1~3.mp4)으로 저장
     (team4/input/background/1~3번_꿈재현_배경_사운드.mp4 · 이미 있으면 건너뜀)
  2) 판마다 A · B 렌더 (오브제 엔진 기본 = 선화 · 어린아이 로봇이 그리는 과정)
  3) 결과 폴더에 4팀용 설명서 README_4팀.md 를 쓴다

저장소 폴더(D:\\asd) 안의 team3\\object 에서 실행한다. git fetch 로 origin/team4 를 먼저 받아 둔다.
"""
import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EMO = {1: '놀람 · 공포 · 중립 · 공포', 2: '혐오 · 공포 · 기쁨 · 슬픔', 3: '공포 · 공포 · 중립 · 중립'}


def fetch_bg(k, dst, ref):
    if dst.exists() and dst.stat().st_size > 1_000_000:
        return True
    path = f'{ref}:team4/input/background/{k}번_꿈재현_배경_사운드.mp4'
    r = subprocess.run(['git', 'show', path], capture_output=True, cwd=HERE)
    if r.returncode != 0 or len(r.stdout) < 1_000_000:
        print(f'  ! 4팀 배경 영상을 꺼내지 못했습니다: {path}\n    (저장소에서 git fetch 를 먼저 했는지 확인하세요)')
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(r.stdout)
    print(f'  4팀 배경 {k}판 → {dst} ({len(r.stdout) / 1e6:.0f}MB)')
    return True


def run(cmd):
    print('  $ ' + ' '.join(str(c) for c in cmd))
    return subprocess.run([str(c) for c in cmd], cwd=HERE).returncode == 0


README = """# 3팀 오브제 영상 (4팀 전달용 · 1팀 1~3판)

오브제 엔진 기본 스타일(선화 — 어린아이 로봇이 그리다 멈추고, 지우고, 다시 그리는 과정)로 렌더했습니다.
규격: 1920×1080 · 30fps · 300초(9,000프레임) · 기 0–75 · 승 75–150 · 전 150–225(반전 195초) · 결 225–300초

| 판 | 장면 감정 | A. 4팀 배경 위 합성 (4팀 소리 포함) | B. 오브제만 (검은 바탕) | B. 투명도 |
|---|---|---|---|---|
{rows}

## A. 4팀 배경 위에 합성한 영상
4팀이 `team4/input/background/` 에 올린 배경 영상 위에 오브제를 그렸고, 배경 영상의 소리를 그대로 붙였습니다. 바로 재생 · 검토용입니다.

## B. 오브제만 + 투명도 (직접 합성용)
- `object_line_N.mp4` — 오브제만 검은 바탕에 그린 영상 (**이미 투명도를 곱한 색**)
- `object_line_N_matte.mp4` — 투명도 (흰색 = 오브제, 검은색 = 비어 있음, 회색 = 반투명 · 선 둘레의 옅은 그림자 포함)

합성 식 (프레임마다, 0~1 범위):
```
out = bg × (1 − matte) + fill
```
```python
import cv2, numpy as np
fill, matte, bg = cv2.VideoCapture('object_line_1.mp4'), cv2.VideoCapture('object_line_1_matte.mp4'), cv2.VideoCapture('배경.mp4')
ok1, F = fill.read(); ok2, M = matte.read(); ok3, B = bg.read()
a = M[..., :1].astype(np.float32) / 255
out = np.clip(B.astype(np.float32) * (1 - a) + F.astype(np.float32), 0, 255).astype(np.uint8)
```
같은 판의 `.json` 에 장면 시작 시각 · 반전 시각 · 스토리 법칙 → 오브제 동작 대응표가 있습니다.
"""


def main():
    ap = argparse.ArgumentParser(description='4팀 전달용 오브제 영상 (A 합성 · B 투명도)')
    ap.add_argument('--only', type=int, nargs='+', default=[1, 2, 3])
    ap.add_argument('--mode', choices=['both', 'integrated', 'alpha'], default='both')
    ap.add_argument('--stories', default='stories', help='dream_scenes_1~3.json 이 있는 폴더')
    ap.add_argument('--objects', default='output_objects_', help='오브제 폴더 앞부분 (output_objects_1 …)')
    ap.add_argument('--out', default=r'D:\renders\team4')
    ap.add_argument('--bg-dir', default=r'D:\renders\team4bg')
    ap.add_argument('--ref', default='origin/team4')
    ap.add_argument('--extra', nargs=argparse.REMAINDER, default=[], help='오브제 엔진에 그대로 넘길 옵션 (시험용)')
    args = ap.parse_args()
    out, bgdir = Path(args.out), Path(args.bg_dir)
    out.mkdir(parents=True, exist_ok=True)
    eng = [sys.executable, HERE / 'object_engine.py']
    ok_all, rows = True, []
    for k in args.only:
        print(f'\n=== {k}판 ({EMO.get(k, "")}) ===')
        story, objs = Path(args.stories) / f'dream_scenes_{k}.json', f'{args.objects}{k}'
        base = eng + ['--story', story, '--objects', objs] + args.extra
        if args.mode in ('both', 'integrated'):
            bg = bgdir / f'bg{k}.mp4'
            if fetch_bg(k, bg, args.ref):
                ok_all &= run(base + ['--bg', bg, '--bg-audio', '--out', out / f'team4_integrated_{k}.mp4'])
            else:
                ok_all = False
        if args.mode in ('both', 'alpha'):
            ok_all &= run(base + ['--alpha-out', '--out', out / f'object_line_{k}.mp4'])
        rows.append(f'| {k}판 | {EMO.get(k, "")} | `team4_integrated_{k}.mp4` | `object_line_{k}.mp4` | `object_line_{k}_matte.mp4` |')
    (out / 'README_4팀.md').write_text(README.format(rows='\n'.join(rows)), encoding='utf-8')
    print(f'\n설명서 → {out / "README_4팀.md"}')
    print('모두 끝났습니다.' if ok_all else '일부 판에서 문제가 있었습니다 — 위 메시지를 확인하세요.')
    sys.exit(0 if ok_all else 1)


if __name__ == '__main__':
    main()
