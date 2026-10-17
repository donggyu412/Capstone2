"""출처 기록 — '이 소리에 남의 음원·남의 모델 출력이 섞였는가'를 실행마다 증거로 남긴다 (LICENSE_AUDIT.md 와 짝).

provenance.json 에 남기는 것
  · 조각 목록 — 조각 wav 하나하나가 어디서 왔는가 (자체 합성 함수 이름 · 시드)
  · 외부 음원 파일 수 — 이 생성기는 외부 음원을 읽는 경로가 없다. 조각 출처가 자체 합성 밖이면 '확인 필요'로 표시
  · 그림 인식 모델 — 쓴 모델 · 라이선스 (그림을 읽기만 하고 소리를 만들지 않는다)
  · 코드 지문 — 실행한 코드 파일의 SHA-256 (같은 코드 · 같은 입력 · 같은 시드 = 같은 소리 → 재현으로 검증 가능)
  · 입력 지문 — 스토리보드 · 배경 사진 · 오브제 그림의 SHA-256 (분석에만 쓰이고 소리에 복사되지 않는다)
  · 라이브러리 버전과 라이선스
  · 판정 — 상업 이용 조건
"""
import hashlib
import json
import os
import platform
import subprocess
import time

from . import paths

LIB_LICENSE = {   # 출력 오디오에 들어가는 것이 아니라 '연산 도구'다 — 도구의 라이선스는 결과물에 상속되지 않는다
    'numpy': 'BSD-3-Clause', 'scipy': 'BSD-3-Clause', 'PIL': 'MIT-CMU (HPND)',
    'imageio_ffmpeg': 'BSD-2-Clause (ffmpeg 실행 파일은 LGPL/GPL — 인코딩 도구로만 실행)',
    'torch': 'BSD-3-Clause', 'transformers': 'Apache-2.0',
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _versions(used_gpu):
    out = {'python': platform.python_version()}
    mods = ['numpy', 'scipy', 'PIL', 'imageio_ffmpeg'] + (['torch', 'transformers'] if used_gpu else [])
    for m in mods:
        try:
            mod = __import__(m)
            out[m] = {'version': getattr(mod, '__version__', '?'), 'license': LIB_LICENSE.get(m, '?')}
        except Exception:
            pass
    try:
        from .timing import ffmpeg
        exe = ffmpeg()
        if exe:
            out['ffmpeg'] = subprocess.run([exe, '-version'], capture_output=True, text=True).stdout.split('\n')[0]
    except Exception:
        pass
    return out


def build(run_dir, scenes, vision, notes):
    code = {}
    for root, _, files in os.walk(paths.SOUND_DIR):
        if os.sep + 'output' in root or os.sep + 'cache' in root or '__pycache__' in root:
            continue
        for f in sorted(files):
            if f.endswith('.py'):
                p = os.path.join(root, f)
                code[os.path.relpath(p, paths.SOUND_DIR).replace('\\', '/')] = sha256(p)
    inputs = {}
    for s in scenes:
        bg = (s.get('background') or {}).get('path')
        if bg:
            inputs[paths.rel(bg)] = sha256(bg)
        for o in s.get('objects', []):
            inputs[paths.rel(o['path'])] = sha256(o['path'])
    sb = [n for n in notes if n.startswith('스토리보드:')]
    mats = [{'scene': s['num'], 'file': m['file'], 'src': m['src'], 'how': m.get('how'), 'seed': m.get('seed'),
             'why': m.get('why')} for s in scenes for m in s.get('pieces', [])]
    unknown = [m for m in mats if m['src'] != 'procedural']
    if unknown:
        verdict, level = '확인 필요 — 출처가 기록되지 않은 조각이 있습니다: %d개' % len(unknown), 'check'
    else:
        verdict = ('자체 합성 — 외부 음원 0개 · 생성 모델 출력 0개. 출력 오디오의 모든 표본은 이 저장소의 코드가 '
                   '수식(numpy/scipy 연산)으로 계산했다. 제3자 저작물이 섞일 경로가 없으므로 상업적 이용에 제약이 없다.'
                   + (' 그림 인식 모델(%s)은 그림을 읽어 합성 값만 정했고 소리를 만들지 않았다 — 모두 상업 이용 가능 라이선스.'
                      % ', '.join('%s %s' % (m['id'].split('/')[-1], m['license'].split(' ')[0]) for m in vision['models'])
                      if vision else ''))
        level = 'own'
    prov = {
        'created': time.strftime('%Y-%m-%d %H:%M:%S'),
        'verdict': verdict, 'verdict_level': level,
        'pieces_by_source': {'procedural': len(mats) - len(unknown)}, 'external_audio_files': len(unknown),
        'vision': ({'note': '그림 인식 — 재질·장소·소리원·깊이를 읽어 합성 값만 정한다. 모델이 만든 오디오 없음', **vision}
                   if vision else '미사용'),
        'code_sha256': code, 'inputs_sha256': inputs, 'storyboard': sb[0] if sb else None,
        'libraries': _versions(bool(vision)), 'pieces': mats,
        'reproduce': '같은 코드 지문 · 같은 입력 지문 · 같은 --seed 로 다시 실행하면 같은 소리가 나온다 '
                     '(그림 인식 결과는 cache/vision/ 에 그림 지문별로 남는다)',
    }
    json.dump(prov, open(os.path.join(run_dir, 'provenance.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return prov
