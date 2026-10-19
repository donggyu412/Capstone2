# -*- coding: utf-8 -*-
"""
run_team3.py — 2팀 꿈 스토리보드 → 3팀(배경 · 오브제 · 사운드 · 통합)을 잇는 연결 (10-14)

루트 run_pipeline.py 가 1팀 → 2팀(team2/output/dream_scenes.json)까지 돈다. 이 파일이 그 다음을 잇는다.

[흐름]
  1) 받기     team2/output/dream_scenes.json → team3/background/input/storyboard/dream_scenes.json
              (3팀 공용 입력 자리 — 배경 엔진·사운드는 여기를 읽고, 오브제는 --story 로 여기를 가리킨다)
              스토리보드가 바뀌었으면 그 자리에 있던 옛 판(json · 사진 · wav · prompts)을
              input/storyboard_archive/<시각>_<감정>/ 로 옮겨 둔다. 같은 판이면 그대로 둔다(다시 돌려도 안전).
  2) 프롬프트 background/tools/make_prompts.py → input/storyboard/prompts.txt (감정별 색·밝기·단순함 포함)
  3) 사진     OpenAI 키(환경변수 또는 team3/.env 의 OPENAI_API_KEY)가 있으면 없는 장면만 자동 생성한다(10-14).
              키가 없거나 --manual 이면 웹 생성기(ChatGPT)로 사람이 만든다 — 필요한 이름을 알려 주고 멈춘다.
              이미 있는 사진은 덮어쓰지 않는다(손으로 고른 사진을 지키려고).
  4) 배경     --serve 면 배경 엔진(app.py)을 띄우고 브라우저를 연다 → START → [영상 mp4 · 프레임 고정]
  4-2) 사운드 --sound → team3/sound/generate_sound.py --style apichatpong(기본) → team3/sound/output/dream_sound.wav
              오브제는 대본과 같은 판일 때만 쓴다(아니면 오브제 층 없이) · 10-17
  5) 넘기기   가장 최근 배경 결과(output/<run>/)를 찾아 오브제 · 사운드 · 통합에 넘길 명령을 출력한다
  6) 통합     --mux 영상 소리 → 영상은 다시 인코딩하지 않고 소리만 붙인다 (D · 최종 꿈 영상)
  7) 4팀      --to-team4 → 배경판 4장 · scenes.json · dream_scenes.json · 오브제 PNG · objects.json 을
              4팀 입력 자리 team4/input/(storyboard · objects)에 넣는다 (10-14 · 4팀 코드는 고치지 않음).
              4팀 DreamModel(주력 · 10-15 GridModel 삭제)은 대본의 오브제 이름과 오브제 파일이 짝이 맞아야 돌므로,
              배경판 · 오브제가 지금 대본과 같은 판일 때만 넣는다(아니면 아무것도 바꾸지 않고 멈춘다).

[사용법] (저장소 루트에서)
  python run_pipeline.py --emotion-csv team1/output/multi_test.csv    # 1·2팀
  python team3/run_team3.py                                          # 받기 → 프롬프트 → 사진 확인
  python team3/run_team3.py --images <사진 폴더>                      # 다른 곳에서 만든 사진 4장 가져오기
  python team3/run_team3.py --manual                                 # 키가 있어도 자동 생성 안 함
  python team3/run_team3.py --serve                                  # 사진까지 있으면 배경 엔진 실행
  python team3/run_team3.py --sound                                  # 사진 뒤 1팀 사운드(아피찻퐁 · 약 3분) — --record 와 같이 써도 됨
  python team3/run_team3.py --sound-only                             # 지금 공용 자리 판으로 사운드만 다시(오브제 새 판이 나온 뒤)
  python team3/run_team3.py --record                                 # START 없이 5분 배경 + 배경판 자동 기록(10-17 · 40~50분)
  python team3/run_team3.py --storyboard <다른 json>                  # 2팀 출력 대신 다른 판으로
  python team3/run_team3.py --mux 통합.mp4 dream_sound.wav            # 최종 영상(소리 붙이기)
  python team3/run_team3.py --to-team4                               # 4팀 입력 자리 채우기
  python team3/run_team3.py --to-team4 --check                       # 한 판인지 확인만 (쓰지 않음)
  python team3/run_team3.py --to-team4 --video 통합_sound.mp4          # 5분 통합 영상도 team4/input/video/ 에(10-17)

각 담당의 코드는 고치지 않고 그대로 부른다. API 키는 이 파일에 쓰지 않는다(환경변수로만).
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
import webbrowser
from datetime import datetime
from pathlib import Path

sys.dont_write_bytecode = True
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')   # 윈도우 콘솔에서 한글이 깨지지 않게

TEAM3 = Path(__file__).resolve().parent
ROOT = TEAM3.parent
BG = TEAM3 / 'background'
SLOT = BG / 'input' / 'storyboard'            # 3팀 공용 입력 자리
ARCHIVE = BG / 'input' / 'storyboard_archive'
BG_OUT = BG / 'output'
DEFAULT_STORY = ROOT / 'team2' / 'output' / 'dream_scenes.json'
OBJ_OUT = TEAM3 / 'object' / 'output_objects'  # 오브제 생성기(generate_objects_comfy.py) 기본 출력
TEAM4_INPUT = ROOT / 'team4' / 'input'          # 4팀 DreamModel/config.py input_root

N_SCENES = 4
IMAGE_EXT = ('.png', '.jpg', '.jpeg')         # app.py IMAGE_EXT 와 같게
EMO_SEVEN = ('기쁨', '슬픔', '분노', '공포', '놀람', '혐오', '중립')


def banner(title):
    print('\n' + '=' * 64 + '\n  ' + title + '\n' + '=' * 64, flush=True)


def rel(p):
    try:
        return Path(p).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(p)


def from_object(p):
    """team3/object 에서 실행할 명령에 넣을 경로 (드라이브가 다르면 절대 경로)."""
    try:
        return Path(os.path.relpath(Path(p).resolve(), TEAM3 / 'object')).as_posix()
    except ValueError:
        return str(Path(p).resolve())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ──────────────────────────────────────────────────────────
# 1) 받기
# ──────────────────────────────────────────────────────────
def load_storyboard(path):
    """읽고 형식을 확인한다. 3팀이 쓰는 칸이 없으면 여기서 멈춘다(뒤에서 조용히 비는 것보다 낫다)."""
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as e:
        sys.exit('[중단] 스토리보드를 읽지 못했습니다: %s\n  %s' % (rel(path), e))
    scenes = data.get('scenes') if isinstance(data, dict) else data
    if not isinstance(scenes, list) or not scenes:
        sys.exit('[중단] scenes 목록이 없습니다: ' + rel(path))
    for i, s in enumerate(scenes, 1):
        missing = [k for k in ('story', 'backgrounds', 'main_emotion') if not s.get(k)]
        if missing:
            sys.exit('[중단] %d번 장면에 %s 칸이 없습니다.' % (i, ', '.join(missing)))
    if len(scenes) != N_SCENES:
        print('  ※ 장면이 %d개입니다 (기승전결 %d개 기준).' % (len(scenes), N_SCENES))
    return scenes


def emotion_labels(scenes):
    out = []
    for s in scenes:
        me = s.get('main_emotion')
        lab = me.get('label') if isinstance(me, dict) else None
        out.append(lab if isinstance(lab, str) and lab else '?')
    return out


def receive(src):
    banner('1) 받기 — 2팀 스토리보드')
    src = Path(src)
    if not src.exists():
        sys.exit('[중단] 스토리보드가 없습니다: %s\n  먼저 run_pipeline.py 를 돌리거나 --storyboard 로 파일을 주세요.' % rel(src))
    scenes = load_storyboard(src)
    labels = emotion_labels(scenes)
    print('  입력: %s (%d장면)' % (rel(src), len(scenes)))
    print('  장면별 감정: ' + ' · '.join(labels))
    odd = [l for l in labels if l not in EMO_SEVEN]
    if odd:
        print('  ※ 7감정 밖의 라벨: %s (엔진은 중립으로 둔다)' % ', '.join(odd))

    SLOT.mkdir(parents=True, exist_ok=True)
    dst = SLOT / 'dream_scenes.json'
    if dst.exists() and sha(dst) == sha(src):
        print('  지금 자리와 같은 판 → 그대로 둠 (사진·프롬프트 유지)')
        save_bg_text(src)
        return scenes
    olds = [p for p in SLOT.iterdir() if p.is_file()]
    if olds:
        old_labels = '?'
        if dst.exists():
            try:
                old_labels = ''.join(emotion_labels(load_storyboard(dst)))
            except SystemExit:
                pass
        box = ARCHIVE / ('%s_%s' % (datetime.now().strftime('%Y%m%d-%H%M%S'), old_labels))
        box.mkdir(parents=True)
        for p in olds:                       # 옛 판의 사진·wav 가 새 판에 끼어 짝지어지지 않게 전부 옮긴다
            shutil.move(str(p), str(box / p.name))
        print('  옛 판 %d개 파일 → %s' % (len(olds), rel(box)))
    # 다른 .json 을 이 자리에 두지 않는다 — 엔진·사운드가 '가장 최근 json'을 스토리보드로 읽는다.
    shutil.copyfile(src, dst)
    print('  저장: ' + rel(dst))
    save_bg_text(src)
    return scenes


def save_bg_text(src):
    """2팀이 배경마다 뽑아 둔 근거 문장(team2/output/scene{N}_elements.json '배경')을
       SLOT/background_text.txt 로 둔다 — make_prompts.py 가 '장소 묘사'로 쓴다(오브제 섞인 문장은 거기서 뺀다).
       .json 이 아니게 둔다: 엔진·사운드가 '가장 최근 json'을 스토리보드로 읽는다. 파일이 없으면 아무것도 안 한다."""
    src = Path(src)
    lines = []
    for f in sorted(src.parent.glob('scene*_elements.json')):
        no = ''.join(ch for ch in f.stem if ch.isdigit())
        try:
            items = json.loads(f.read_text(encoding='utf-8')).get('배경') or []
        except (OSError, ValueError):
            continue
        for e in items:
            t = (e.get('근거문장') or '').strip() if isinstance(e, dict) else ''
            if no and t:
                lines.append('%s\t%s' % (int(no), ' '.join(t.split())))
    if not lines:
        return
    # 근거 문장 파일이 스토리보드보다 오래됐으면 다른 판의 것일 수 있다 → 쓰지 않는다
    if min(f.stat().st_mtime for f in src.parent.glob('scene*_elements.json')) < src.stat().st_mtime - 3600:
        print('  ※ scene*_elements.json 이 스토리보드보다 1시간 넘게 오래됨 → 배경 글 안 씀')
        return
    out = SLOT / 'background_text.txt'
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('  배경 글(근거 문장 %d줄) → %s' % (len(lines), rel(out)))


# ──────────────────────────────────────────────────────────
# 2) 프롬프트
# ──────────────────────────────────────────────────────────
def prompts():
    banner('2) 배경 프롬프트')
    env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    r = subprocess.run([sys.executable, '-B', str(BG / 'tools' / 'make_prompts.py')], cwd=str(BG), env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8')
    if r.returncode != 0:
        print(r.stdout)
        sys.exit('[중단] make_prompts.py 오류 (종료 코드 %d)' % r.returncode)
    print('  저장: ' + rel(SLOT / 'prompts.txt'))


# ──────────────────────────────────────────────────────────
# 3) 사진
# ──────────────────────────────────────────────────────────
def find_image(folder, n):
    for ext in IMAGE_EXT:
        p = Path(folder) / ('scene_%02d%s' % (n, ext))
        if p.exists():
            return p
    return None


def import_images(folder):
    """다른 곳(다른 노트북 · 시험 폴더)에서 만든 scene_01~04 를 공용 자리로 복사한다."""
    folder = Path(folder)
    got = 0
    for n in range(1, N_SCENES + 1):
        p = find_image(folder, n)
        if p is None:
            continue
        for old in (find_image(SLOT, n),):
            if old is not None and old.name != p.name:
                old.unlink()                 # 확장자가 다른 옛 사진이 먼저 읽히지 않게
        shutil.copyfile(p, SLOT / p.name)
        got += 1
    print('  사진 %d장 가져옴 ← %s' % (got, rel(folder)))


def openai_key():
    """환경변수 → team3/.env 순서. 키는 출력하지 않는다(.env 는 .gitignore 대상)."""
    key = os.environ.get('OPENAI_API_KEY', '').strip()
    env = TEAM3 / '.env'
    if not key and env.exists():
        for line in env.read_text(encoding='utf-8-sig').splitlines():
            k, _, v = line.partition('=')
            if k.strip() == 'OPENAI_API_KEY':
                key = v.strip().strip('"\'')
    return key or None


def scene_prompts(folder):
    """prompts.txt 와 같은 문장을 장면 번호별로 만든다 (make_prompts.py 의 규칙을 그대로 쓴다)."""
    sys.path.insert(0, str(BG / 'tools'))
    sys.path.insert(0, str(BG))
    cwd = os.getcwd()
    os.chdir(BG)                             # app.py 가 상대 경로로 db 를 읽는다
    try:
        import make_prompts as mp
        rows = mp.app.read_scene_list(str(Path(folder) / 'dream_scenes.json')) or []
        out = {}
        bg_file = mp.load_bg_text(str(folder))
        for i, row in enumerate(rows):
            sc = mp.app.to_scene(i, len(rows), row, str(folder))
            all_objects = [o for o in (row.get('objects') or []) if isinstance(o, str)]
            bg_text, _ = mp.bg_sentences(row, bg_file.get(row.get('_num', i + 1)), all_objects)
            objects, _ = mp.split_objects(sc['backgrounds'] or [], all_objects)
            out[sc['act']] = mp.build_prompt(sc, objects, bg_text)
        return out
    finally:
        os.chdir(cwd)


def make_images_openai(folder, key, model, quality, only_missing=True):
    """OpenAI 이미지 API 로 scene_NN.png 를 만든다. 가로 1536×1024 로 받아 가운데를 16:9 로 자른다
       (웹 ChatGPT 사진과 같은 비율 — 엔진은 그 비율에 맞춰 조정해 왔다). 만든 장 수를 돌려준다."""
    import base64
    import io
    from openai import OpenAI
    from PIL import Image
    client = OpenAI(api_key=key)
    folder = Path(folder)
    log = []
    made = 0
    for n, prompt in sorted(scene_prompts(folder).items()):
        if only_missing and find_image(folder, n):
            print('  scene_%02d  이미 있음 → 건너뜀' % n)
            continue
        print('  scene_%02d  생성 중 (%s · %s)...' % (n, model, quality), flush=True)
        t0 = time.time()
        try:
            r = client.images.generate(model=model, prompt=prompt, size='1536x1024', quality=quality, n=1)
        except Exception as e:               # 키·잔액·모델 이름 문제는 여기서 드러난다 → 수동으로 돌아간다
            print('  [실패] %s' % e)
            break
        img = Image.open(io.BytesIO(base64.b64decode(r.data[0].b64_json))).convert('RGB')
        w, h = img.size
        ch = round(w * 9 / 16)
        img = img.crop((0, (h - ch) // 2, w, (h - ch) // 2 + ch))
        img.save(folder / ('scene_%02d.png' % n))
        made += 1
        log.append('scene_%02d.png · %s · %s · %.0f초\n  %s' % (n, model, quality, time.time() - t0, prompt))
        print('  scene_%02d  저장 (%dx%d · %.0f초)' % (n, img.size[0], img.size[1], time.time() - t0))
    if log:                                  # .txt — .json 이면 엔진이 스토리보드로 착각한다
        with open(folder / 'images_log.txt', 'a', encoding='utf-8-sig') as f:
            f.write('\n'.join(['# ' + datetime.now().strftime('%Y-%m-%d %H:%M')] + log) + '\n\n')
    return made


def images(n_scenes, backend='manual', model='gpt-image-2', quality='medium'):
    banner('3) 배경 사진 (%s)' % ('웹 생성기 · 수동' if backend == 'manual' else 'OpenAI ' + model))
    if backend == 'openai':
        key = openai_key()
        if key is None:
            print('  OPENAI_API_KEY 가 없습니다 (환경변수 또는 team3/.env) → 수동으로 진행')
        else:
            make_images_openai(SLOT, key, model, quality)
    missing = []
    for n in range(1, n_scenes + 1):
        p = find_image(SLOT, n)
        print('  scene_%02d  %s' % (n, p.name if p else '없음'))
        if p is None:
            missing.append('scene_%02d.png' % n)
    if missing:
        print('\n  → %s 의 장면별 문장으로 사진을 만들어' % rel(SLOT / 'prompts.txt'))
        print('    %s 에 %s 로 저장한 뒤 다시 실행하세요.' % (rel(SLOT), ', '.join(missing)))
        print('    (다른 폴더에 만들었으면: python team3/run_team3.py --images <그 폴더>)')
        return False
    return True


# ──────────────────────────────────────────────────────────
# 4) 배경 엔진
# ──────────────────────────────────────────────────────────
def serve():
    banner('4) 배경 엔진')
    url = 'http://127.0.0.1:5000/?size=1920x1080'
    print('  %s → START → [영상 mp4 · 프레임 고정] (5분 · 다른 무거운 작업과 같이 돌리지 않기)' % url)
    print('  배경판 PNG(4팀)는 [장면 저장]. 끝나면 Ctrl+C 로 서버 종료 → 다시 실행해 넘길 명령 확인.\n')
    p = subprocess.Popen([sys.executable, '-B', 'app.py'], cwd=str(BG))
    time.sleep(3)
    webbrowser.open(url)
    try:
        p.wait()
    except KeyboardInterrupt:
        p.terminate()


def find_chrome():
    for p in (os.environ.get('PROGRAMFILES', r'C:\Program Files') + r'\Google\Chrome\Application\chrome.exe',
              os.environ.get('PROGRAMFILES(X86)', r'C:\Program Files (x86)') + r'\Google\Chrome\Application\chrome.exe',
              os.environ.get('LOCALAPPDATA', '') + r'\Google\Chrome\Application\chrome.exe'):
        if p and Path(p).exists():
            return p
    return shutil.which('chrome') or shutil.which('google-chrome')


def record(sec=None):
    """사람이 START 를 누르던 5분 기록을 헤드리스로 한다 (10-17). 시험 서버(5055) + 헤드리스 크롬(9333) →
       tools/record.mjs 가 [영상 mp4 · 프레임 고정] 한 바퀴 + [장면 저장](4팀 배경판)을 같이 찍고 끈다.
       사용자 서버(5000)는 건드리지 않는다. 8GB PC 에서는 약 40~50분 · 다른 프로그램을 닫고 단독으로."""
    import tempfile
    import urllib.request
    banner('4) 배경 엔진 — 헤드리스 기록 (%s)' % ('장면당 %g초 · 시험' % sec if sec else '5분'))
    chrome, node = find_chrome(), shutil.which('node')
    if not chrome or not node:
        sys.exit('[중단] %s 가 없습니다 → --serve 로 브라우저에서 직접 기록하세요.' % ('크롬' if not chrome else 'node'))
    url = 'http://127.0.0.1:5055/?size=1920x1080' + ('&sec=%g' % sec if sec else '')
    env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    srv = subprocess.Popen([sys.executable, '-B', '-c', 'import app; app.app.run(port=5055, debug=False)'],
                           cwd=str(BG), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    profile = tempfile.mkdtemp(prefix='team3_rec_')
    chr_ = None
    try:
        for _ in range(60):                  # 서버가 뜰 때까지 (db 를 읽느라 몇 초 걸린다)
            try:
                urllib.request.urlopen('http://127.0.0.1:5055/', timeout=2)
                break
            except Exception:
                if srv.poll() is not None:
                    sys.exit('[중단] 배경 엔진 서버가 꺼졌습니다 (5055 포트를 다른 프로그램이 쓰는지 확인)')
                time.sleep(1)
        chr_ = subprocess.Popen([chrome, '--headless=new', '--remote-debugging-port=9333', '--user-data-dir=' + profile,
                                 '--mute-audio', '--window-size=1280,720', 'about:blank'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(5)
        print('  %s · 진행은 1분마다 표시 (멈추려면 Ctrl+C)' % url, flush=True)
        rc = subprocess.run([node, str(BG / 'tools' / 'record.mjs'), '9333', url]).returncode
    except KeyboardInterrupt:
        rc = 1
        print('\n  중단')
    finally:
        for p in (chr_, srv):                # 크롬은 자식 프로세스가 많아 트리째 끈다
            if p and p.poll() is None:
                subprocess.run(['taskkill', '/T', '/F', '/PID', str(p.pid)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        shutil.rmtree(profile, ignore_errors=True)
    bg = latest_background()
    if rc != 0 or bg is None:
        sys.exit('[중단] 기록이 끝나지 않았습니다 → 메모리가 부족하면 다른 프로그램을 닫거나 --serve 로 직접 기록하세요.')
    print('  저장: %s' % rel(bg[0]))


# ──────────────────────────────────────────────────────────
# 5) 넘기기
# ──────────────────────────────────────────────────────────
def latest_background():
    """가장 최근 배경 결과 폴더(영상 + video.json). 이번 스토리보드보다 오래된 것은 빼고 본다."""
    if not BG_OUT.is_dir():
        return None
    story_t = (SLOT / 'dream_scenes.json').stat().st_mtime
    runs = []
    for d in BG_OUT.iterdir():
        meta = d / 'video.json'
        vid = next((d / n for n in ('dream.mp4', 'dream.webm') if (d / n).exists()), None)
        if d.is_dir() and meta.exists() and vid and meta.stat().st_mtime > story_t:
            runs.append((meta.stat().st_mtime, vid, meta))
    return max(runs)[1:] if runs else None


def handoff():
    banner('5) 넘기기 — 오브제 · 사운드 · 통합')
    story = from_object(SLOT / 'dream_scenes.json')
    bg = latest_background()
    if bg is None:
        print('  이번 스토리보드로 찍은 배경 영상이 아직 없습니다 → --record(자동) 또는 --serve(브라우저)로 기록하세요.')
    else:
        print('  배경: %s · %s' % (rel(bg[0]), rel(bg[1])))
    print('\n  [B 오브제 · 오브제 담당 PC] (교수님 10/15: 선화 · 어린아이 로봇이 그리는 과정 = 엔진 기본)')
    print('    cd team3/object')
    print('    python generate_objects_comfy.py --story %s' % story)
    print('    ※ 오브제 PNG 는 반드시 이 대본으로 새로 만든다 — 엔진은 이름이 안 맞아도 같은 번호의 옛 PNG 를 그대로 쓴다')
    if bg:
        print('    python object_engine.py --story %s --bg %s --bg-json %s --out dream_integrated.mp4'
              % (story, from_object(bg[0]), from_object(bg[1])))
    print('    (4팀이 직접 합성할 오브제만 + 투명도: python object_engine.py --story %s --alpha-out --out object_line.mp4)'
          % story)
    wav = SOUND / 'output' / 'dream_sound.wav'
    story_t = (SLOT / 'dream_scenes.json').stat().st_mtime
    print('\n  [C 사운드 · 1팀 생성기 · 아피찻퐁] (교수님 10/8 · 10/15) — 이 PC 에서 약 3분')
    if wav.exists() and wav.stat().st_mtime > story_t:
        print('    이번 판 사운드 있음: %s' % rel(wav))
    print('    python team3/run_team3.py --sound-only   (오브제가 이 판으로 나온 뒤에 돌리면 오브제 소리까지)')
    print('\n  [4팀] 배경 엔진 [장면 저장] → 이 판 오브제가 나오면: python team3/run_team3.py --to-team4')
    print('\n  [D 통합] python team3/run_team3.py --mux <dream_integrated.mp4> <dream_sound.wav>')
    print('\n  [4팀 · 통합 영상까지] python team3/run_team3.py --to-team4 --video <dream_integrated_sound.mp4>')


# ──────────────────────────────────────────────────────────
# 4-2) 사운드 — 1팀 사운드 생성기(team3/sound · 10-16 아피찻퐁)를 공용 자리 판으로 돌린다 (10-17)
# ──────────────────────────────────────────────────────────
SOUND = TEAM3 / 'sound'


def sound(style='apichatpong', objects=None):
    """공용 자리의 스토리보드 · 사진(+ 같은 판 오브제)으로 5분 사운드 → team3/sound/output/dream_sound.wav.
       오브제가 다른 판이면 그 오브제로 소리를 만들지 않는다(10-17 시험: 옛 판 오브제 소리가 섞였다) —
       오브제 층 없이 배경 · 글로만 만들고, 새 판 오브제가 나오면 --sound-only 로 다시 만든다.
       생성기는 끝까지 성공했을 때만 output/ 을 갈아 끼운다(중간에 멈춰도 이전 결과는 남는다)."""
    banner('4-2) 사운드 — 1팀 생성기 · 스타일 %s' % style)
    story = SLOT / 'dream_scenes.json'
    rows = load_storyboard(story)
    obj_dir = Path(objects) if objects else OBJ_OUT
    problems, _ = check_objects(rows, obj_dir)
    tmp = None
    if problems or obj_dir.name != 'output_objects':
        tmp = Path(tempfile.mkdtemp(prefix='team3_noobj_'))    # 빈 폴더 = 생성기가 '오브제 층 없이' 진행
        base = tmp
        why = problems[0].split('\n')[0] if problems else '오브제 폴더 이름이 output_objects 가 아님'
        print('  ※ 오브제 없이 만든다 — %s' % why)
        print('    (이 판 오브제가 %s 에 나오면: python team3/run_team3.py --sound-only)' % rel(OBJ_OUT))
    else:
        base = obj_dir.parent                                    # 생성기는 <base>/output_objects/ 를 읽는다
        print('  오브제: %s (대본과 같은 판)' % rel(obj_dir))
    cmd = [sys.executable, str(SOUND / 'generate_sound.py'), '--style', style,
           '--scenes', str(story), '--objects', str(base)]
    env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    t0 = time.time()
    sys.stdout.flush()                                           # 안내가 생성기 출력보다 먼저 보이게
    try:
        r = subprocess.run(cmd, cwd=str(ROOT), env=env)
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    if r.returncode != 0:
        sys.exit('[중단] 사운드 생성 오류 (종료 코드 %d) — 이전 결과(team3/sound/output/)는 그대로' % r.returncode)
    wav = SOUND / 'output' / 'dream_sound.wav'
    print('  사운드: %s · %.0f초 걸림' % (rel(wav), time.time() - t0))
    return wav


# ──────────────────────────────────────────────────────────
# 6) 통합 — 소리 붙이기
# ──────────────────────────────────────────────────────────
def mux(video, audio, out=None):
    banner('6) 통합 — 영상에 소리 붙이기')
    try:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        sys.exit('[중단] ffmpeg 가 없습니다 (pip install imageio-ffmpeg)')
    video, audio = Path(video), Path(audio)
    for p in (video, audio):
        if not p.exists():
            sys.exit('[중단] 파일이 없습니다: ' + str(p))
    out = Path(out) if out else video.with_name(video.stem + '_sound.mp4')
    cmd = [ffmpeg, '-y', '-v', 'error', '-i', str(video), '-i', str(audio),
           '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest', str(out)]
    if subprocess.run(cmd).returncode != 0:
        sys.exit('[중단] ffmpeg 오류')
    print('  저장: %s (%.0fMB) — 영상은 다시 인코딩하지 않음' % (out, out.stat().st_size / 1048576))


# ──────────────────────────────────────────────────────────
# 7) 4팀 — 입력 자리 채우기
# ──────────────────────────────────────────────────────────
def nfc(t):
    return unicodedata.normalize('NFC', str(t)).strip()


def latest_plates(story_t):
    """가장 최근 [장면 저장] 결과(scene_01~04.png + scenes.json). 이번 스토리보드보다 오래된 것은 뺀다."""
    if not BG_OUT.is_dir():
        return None
    runs = []
    for d in BG_OUT.iterdir():
        meta = d / 'scenes.json'
        if d.is_dir() and meta.exists() and meta.stat().st_mtime > story_t:
            runs.append((meta.stat().st_mtime, d))
    return max(runs)[1] if runs else None


def check_team4(story_path, plates, objects):
    """4팀에 넘길 묶음이 한 판인지 확인한다. (문제 목록, 배경판 파일, 오브제 파일)을 돌려준다."""
    problems = []
    rows = load_storyboard(story_path)
    labels = emotion_labels(rows)
    plate_files, obj_files = [], []

    # 배경판 — 4팀은 scenes.json 의 act · files.background 로 찾고, 감정이 대본과 다르면 DreamModel 이 멈춘다
    if plates is None:
        problems.append('이번 스토리보드로 찍은 배경판([장면 저장] 결과)이 없습니다 → --serve 로 엔진을 띄워 [장면 저장]')
    else:
        metas = json.loads((plates / 'scenes.json').read_text(encoding='utf-8-sig')).get('scenes', [])
        if len(metas) != len(rows):
            problems.append('배경판 %d장 · 대본 %d장면 — 수가 다릅니다 (%s)' % (len(metas), len(rows), rel(plates)))
        for i, m in enumerate(metas, 1):
            name = (m.get('files') or {}).get('background') or 'scene_%02d.png' % i
            if not (plates / name).exists():
                problems.append('배경판 파일이 없습니다: ' + rel(plates / name))
            plate_files.append(plates / name)
            if i <= len(labels) and m.get('emotion') != labels[i - 1]:
                problems.append('장면 %d 감정이 다릅니다 — 배경판 %s · 대본 %s (다른 판의 배경판)'
                                % (i, m.get('emotion'), labels[i - 1]))

    obj_problems, obj_files = check_objects(rows, objects)
    return problems + obj_problems, plate_files, obj_files


def check_objects(rows, objects):
    """오브제가 대본과 한 판인지 — 대본 objects 와 objects.json name_ko 가 장면마다 같은 순서로 같아야 한다.
       (문제 목록, 오브제 파일). 4팀 넘기기와 사운드가 같이 쓴다."""
    problems, obj_files = [], []
    manifest = Path(objects) / 'objects.json'
    if not manifest.exists():
        return ['오브제 대응표가 없습니다: ' + rel(manifest)], []
    by_scene = {int(sc['scene']): sc.get('objects', [])
                for sc in json.loads(manifest.read_text(encoding='utf-8-sig')).get('scenes', [])}
    for i, row in enumerate(rows, 1):
        want = [nfc(o) for o in (row.get('objects') or []) if isinstance(o, str)]
        ents = sorted(by_scene.get(i, []), key=lambda e: e.get('index', 0))
        have = [nfc(e.get('name_ko', '')) for e in ents]
        if have != want:
            problems.append('장면 %d 오브제가 대본과 다릅니다 (다른 판의 오브제)\n      대본  : %s\n      오브제: %s'
                            % (i, ' · '.join(want) or '없음', ' · '.join(have) or '없음'))
            continue
        for e in ents:
            f = Path(objects) / e.get('file', '')
            if not f.is_file():
                problems.append('오브제 파일이 없습니다: ' + rel(f))
            obj_files.append(f)
    return problems, obj_files


def team4_readme(kind, plates, labels):
    lines = ['# 3팀 %s (4팀 입력 · %s · `run_team3.py --to-team4` 가 채움)' % (kind, datetime.now().strftime('%Y-%m-%d %H:%M')),
             '',
             '- 장면 감정: ' + ' · '.join(labels),
             '- 대본: `../storyboard/dream_scenes.json` (2팀 출력 → 3팀이 읽은 그대로)']
    if kind == '배경판':
        lines += ['- `scene_01~04.png`: 글자 없는 배경판 · 1920×1080 · 장면 한가운데 한 순간 (3팀 배경 결과 `%s`)' % plates.name,
                  '- `scenes.json`: 장면별 정보 (act · 감정 · files.background)']
    else:
        lines += ['- `scene_0N/obj_<순번>_<이름>.png`: 투명 PNG · `<순번>` 은 그 장면 objects 배열 순서(1부터)',
                  '- `objects.json`: 장면 · 순번 · 이름 · 파일 대응표']
    lines += ['- 규격: 30fps · 5:00 · 장면당 75초 · 클라이맥스 반전 3:15 (전 장면 45초)', '']
    return '\n'.join(lines)


def video_info(path):
    """(길이 초, 소리 있음) — ffmpeg -i 의 안내 글에서 읽는다 (ffprobe 는 imageio-ffmpeg 에 없다)."""
    import re
    try:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        return None, None
    err = subprocess.run([ffmpeg, '-hide_banner', '-i', str(path)], capture_output=True,
                         text=True, encoding='utf-8', errors='replace').stderr
    m = re.search(r'Duration: (\d+):(\d+):([\d.]+)', err)
    sec = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else None
    return sec, 'Audio:' in err


def check_video(video):
    """4팀에 넘길 5분 통합 영상(배경 · 오브제 · 사운드) 확인 — 문제 목록."""
    video = Path(video)
    if not video.is_file():
        return ['통합 영상이 없습니다: ' + str(video)]
    sec, audio = video_info(video)
    problems = []
    if sec is None:
        problems.append('통합 영상 길이를 읽지 못했습니다 (ffmpeg 확인): ' + video.name)
    elif abs(sec - 300) > 2:
        problems.append('통합 영상이 5:00 이 아닙니다 (%d:%04.1f) — %s' % (sec // 60, sec % 60, video.name))
    if audio is False:
        problems.append('통합 영상에 소리가 없습니다 → 먼저 --mux 로 사운드를 붙이세요: ' + video.name)
    return problems


def to_team4(story_path, plates_dir=None, objects_dir=None, team4_input=None, check_only=False, video=None):
    banner('7) 4팀 — 입력 자리 채우기')
    story_path = Path(story_path)
    if not story_path.exists():
        sys.exit('[중단] 스토리보드가 없습니다: ' + rel(story_path))
    dst = Path(team4_input) if team4_input else TEAM4_INPUT
    plates = Path(plates_dir) if plates_dir else latest_plates(story_path.stat().st_mtime)
    objects = Path(objects_dir) if objects_dir else OBJ_OUT
    labels = emotion_labels(load_storyboard(story_path))
    print('  대본  : %s (%s)' % (rel(story_path), ' · '.join(labels)))
    print('  배경판: %s' % (rel(plates) if plates else '없음'))
    print('  오브제: %s' % rel(objects))
    print('  통합 영상: %s' % (video or '없음 (--video 로 5분 통합 영상도 넘길 수 있다)'))
    print('  넣을 곳: %s' % rel(dst))

    problems, plate_files, obj_files = check_team4(story_path, plates, objects)
    if video:
        problems += check_video(video)
    if problems:
        print('\n  [멈춤] 4팀 입력 자리는 그대로 둡니다 — 4팀 모델은 대본 · 배경판 · 오브제가 한 판이어야 돈다:')
        for p in problems:
            print('    - ' + p)
        sys.exit(2)
    print('  확인: 대본 · 배경판 %d장 · 오브제 %d장이 한 판%s'
          % (len(plate_files), len(obj_files), ' · 통합 영상 5:00 · 소리 있음' if video else ''))
    if check_only:
        print('  (--check — 쓰지 않음)')
        return
    if not dst.is_dir():
        sys.exit('[중단] 4팀 입력 자리가 없습니다: %s\n  team4 를 합친 저장소에서 실행하거나 --team4-dir 로 가리키세요.' % rel(dst))

    sb, ob = dst / 'storyboard', dst / 'objects'
    sb.mkdir(exist_ok=True)
    ob.mkdir(exist_ok=True)
    # 옛 판을 지운다 — 남으면 4팀이 obj_<순번>_ 파일을 여러 개 찾거나 옛 배경판을 읽는다. 소리 파일은 건드리지 않는다.
    for p in list(sb.iterdir()):
        if p.is_file() and (p.name in ('scenes.json', 'dream_scenes.json') or
                            (p.name.startswith('scene_') and p.suffix.lower() in IMAGE_EXT)):
            p.unlink()
    for p in list(ob.iterdir()):
        if p.is_dir() and p.name.startswith('scene_'):
            for f in p.iterdir():
                if f.is_file() and f.suffix.lower() in IMAGE_EXT:
                    f.unlink()
            if not any(p.iterdir()):
                p.rmdir()
        elif p.name == 'objects.json':
            p.unlink()

    for f in plate_files:
        shutil.copyfile(f, sb / f.name)
    shutil.copyfile(plates / 'scenes.json', sb / 'scenes.json')
    shutil.copyfile(story_path, sb / 'dream_scenes.json')
    for f in obj_files:
        out = ob / f.relative_to(objects)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(f, out)
    shutil.copyfile(objects / 'objects.json', ob / 'objects.json')
    (sb / 'README.md').write_text(team4_readme('배경판', plates, labels), encoding='utf-8')
    (ob / 'README.md').write_text(team4_readme('오브제', plates, labels), encoding='utf-8')
    print('  저장: %s (배경판 %d · json 2) · %s (오브제 %d · objects.json)'
          % (rel(sb), len(plate_files), rel(ob), len(obj_files)))
    if video:                                # 4팀 결과물과 나란히 보여 줄 3팀 최종 꿈 영상 (10-17 사용자 요청)
        vd = dst / 'video'
        vd.mkdir(exist_ok=True)
        shutil.copyfile(video, vd / 'dream_final.mp4')
        (vd / 'README.md').write_text(
            '# 3팀 통합 영상 (4팀 입력 · %s · `run_team3.py --to-team4 --video` 가 채움)\n\n'
            '- 장면 감정: %s\n'
            '- `dream_final.mp4`: 배경 · 오브제 · 사운드를 합친 5:00 최종 꿈 영상 (원본 `%s`)\n'
            '- 대본 · 배경판 · 오브제와 같은 판\n'
            % (datetime.now().strftime('%Y-%m-%d %H:%M'), ' · '.join(labels), Path(video).name), encoding='utf-8')
        print('  저장: %s (통합 영상 %.0fMB)' % (rel(vd / 'dream_final.mp4'), (vd / 'dream_final.mp4').stat().st_size / 1048576))
    print('  → 4팀이 DreamModel 을 실행한다 (소리는 4팀이 input 아래에 둔다)')


def main():
    ap = argparse.ArgumentParser(description='2팀 스토리보드 → 3팀 배경 · 오브제 · 사운드 · 통합 연결')
    ap.add_argument('--storyboard', help='기본: team2/output/dream_scenes.json (--to-team4 는 3팀 공용 입력 자리)')
    ap.add_argument('--images', help='scene_01~04 사진이 있는 폴더 (공용 자리로 복사)')
    ap.add_argument('--manual', action='store_true', help='OpenAI 키가 있어도 사진을 자동 생성하지 않음')
    ap.add_argument('--image-model', default='gpt-image-2', help='OpenAI 이미지 모델 (기본 gpt-image-2)')
    ap.add_argument('--image-quality', default='medium', choices=['low', 'medium', 'high'])
    ap.add_argument('--serve', action='store_true', help='사진이 다 있으면 배경 엔진을 띄운다')
    ap.add_argument('--record', action='store_true',
                    help='사진이 다 있으면 5분 배경 영상 + 배경판을 헤드리스로 기록 (START 안 눌러도 됨 · 40~50분)')
    ap.add_argument('--record-sec', type=float, help='--record 시험용: 장면당 초 (기본 75 = 5분)')
    ap.add_argument('--sound', action='store_true',
                    help='사진까지 끝나면 1팀 사운드 생성기로 5분 사운드를 만든다 (이 PC 약 3분 · 오브제는 같은 판일 때만)')
    ap.add_argument('--sound-only', action='store_true',
                    help='받기 · 사진을 거치지 않고 지금 공용 자리 판으로 사운드만 다시 만든다')
    ap.add_argument('--sound-style', default='apichatpong',
                    help='사운드 스타일 (기본 apichatpong — 교수님 10/15 · 그 밖에 default · apichatpong_deep · apichatpong_synth)')
    ap.add_argument('--mux', nargs=2, metavar=('VIDEO', 'AUDIO'), help='최종 영상: 영상에 소리만 붙인다')
    ap.add_argument('--out', help='--mux 결과 파일 (기본: <영상>_sound.mp4)')
    ap.add_argument('--to-team4', action='store_true', help='4팀 입력 자리(team4/input)에 배경판 · 오브제를 넣는다')
    ap.add_argument('--check', action='store_true', help='--to-team4 와 함께: 한 판인지 확인만 하고 쓰지 않음')
    ap.add_argument('--plates', help='--to-team4 배경판 폴더 (기본: 가장 최근 [장면 저장] 결과)')
    ap.add_argument('--objects', help='--to-team4 · --sound 오브제 폴더 (기본: team3/object/output_objects)')
    ap.add_argument('--team4-dir', help='--to-team4 넣을 곳 (기본: team4/input)')
    ap.add_argument('--video', help='--to-team4 와 함께: 5분 통합 영상(배경 · 오브제 · 사운드)도 team4/input/video/ 에 넣는다')
    a = ap.parse_args()

    if a.mux:
        mux(a.mux[0], a.mux[1], a.out)
        return
    if a.sound_only:                         # 받기를 거치지 않는다 — 공용 자리 판 그대로
        sound(a.sound_style, a.objects)
        return
    if a.to_team4:                           # 받기를 거치지 않는다 — 공용 자리를 2팀 새 출력으로 바꾸지 않게
        to_team4(a.storyboard or SLOT / 'dream_scenes.json', a.plates, a.objects, a.team4_dir, a.check, a.video)
        return
    scenes = receive(a.storyboard or DEFAULT_STORY)
    prompts()
    if a.images:
        import_images(a.images)
    backend = 'manual' if a.manual or openai_key() is None else 'openai'
    if not images(len(scenes), backend, a.image_model, a.image_quality):
        sys.exit(2)
    if a.sound:
        sound(a.sound_style, a.objects)
    if a.record:
        record(a.record_sec)
    elif a.serve:
        serve()
    handoff()


if __name__ == '__main__':
    main()
