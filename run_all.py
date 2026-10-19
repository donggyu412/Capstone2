# -*- coding: utf-8 -*-
"""
run_all.py — 1팀 → 2팀 → 3팀 → 4팀을 한 줄로 (10-20)

각 팀 코드는 고치지 않고, 이미 따로 시험한 명령을 순서대로 부른다.
시작 전에 키 · ComfyUI · 4팀 실행 환경을 먼저 검사하고, 어느 단계에서 멈췄는지 알려 준다.

[단계]
  1  1·2팀   python run_pipeline.py <1팀 입력>          감정 → 꿈 이야기 4장면
  2  3팀     python team3/run_team3.py --record          배경 사진 4장 → 5분 배경 영상 + 배경판
  3  3팀     python team3/run_team3.py --object --alpha  오브제 PNG(ComfyUI) → 오브제 영상 (GPU PC)
  4  3팀     python team3/run_team3.py --sound-only      오브제까지 넣은 5분 사운드
  5  3팀     --mux (3팀 최종 꿈 영상) → --to-team4 --video   4팀 입력 폴더 채우기
  6  4팀     team4/main.py                               4팀 최종 영상 team4/output/team4_output.mp4

[사용법] (저장소 루트에서 · 오브제 생성이 되는 PC)
  python run_all.py --emotion-csv team1/output/multi_test.csv     # 처음부터 끝까지
  python run_all.py --sources 0 1 --narration <파일>               # 실제 촬영으로 시작
  python run_all.py --check --emotion-csv <CSV>                    # 준비 상태만 검사 (아무것도 돌리지 않음)
  python run_all.py --from 3                                       # 3단계부터 다시 (앞 단계 결과는 그대로)
  python run_all.py --emotion-csv <CSV> --until 5                  # 5단계(4팀 넘기기)까지만
  python run_all.py --emotion-csv <CSV> --quick                    # 빠른 시험 (배경 장면당 5초 · 오브제 40초)
1팀 입력(--emotion-csv · --sources · --narration 등)은 run_pipeline.py 에 그대로 넘긴다.
"""
import argparse
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parent
PY = sys.executable
TEAM3_RUN = ROOT / 'team3' / 'run_team3.py'
OBJ_RESULT = ROOT / 'team3' / 'object' / 'output'
SOUND_WAV = ROOT / 'team3' / 'sound' / 'output' / 'dream_sound.wav'
TEAM4 = ROOT / 'team4'
TEAM4_VENV_PY = TEAM4 / 'DreamModel' / '.venv' / 'Scripts' / 'python.exe'
TEAM4_PY = TEAM4_VENV_PY if TEAM4_VENV_PY.exists() else Path(PY)
TEAM4_INPUTS = [TEAM4 / 'input' / 'background' / 'dream_background.mp4',
                TEAM4 / 'input' / 'background' / 'scenes.json',
                TEAM4 / 'input' / 'background' / 'dream_scenes.json',
                TEAM4 / 'input' / 'object' / 'object_line_1.mp4',
                TEAM4 / 'input' / 'sound' / 'dream_sound.wav']
COMFY = 'http://127.0.0.1:8188'

STEPS = {1: '1·2팀 감정 → 꿈 이야기', 2: '3팀 배경 (사진 → 5분 배경 영상)', 3: '3팀 오브제 (PNG → 오브제 영상)',
         4: '3팀 사운드', 5: '3팀 최종 영상 · 4팀에 넘기기', 6: '4팀 최종 영상'}


def env_key(name, files):
    """환경변수 → .env 파일 순서로 키가 있는지만 본다 (값은 출력하지 않음)."""
    if os.environ.get(name, '').strip():
        return True
    for f in files:
        if f.exists():
            for line in f.read_text(encoding='utf-8-sig').splitlines():
                k, _, v = line.partition('=')
                if k.strip() == name and v.strip().strip('"\''):
                    return True
    return False


def comfy_up():
    try:
        urllib.request.urlopen(COMFY + '/system_stats', timeout=3)
        return True
    except Exception:
        return False


def team4_env_ok():
    r = subprocess.run([str(TEAM4_PY), '-c', 'import torch, cv2, numpy'], capture_output=True, text=True)
    return r.returncode == 0, (r.stderr or r.stdout).strip().splitlines()[-1:] or ['']


def precheck(first, last, pipeline_args):
    """돌릴 단계에 필요한 것만 검사한다. (문제 목록)"""
    problems = []
    print('\n[준비 상태 검사]')

    def ok(cond, label, fix):
        print('  %s %s' % ('✅' if cond else '❌', label))
        if not cond:
            problems.append('%s → %s' % (label, fix))

    if first <= 1 <= last:
        ok(bool(pipeline_args), '1팀 입력 (--emotion-csv 또는 --sources)', '명령 뒤에 --emotion-csv <CSV> 를 붙이세요')
        ok(env_key('ANTHROPIC_API_KEY', [ROOT / '.env', ROOT / 'team2' / '.env']),
           'Claude 키 (루트 .env · ANTHROPIC_API_KEY)', '루트 .env 에 키를 넣으세요')
    if first <= 2 <= last:
        ok(env_key('OPENAI_API_KEY', [ROOT / 'team3' / '.env']),
           'OpenAI 키 (team3/.env · OPENAI_API_KEY)', 'team3/.env 에 키를 넣으세요')
    if first <= 3 <= last:
        ok(comfy_up(), 'ComfyUI 켜짐 (%s)' % COMFY, 'run_nvidia_gpu.bat 으로 ComfyUI 를 켜세요')
    if first <= 6 <= last:
        good, detail = team4_env_ok()
        ok(good, '4팀 실행 환경 (torch · opencv · numpy · %s)' % TEAM4_PY,
           'team4/DreamModel/.venv 에 설치하세요 (%s)' % detail[0])
    if first > 1 and first <= 6:
        need = {2: ROOT / 'team2' / 'output' / 'dream_scenes.json',
                6: TEAM4_INPUTS[0]}.get(first)
        if need is not None:
            ok(need.exists(), '앞 단계 결과 (%s)' % need.relative_to(ROOT), '앞 단계부터 다시 돌리세요')
    return problems


def run_step(n, cmd, cwd=ROOT):
    print('\n' + '━' * 70)
    print('▶ %d단계 / 6 — %s' % (n, STEPS[n]))
    print('  ' + subprocess.list2cmdline([str(c) for c in cmd]))
    print('━' * 70, flush=True)
    t0 = time.time()
    r = subprocess.run([str(c) for c in cmd], cwd=str(cwd))
    took = time.time() - t0
    if r.returncode != 0:
        stop(n, '종료 코드 %d' % r.returncode)
    print('  ✅ %d단계 끝 · %s' % (n, mmss(took)), flush=True)
    return took


def stop(n, why, resume=None):
    print('\n[멈춤] %d단계(%s)에서 멈췄습니다 — %s' % (n, STEPS[n], why))
    print('  위 메시지대로 고친 뒤:  python run_all.py --from %d' % (resume or n))
    sys.exit(2)


def mmss(sec):
    return '%d분 %02d초' % (sec // 60, sec % 60)


def latest_render(since, quick):
    """이번 실행에서 만든 오브제 렌더 폴더 (가장 최근)."""
    runs = [d for d in OBJ_RESULT.glob('render_*')
            if d.is_dir() and d.stat().st_mtime >= since and d.name.endswith('_quick') == quick]
    return max(runs, key=lambda d: d.stat().st_mtime) if runs else None


def main():
    ap = argparse.ArgumentParser(description='1팀 → 4팀 한 줄 실행 (모르는 옵션은 run_pipeline.py 로 넘김)')
    ap.add_argument('--from', dest='first', type=int, default=1, choices=range(1, 7), help='이 단계부터 (기본 1)')
    ap.add_argument('--until', dest='last', type=int, default=6, choices=range(1, 7), help='이 단계까지 (기본 6)')
    ap.add_argument('--check', action='store_true', help='준비 상태만 검사하고 끝')
    ap.add_argument('--quick', action='store_true', help='빠른 시험: 배경 장면당 5초 · 오브제 40초')
    a, pipeline_args = ap.parse_known_args()
    if a.first > a.last:
        ap.error('--from 이 --until 보다 큽니다')

    start = time.time()
    print('run_all — %d~%d단계 %s(%s)' % (a.first, a.last, '빠른 시험 ' if a.quick else '',
                                        datetime.now().strftime('%Y-%m-%d %H:%M')))
    problems = precheck(a.first, a.last, pipeline_args)
    if problems:
        print('\n[시작 안 함] 준비가 덜 됐습니다:')
        for p in problems:
            print('  - ' + p)
        sys.exit(2)
    if a.check:
        print('\n준비 완료 — --check 빼고 다시 실행하면 시작합니다.')
        return

    times = {}
    t3 = TEAM3_RUN
    if a.first <= 1 <= a.last:
        times[1] = run_step(1, [PY, 'run_pipeline.py'] + pipeline_args)
    if a.first <= 2 <= a.last:
        times[2] = run_step(2, [PY, t3, '--record'] + (['--record-sec', '5'] if a.quick else []))
    if a.first <= 3 <= a.last:
        t = time.time()
        times[3] = run_step(3, [PY, t3, '--object', '--alpha'] + (['--quick'] if a.quick else []))
        if latest_render(t, a.quick) is None:
            stop(3, '오브제 렌더 폴더가 만들어지지 않았습니다 (%s)' % OBJ_RESULT.relative_to(ROOT))
    if a.first <= 4 <= a.last:
        times[4] = run_step(4, [PY, t3, '--sound-only'])
    if a.first <= 5 <= a.last:
        story = ROOT / 'team3' / 'background' / 'input' / 'storyboard' / 'dream_scenes.json'
        render = latest_render(story.stat().st_mtime if story.exists() else 0, a.quick)   # 이 대본 뒤 렌더만 (옛 판 섞임 방지)
        if render is None:
            stop(5, '이번 대본으로 만든 오브제 렌더 결과가 없습니다', resume=3)
        cmd = [PY, t3, '--to-team4']
        integrated = render / 'dream_integrated.mp4'
        if not a.quick and integrated.is_file() and SOUND_WAV.is_file():   # 3팀 최종 꿈 영상도 같이 (--video 는 5:00 만 받음)
            run_step(5, [PY, t3, '--mux', integrated, SOUND_WAV])
            cmd += ['--video', integrated.with_name('dream_integrated_sound.mp4')]
        if a.quick:                                            # 빠른 시험 렌더는 기본 선택에서 빠지므로 직접 지정
            cmd += ['--object-video', render / 'object_line_alpha.mp4']
        t = time.time()
        times[5] = run_step(5, cmd)
        old = [p.relative_to(ROOT) for p in TEAM4_INPUTS if not p.exists() or p.stat().st_mtime < t - 1]
        if old:                                                # --to-team4 는 없는 것은 알림만 하고 넘어가므로 여기서 막는다
            stop(5, '4팀 입력 중 이번 판으로 바뀌지 않은 파일: ' + ', '.join(map(str, old)))
    if a.first <= 6 <= a.last:
        times[6] = run_step(6, [TEAM4_PY, 'main.py'], cwd=TEAM4)

    print('\n' + '═' * 70)
    print('완료 — 전체 %s' % mmss(time.time() - start))
    for n, s in times.items():
        print('  %d단계 %-28s %s' % (n, STEPS[n], mmss(s)))
    if a.last >= 6:
        print('  4팀 최종 영상: %s' % (TEAM4 / 'output' / 'team4_output.mp4'))
    if a.last >= 5:
        print('  3팀 최종 꿈 영상: team4/input/video/dream_final.mp4 (있으면)')


if __name__ == '__main__':
    main()
