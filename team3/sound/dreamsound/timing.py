"""4단계 · 길이 — 장면 소리를 이어 붙이고 WAV(·mp3)로 낸다. 영상에 붙이는 일(mux)도 여기.

장면 길이는 고정 75초 (10-07 결정 — 영상을 기다리지 않고 사운드를 먼저 끝낸다. 4장면 = 5분 = 10/15 미션 길이 =
배경 엔진 SCENE_SEC 기본값). 이어 붙이기는 경계를 가운데 두고 겹쳐 섞는다(등전력 크로스페이드) —
전체 길이가 장면 길이 합과 샘플 단위로 같다.

출력 형식: WAV 48kHz 16비트 PCM (영상 표준 표본율 · 무손실). 영상에 붙일 때 AAC 로 한 번만 압축된다.
mp3 로 먼저 만든 뒤 영상에 넣으면 손실 압축이 두 번 겹친다 — mp3 는 미리듣기용(--mp3)으로만.
"""
import json
import math
import os
import re
import shutil
import subprocess

import numpy as np
from scipy.io import wavfile

DEFAULT_SEC = 75.0
XFADE = 2.8          # 배경 엔진의 장면 간 모핑 시간과 같다 (Z-order 파편 이동 약 2.8초)


def ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        exe = shutil.which('ffmpeg')
        if exe:
            return exe
    return None


def media_duration(path):
    """영상·음원 길이(초) — ffprobe 없이 ffmpeg 출력의 Duration 을 읽는다."""
    exe = ffmpeg()
    if not exe:
        raise SystemExit('ffmpeg 이 없습니다 — pip install imageio-ffmpeg')
    r = subprocess.run([exe, '-hide_banner', '-i', path], capture_output=True, text=True, errors='replace')
    m = re.search(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)', r.stderr)
    if not m:
        raise SystemExit('길이를 읽지 못했습니다: %s' % path)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def plan(durs, xfade=XFADE):
    """장면별 렌더 구간 — 경계마다 앞뒤로 xfade/2 씩 더 만든다. → [(시작초, 렌더 길이, 앞겹침, 뒤겹침)]."""
    n = len(durs)
    half = [min(xfade / 2, durs[i] / 3, durs[i + 1] / 3) for i in range(n - 1)]   # 경계마다 같은 폭으로
    out, t = [], 0.0
    for i, D in enumerate(durs):
        pre = half[i - 1] if i > 0 else 0.0
        post = half[i] if i < n - 1 else 0.0
        out.append((t - pre, D + pre + post, pre, post))
        t += D
    return out


def match_levels(parts, durs, sr):
    """경계 음량 맞추기 — 장면마다 따로 만든 기승전결 곡선이 경계에서 튀지 않게(예: 전의 끝 −38dB → 결의 시작 −18dB).
    경계 양쪽 3초의 음량을 재 그 기하평균으로 모으되, 장면 길이의 20% 에 걸쳐 천천히 기울인다 — 곡선의 모양은 남는다."""
    pl = plan(durs)
    parts = [p.copy() for p in parts]
    for i in range(len(parts) - 1):
        (_, La, preA, postA), (_, Lb, preB, postB) = pl[i], pl[i + 1]
        W = int(min(3.0, durs[i] / 4, durs[i + 1] / 4) * sr)
        a_end = int(round((preA + durs[i]) * sr))
        b_beg = int(round(preB * sr))
        ra = np.sqrt(np.mean(parts[i][max(0, a_end - W):a_end] ** 2)) + 1e-9
        rb = np.sqrt(np.mean(parts[i + 1][b_beg:b_beg + W] ** 2)) + 1e-9
        tgt = math.sqrt(ra * rb)
        ga, gb = float(np.clip(tgt / ra, 0.35, 2.8)), float(np.clip(tgt / rb, 0.35, 2.8))
        ra_len = int(0.2 * durs[i] * sr)
        rb_len = int(0.2 * durs[i + 1] * sr)
        ya, yb = parts[i], parts[i + 1]
        s = max(0, a_end - ra_len)
        ramp = np.ones(len(ya))
        ramp[s:a_end] = np.exp(np.linspace(0, math.log(ga), a_end - s))
        ramp[a_end:] = ga
        ya *= ramp[:, None]
        e = min(len(yb), b_beg + rb_len)
        ramp = np.ones(len(yb))
        ramp[:b_beg] = gb
        ramp[b_beg:e] = np.exp(np.linspace(math.log(gb), 0, e - b_beg))
        yb *= ramp[:, None]
    return parts


def assemble(parts, durs, sr):
    """겹쳐 섞기 — 렌더한 장면들(parts, 각자 앞뒤 겹침 포함)을 한 줄로. 길이 = sum(durs)*sr 정확히."""
    total = int(round(sum(durs) * sr))
    out = np.zeros((total, 2), dtype=np.float32)
    parts = match_levels(parts, durs, sr)
    for (start, L, pre, post), y in zip(plan(durs), parts):
        y = y.copy()
        a, b = int(round(pre * 2 * sr)), int(round(post * 2 * sr))
        if a:
            y[:a] *= np.sin(np.linspace(0, np.pi / 2, a))[:, None]     # 등전력 페이드
        if b:
            y[-b:] *= np.cos(np.linspace(0, np.pi / 2, b))[:, None]
        s = int(round(start * sr))
        s0, s1 = max(0, s), min(total, s + len(y))
        out[s0:s1] += y[s0 - s:s1 - s]
    out = np.tanh(out / 0.95) * 0.95                               # 경계 맞추기로 커진 꼭대기를 부드럽게
    # 처음·끝 20ms 만 살짝 — 클릭 방지
    f = int(0.02 * sr)
    out[:f] *= np.linspace(0, 1, f)[:, None]
    out[-f:] *= np.linspace(1, 0, f)[:, None]
    return out


def write_wav(path, y, sr):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    wavfile.write(path, sr, (np.clip(y, -1, 1) * 32767).astype(np.int16))


def to_mp3(wav, mp3, kbps=192):
    exe = ffmpeg()
    if not exe:
        return False
    r = subprocess.run([exe, '-y', '-hide_banner', '-loglevel', 'error', '-i', wav, '-c:a', 'libmp3lame',
                        '-b:a', '%dk' % kbps, mp3], capture_output=True, text=True)
    return r.returncode == 0


def mux(video, wav, out):
    """영상 + 사운드 → mp4. 영상은 다시 인코딩하지 않는다(-c:v copy)."""
    exe = ffmpeg()
    if not exe:
        raise SystemExit('ffmpeg 이 없습니다 — pip install imageio-ffmpeg')
    r = subprocess.run([exe, '-y', '-hide_banner', '-loglevel', 'error', '-i', video, '-i', wav,
                        '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
                        '-movflags', '+faststart', out], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit('mp4 합치기 실패: %s' % r.stderr[-400:])
    return out
