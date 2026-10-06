# -*- coding: utf-8 -*-
"""
generate_dream_sound.py — 2팀 꿈 이야기(dream_scenes.json) → 5분짜리 꿈 사운드

[흐름]
  1) 사운드 설계  : Claude가 장면마다 이야기를 읽고 '소리 대본'(영어 프롬프트 + 배치 시점)을 작성
                   → sound/output/sound_design.json  (이미 있고 이야기가 같으면 재사용)
  2) 소리 생성    : Stable Audio 3 Small-SFX로 배경음·감정 질감·효과음을 생성
                   → sound/output/stems/*.wav       (같은 프롬프트+시드는 캐시 재사용)
  3) 믹싱         : 장면마다 배경음 + 질감 + 효과음(시점 배치, 꿈 효과) → 장면 사이 크로스페이드
                   → sound/output/scene1~4.wav, dream_soundtrack.wav (기본 5분)

[장면 하나의 구조 (기본 75초 + 크로스페이드 여유)]
  배경음(ambience) : 장면 전체에 깔리는 환경음 1개
  질감(texture)    : main_emotion에 맞춘 낮은 드론/질감 1개
  효과음(events)   : 이야기 흐름을 따라 4~7개, 시점·길이·꿈 효과(reverse/echo/slow/fast)

[실행 환경]  conda 'sound' 환경 (torch + stable-audio-3 + anthropic + python-dotenv)
  python sound/generate_dream_sound.py
  python sound/generate_dream_sound.py --redesign        # 설계를 Claude로 새로 작성
  python sound/generate_dream_sound.py --design-only     # 설계만 (GPU 없이)
  python sound/generate_dream_sound.py --dry-run         # 모델 없이 가짜 소리로 믹싱 흐름만 확인
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]          # Capstone2
DEFAULT_SCENES = ROOT / "team2" / "output" / "dream_scenes.json"
DEFAULT_OUT = ROOT / "sound" / "output"

SR = 44100
SCENE_NOMINAL = 75.0          # 설계상 장면 길이(초). 효과음 시점은 이 기준
MODEL_NAME = "small-sfx"
DESIGN_MODEL = "claude-sonnet-5"   # 2팀 step2와 같은 모델
ALLOWED_FX = {"none", "reverse", "echo", "slow", "fast"}

# 믹싱 기준 (dBFS)
AMBIENCE_RMS_DB = -26.0
TEXTURE_RMS_DB = -31.0
EVENT_PEAK_DB = -6.0
MASTER_PEAK_DB = -1.0


# ══════════════════════════════════════════════════════════
# 공통 유틸
# ══════════════════════════════════════════════════════════
def db2lin(db):
    return 10 ** (db / 20.0)


def stories_hash(scenes):
    text = "\n".join(s.get("story", "") for s in scenes)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def load_scenes(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    scenes = data["scenes"] if isinstance(data, dict) else data
    if not scenes:
        sys.exit(f"[중단] 장면이 없습니다: {path}")
    return scenes


def load_env_key():
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    try:
        from dotenv import load_dotenv
    except ImportError:
        return False
    for p in (ROOT / ".env", ROOT / "team2" / ".env"):
        if p.exists():
            load_dotenv(p)
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


# ══════════════════════════════════════════════════════════
# 1) 사운드 설계 (Claude)
# ══════════════════════════════════════════════════════════
DESIGN_PROMPT = """너는 꿈 장면을 위한 사운드 디자이너다. 아래 꿈 장면 하나를 읽고, 텍스트→오디오 모델
(Stable Audio 3 Small-SFX, 효과음·환경음 전용, 음악/목소리 불가)에 넣을 '소리 대본'을 작성하라.

[장면 {scene_no} / 길이 {length:.0f}초]
- 이야기:
{story}
- 배경: {backgrounds}
- 오브제: {objects}
- 감정: {emotions}
- 대표 감정: {main_label} (강도 {main_intensity})
- 꿈의 물리법칙(현실과 어긋난 점): {physics}

[작성 규칙]
1. 모든 프롬프트는 영어로, 'TrackType: SFX, '로 시작한다.
2. 프롬프트는 소리의 원천(무엇이) + 동작(어떻게, 얼마나) + 녹음 특성(공간감, 마이크 거리, 잔향)을 구체적으로 쓴다.
   음악, 멜로디, 리듬, 노래, 말소리, 목소리는 넣지 않는다.
3. ambience: 장면 전체({length:.0f}초)에 깔리는 환경음 1개. "field recording" 성격, 끊기지 않고 이어지는 소리.
4. texture: 대표 감정을 받쳐주는 낮은 드론/질감 1개 (예: 놀람→불안정하게 흔들리는 유리질 고음,
   공포→압박감이 커지는 저음 럼블, 슬픔→느리고 공허한 바람결). 멜로디 없이 지속되는 소리.
5. events: 이야기의 문단 순서를 따라 핵심 소리 순간 4~7개. 각 항목:
   - t: 시작 시점(초, 2 이상 {last_t} 이하, 이야기 순서대로 오름차순, 서로 5초 이상 간격)
   - dur: 길이(초, 2~8)
   - prompt: 영어 프롬프트
   - gain_db: 상대 음량(-12 ~ 0, 핵심 사건일수록 0에 가깝게)
   - fx: 꿈의 물리법칙을 소리로 표현할 때만 사용. none | reverse(떨어지는 소리를 거꾸로 → 떠오름) |
         echo(소리가 늦게 도착/울림) | slow(느려지고 낮아짐, 무거움) | fast(빨라지고 높아짐)
   - source: 이 소리의 근거가 된 이야기 속 장면(한국어, 짧게)
6. envelopes(선택): 이야기에서 소리가 '뚝 끊기거나' 점점 커지는 순간이 있으면, ambience/texture 음량 곡선을
   [[시점초, dB], ...] 형식으로 지정한다. 예: 귀뚜라미가 뚝 끊김 → "ambience": [[0,0],[40,0],[40.5,-30],[{length:.0f},-30]].
   필요 없으면 빈 객체.

[출력 — JSON만, 설명이나 코드블록 없이]
{{
  "ambience": {{"prompt": "..."}},
  "texture": {{"prompt": "..."}},
  "events": [{{"t": 3, "dur": 4, "prompt": "...", "gain_db": -3, "fx": "none", "source": "..."}}],
  "envelopes": {{}}
}}"""


def design_scene_with_claude(client, scene, length):
    me = scene.get("main_emotion") or {}
    prompt = DESIGN_PROMPT.format(
        scene_no=scene.get("scene", "?"),
        length=length,
        story=scene.get("story", ""),
        backgrounds=", ".join(scene.get("backgrounds", [])),
        objects=", ".join(scene.get("objects", [])),
        emotions=", ".join(scene.get("emotions", [])),
        main_label=me.get("label", "중립"),
        main_intensity=me.get("intensity", 0.5),
        physics="; ".join(scene.get("physics_laws", [])) or "없음",
        last_t=int(length - 6),
    )
    last_err = None
    for attempt in range(1, 4):
        msg = client.messages.create(
            model=DESIGN_MODEL, max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = next((b.text for b in msg.content if hasattr(b, "text")), "")
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        try:
            return validate_scene_design(json.loads(m.group()), length)
        except Exception as e:                       # noqa: BLE001
            last_err = e
            print(f"  [설계 재시도 {attempt}/3] {e}")
    raise RuntimeError(f"장면 {scene.get('scene')} 설계 실패: {last_err}")


def _fix_prompt(p):
    p = str(p).strip()
    return p if p.lower().startswith("tracktype") else f"TrackType: SFX, {p}"


def validate_scene_design(d, length):
    """Claude 출력(또는 수기 설계)을 안전한 범위로 정리"""
    out = {
        "ambience": {"prompt": _fix_prompt(d["ambience"]["prompt"])},
        "texture": {"prompt": _fix_prompt(d["texture"]["prompt"])},
        "events": [],
        "envelopes": {},
    }
    for ev in sorted(d.get("events", []), key=lambda e: float(e["t"])):
        t = float(np.clip(float(ev["t"]), 0.5, length - 2))
        dur = float(np.clip(float(ev.get("dur", 4)), 1.0, 10.0))
        fx = str(ev.get("fx", "none")).lower()
        out["events"].append({
            "t": round(t, 2), "dur": round(dur, 2),
            "prompt": _fix_prompt(ev["prompt"]),
            "gain_db": float(np.clip(float(ev.get("gain_db", -4)), -18, 0)),
            "fx": fx if fx in ALLOWED_FX else "none",
            "source": ev.get("source", ""),
        })
    if not out["events"]:
        raise ValueError("events가 비어 있음")
    for layer in ("ambience", "texture"):
        pts = (d.get("envelopes") or {}).get(layer)
        if pts:
            out["envelopes"][layer] = [[float(a), float(b)] for a, b in pts]
    return out


def build_design(scenes, design_path, redesign, explicit=False):
    h = stories_hash(scenes)
    if explicit and design_path.exists() and not redesign:
        design = json.loads(design_path.read_text(encoding="utf-8"))
        if len(design.get("scenes", [])) != len(scenes):
            sys.exit(f"[중단] 설계 장면 수({len(design.get('scenes', []))})와 이야기 장면 수({len(scenes)})가 다릅니다.")
        print(f"[설계] 지정한 설계 파일 사용: {design_path}")
        return design
    if design_path.exists() and not redesign:
        design = json.loads(design_path.read_text(encoding="utf-8"))
        if design.get("stories_sha1") == h:
            print(f"[설계] 기존 설계 재사용: {design_path}")
            return design
        print("[설계] dream_scenes.json 내용이 바뀌어 설계를 새로 만듭니다.")

    if not load_env_key():
        sys.exit("[중단] 설계를 새로 만들려면 ANTHROPIC_API_KEY가 필요합니다 (Capstone2/.env).")
    try:
        import anthropic
    except ImportError:
        sys.exit("[중단] anthropic 패키지가 없습니다: pip install anthropic python-dotenv")
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    design = {"stories_sha1": h, "scene_nominal_sec": SCENE_NOMINAL,
              "model": MODEL_NAME, "scenes": []}
    for sc in scenes:
        print(f"[설계] 장면 {sc.get('scene')} 소리 대본 작성 중...")
        d = design_scene_with_claude(client, sc, SCENE_NOMINAL)
        d["scene"] = sc.get("scene")
        d["main_emotion"] = sc.get("main_emotion")
        design["scenes"].append(d)
    design_path.parent.mkdir(parents=True, exist_ok=True)
    design_path.write_text(json.dumps(design, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[설계] 저장 → {design_path}")
    return design


# ══════════════════════════════════════════════════════════
# 2) 소리 생성 (Stable Audio 3)
# ══════════════════════════════════════════════════════════
class Generator:
    def __init__(self, stems_dir, steps, dry_run=False):
        self.stems_dir = Path(stems_dir)
        self.stems_dir.mkdir(parents=True, exist_ok=True)
        self.steps = steps
        self.dry_run = dry_run
        self.model = None
        self.n_generated = 0
        self.n_cached = 0

    def _load(self):
        if self.model is not None or self.dry_run:
            return
        from stable_audio_3 import StableAudioModel
        print(f"[생성] 모델 불러오는 중: {MODEL_NAME}")
        self.model = StableAudioModel.from_pretrained(MODEL_NAME)
        global SR
        SR = int(self.model.model.sample_rate)

    def get(self, name, prompt, duration, seed):
        """(2, N) float32 반환. 같은 이름·프롬프트·길이·시드면 캐시 파일 재사용"""
        import soundfile as sf
        key = hashlib.sha1(f"{prompt}|{duration:.2f}|{seed}|{self.steps}|{self.dry_run}".encode()).hexdigest()[:8]
        path = self.stems_dir / f"{name}_{key}.wav"
        if path.exists():
            data, _ = sf.read(path, dtype="float32", always_2d=True)
            self.n_cached += 1
            return data.T
        if self.dry_run:
            audio = fake_audio(prompt, duration, seed)
        else:
            self._load()
            out = self.model.generate(
                prompt=prompt, duration=float(duration), seed=int(seed),
                steps=self.steps, sample_size=self.model.model_config["sample_size"],
            )
            audio = out[0].detach().cpu().float().numpy()
        if audio.shape[0] == 1:
            audio = np.repeat(audio, 2, axis=0)
        sf.write(path, audio.T, SR, subtype="FLOAT")
        self.n_generated += 1
        print(f"  [생성] {name} ({duration:.1f}s) {prompt[:70]}...")
        return audio


def fake_audio(prompt, duration, seed):
    """--dry-run용: 프롬프트마다 다른 톤+잡음 (모델 없이 믹싱 흐름 확인)"""
    rng = np.random.default_rng(seed)
    n = int(duration * SR)
    t = np.arange(n) / SR
    f = 110 + (int(hashlib.md5(prompt.encode()).hexdigest(), 16) % 600)
    tone = 0.3 * np.sin(2 * np.pi * f * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 0.2 * t))
    noise = 0.1 * rng.standard_normal(n)
    mono = (tone + noise).astype(np.float32)
    return np.stack([mono, mono * 0.9])


# ══════════════════════════════════════════════════════════
# 3) 믹싱
# ══════════════════════════════════════════════════════════
def rms_normalize(x, target_db):
    rms = np.sqrt(np.mean(x ** 2)) + 1e-9
    return x * (db2lin(target_db) / rms)


def peak_normalize(x, target_db):
    peak = np.max(np.abs(x)) + 1e-9
    return x * (db2lin(target_db) / peak)


def fade(x, fade_in, fade_out):
    n = x.shape[1]
    fi, fo = min(int(fade_in * SR), n // 2), min(int(fade_out * SR), n // 2)
    env = np.ones(n, dtype=np.float32)
    if fi > 0:
        env[:fi] = np.linspace(0, 1, fi)
    if fo > 0:
        env[-fo:] = np.linspace(1, 0, fo)
    return x * env


def fit_length(x, n):
    if x.shape[1] >= n:
        return x[:, :n]
    return np.pad(x, ((0, 0), (0, n - x.shape[1])))


def apply_envelope(x, points):
    """points: [[초, dB], ...] 선형 보간 음량 곡선"""
    if not points:
        return x
    pts = sorted(points)
    times = np.array([p[0] for p in pts]) * SR
    gains = db2lin(np.array([p[1] for p in pts]))
    env = np.interp(np.arange(x.shape[1]), times, gains).astype(np.float32)
    return x * env


def change_speed(x, factor):
    """factor < 1: 느리고 낮게, > 1: 빠르고 높게 (리샘플링)"""
    n_out = int(x.shape[1] / factor)
    src = np.linspace(0, x.shape[1] - 1, n_out)
    return np.stack([np.interp(src, np.arange(x.shape[1]), ch) for ch in x]).astype(np.float32)


def apply_fx(x, fx):
    if fx == "reverse":
        return x[:, ::-1].copy()
    if fx == "echo":
        taps = [(0.0, 1.0), (0.35, 0.5), (0.7, 0.28), (1.05, 0.14), (1.4, 0.07)]
        n = x.shape[1] + int(taps[-1][0] * SR)
        y = np.zeros((x.shape[0], n), dtype=np.float32)
        for delay, g in taps:
            d = int(delay * SR)
            y[:, d:d + x.shape[1]] += g * x
        return y
    if fx == "slow":
        return change_speed(x, 0.75)
    if fx == "fast":
        return change_speed(x, 1.33)
    return x


def render_scene(gen, sd, scene_idx, scene_len, seed_base, log):
    n = int(scene_len * SR)
    s = seed_base + scene_idx * 100

    amb = gen.get(f"s{scene_idx+1}_ambience", sd["ambience"]["prompt"], scene_len, s)
    amb = fade(rms_normalize(fit_length(amb, n), AMBIENCE_RMS_DB), 2.0, 2.0)
    amb = apply_envelope(amb, sd.get("envelopes", {}).get("ambience"))

    tex = gen.get(f"s{scene_idx+1}_texture", sd["texture"]["prompt"], scene_len, s + 1)
    tex = fade(rms_normalize(fit_length(tex, n), TEXTURE_RMS_DB), 3.0, 3.0)
    tex = apply_envelope(tex, sd.get("envelopes", {}).get("texture"))

    mix = amb + tex
    scale = scene_len / SCENE_NOMINAL if scene_len < SCENE_NOMINAL else 1.0
    for j, ev in enumerate(sd["events"]):
        x = gen.get(f"s{scene_idx+1}_ev{j+1}", ev["prompt"], ev["dur"], s + 10 + j)
        x = apply_fx(x, ev.get("fx", "none"))
        x = fade(peak_normalize(x, EVENT_PEAK_DB + ev.get("gain_db", 0)), 0.005, min(0.5, x.shape[1] / SR * 0.15))
        start = int(ev["t"] * scale * SR)
        end = min(n, start + x.shape[1])
        if start < n:
            mix[:, start:end] += x[:, :end - start]
        log.append({"scene": scene_idx + 1, "event": j + 1, "t": ev["t"], "fx": ev.get("fx"),
                    "source": ev.get("source", ""), "prompt": ev["prompt"]})

    peak = np.max(np.abs(mix))
    if peak > db2lin(-3):                      # 장면 단위로 과도한 피크만 눌러줌
        mix *= db2lin(-3) / peak
    return mix.astype(np.float32)


def crossfade_concat(clips, xfade_sec):
    xf = int(xfade_sec * SR)
    out = clips[0]
    for c in clips[1:]:
        k = min(xf, out.shape[1], c.shape[1])
        t = np.linspace(0, np.pi / 2, k, dtype=np.float32)
        tail = out[:, -k:] * np.cos(t) + c[:, :k] * np.sin(t)       # 등전력 크로스페이드
        out = np.concatenate([out[:, :-k], tail, c[:, k:]], axis=1)
    return out


# ══════════════════════════════════════════════════════════
# 메인
# ══════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser(description="꿈 이야기 → 5분 꿈 사운드")
    ap.add_argument("--scenes", default=str(DEFAULT_SCENES), help="2팀 dream_scenes.json 경로")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--design", default=None, help="사운드 설계 파일 (기본: <out>/sound_design.json)")
    ap.add_argument("--redesign", action="store_true", help="설계를 Claude로 새로 작성")
    ap.add_argument("--design-only", action="store_true", help="설계만 하고 끝냄")
    ap.add_argument("--total", type=float, default=300.0, help="전체 길이(초), 기본 300 = 5분")
    ap.add_argument("--crossfade", type=float, default=4.0, help="장면 사이 크로스페이드(초)")
    ap.add_argument("--steps", type=int, default=8, help="확산 단계 (Small-SFX 기본 8)")
    ap.add_argument("--seed", type=int, default=1234, help="기본 시드 (바꾸면 다른 소리)")
    ap.add_argument("--dry-run", action="store_true", help="모델 없이 가짜 소리로 흐름만 확인")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    scenes = load_scenes(args.scenes)
    design_path = Path(args.design) if args.design else out / "sound_design.json"
    design = build_design(scenes, design_path, args.redesign, explicit=bool(args.design))
    if args.design_only:
        return

    n = len(design["scenes"])
    scene_len = (args.total + (n - 1) * args.crossfade) / n
    print(f"\n[믹싱] 장면 {n}개 × {scene_len:.1f}초, 크로스페이드 {args.crossfade:g}초 → 전체 {args.total:g}초")

    t0 = time.time()
    gen = Generator(out / "stems", args.steps, dry_run=args.dry_run)
    import soundfile as sf
    clips, log = [], []
    for i, sd in enumerate(design["scenes"]):
        print(f"\n[장면 {i+1}] 대표 감정: {(sd.get('main_emotion') or {}).get('label', '-')}")
        clip = render_scene(gen, sd, i, scene_len, args.seed, log)
        sf.write(out / f"scene{i+1}.wav", clip.T, SR, subtype="PCM_16")
        clips.append(clip)

    master = crossfade_concat(clips, args.crossfade)
    master = peak_normalize(master, MASTER_PEAK_DB)
    master_path = out / "dream_soundtrack.wav"
    sf.write(master_path, master.T, SR, subtype="PCM_16")

    (out / "sound_log.json").write_text(json.dumps({
        "scenes_file": str(Path(args.scenes).resolve()), "total_sec": master.shape[1] / SR,
        "scene_len": scene_len, "crossfade": args.crossfade, "seed": args.seed,
        "steps": args.steps, "dry_run": args.dry_run, "events": log,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n완료 ({time.time() - t0:.1f}초) — 새로 생성 {gen.n_generated}개, 캐시 재사용 {gen.n_cached}개")
    print(f"  전체 사운드 : {master_path}  ({master.shape[1] / SR:.1f}초)")
    print(f"  장면별      : {out / 'scene1.wav'} ~ scene{n}.wav")
    print(f"  설계/기록   : {design_path.name}, sound_log.json")


if __name__ == "__main__":
    main()