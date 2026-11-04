"""
오브제 5분 렌더 — ComfyUI 없이 (목표 선화 targets.json 으로 그리는 진화 방식)
  가장 최근 배경 녹화(team3/background/output/…/dream.mp4 + video.json)를 찾아
  ① 배경 + 오브제 통합 영상  ② 4팀용 오브제만 + 투명도 영상을 한 번에 렌더한다.
  결과 폴더: team3/object/output/render_<시각>/  (make_delivery.py 가 그대로 읽는다)

  python render_objects.py                 (D:\\asd 에서)
  python render_objects.py --scene-sec 10  (빠른 시험 · 엔진 옵션을 그대로 넘긴다)
"""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STORY = ROOT / 'team3' / 'background' / 'input' / 'storyboard' / 'dream_scenes.json'
OBJ = ROOT / 'team3' / 'object'
BG_OUT = ROOT / 'team3' / 'background' / 'output'


def latest_bg():
    runs = []
    for d in (BG_OUT.iterdir() if BG_OUT.is_dir() else []):
        meta = d / 'video.json'
        vid = next((d / n for n in ('dream.mp4', 'dream.webm') if (d / n).exists()), None)
        if d.is_dir() and meta.exists() and vid:
            runs.append((meta.stat().st_mtime, vid, meta))
    return max(runs)[1:] if runs else None


def main():
    extra = sys.argv[1:]
    if not (OBJ / 'output_objects' / 'targets.json').exists():
        sys.exit('[중단] team3/object/output_objects/targets.json 이 없습니다 — 먼저 targets.py 로 목표 선화를 만드세요.')
    bg = latest_bg()
    if not bg:
        sys.exit('[중단] 배경 녹화가 없습니다 — 먼저 python team3/run_team3.py --record --storyboard … 를 돌리세요.')
    vid, meta = bg
    out = OBJ / 'output' / time.strftime('render_%Y%m%d-%H%M%S')
    out.mkdir(parents=True, exist_ok=True)
    base = [sys.executable, str(OBJ / 'object_engine.py'), '--story', str(STORY),
            '--objects', str(OBJ / 'output_objects'), '--jobs', 'auto'] + extra
    print(f'배경 영상: {vid}\n결과 폴더: {out}')
    t0 = time.time()
    for label, args in (('배경 위 통합', ['--bg', str(vid), '--bg-json', str(meta), '--out', str(out / 'dream_integrated.mp4')]),
                        ('오브제만 + 투명도 (4팀용)', ['--alpha-out', '--out', str(out / 'object_line_alpha.mp4')])):
        print(f'\n== {label} ==')
        r = subprocess.run(base + args)
        if r.returncode != 0:
            sys.exit(f'[중단] {label} 렌더 실패 (종료 코드 {r.returncode})')
    print(f'\n완료 — {int(time.time() - t0) // 60}분 · {out}')


if __name__ == '__main__':
    main()
