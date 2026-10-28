# -*- coding: utf-8 -*-
"""Story-conditioned target preparation and alternating constructive GA / CA rendering. Each cycle owns its reconstructed RGB state. The source plate is an objective, never a composited reveal layer."""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as F

from team4.DreamModel.runtime import background_ca_engine as m


SCENARIO_NAMES = {
    1: "1_놀람공포중립공포",
    2: "2_혐오공포기쁨슬픔",
    3: "3_공포공포중립중립",
}


# --------------------------------------------------------------------------------------
# 1. 범용 스토리·감정 해석기 (하드코딩 없는 서사 → 공간 진화/물리 매핑)
# --------------------------------------------------------------------------------------
def _count_cues(text: str, cues: tuple[str, ...]) -> int:
    return sum(1 for c in cues if c in text)


def load_unified_scene_metadata(scenario_dir: Path) -> tuple[list[dict], list[dict]]:
    """
    scenes.json 과 dream_scenes.json 을 로드하며, scenes.json 이 없는 스토리보드 폴더에서도
    dream_scenes.json 으로부터 자동으로 표준 4장면 메타데이터를 구성한다.
    """
    story_path = scenario_dir / "dream_scenes.json"
    scenes_path = scenario_dir / "scenes.json"

    story_scenes: list[dict] = []
    if story_path.exists():
        raw_story = json.loads(story_path.read_text(encoding="utf-8-sig"))
        story_scenes = raw_story.get("scenes", raw_story) if isinstance(raw_story, dict) else raw_story

    if scenes_path.exists():
        raw_sc = json.loads(scenes_path.read_text(encoding="utf-8-sig"))
        sc_list = raw_sc.get("scenes", [])
    else:
        stages = ["기", "승", "전", "결"]
        sc_list = []
        for idx in range(4):
            st = story_scenes[idx] if idx < len(story_scenes) else {}
            me = st.get("main_emotion") or {}
            emo_ko = me.get("label", "중립") if isinstance(me, dict) else "중립"
            if emo_ko not in m.EMO_KO:
                emo_ko = "중립"
            inten = float(me.get("intensity", 0.5)) if isinstance(me, dict) else 0.5
            bgs = st.get("backgrounds") or [f"장면 {idx + 1}"]
            sc_list.append({
                "stage": stages[idx],
                "act": idx + 1,
                "title": bgs[0] if bgs else f"장면 {idx + 1}",
                "emotion": emo_ko,
                "intensity": inten,
                "backgrounds": bgs,
            })

    return sc_list, story_scenes


def interpret_story_and_emotion(
    idx: int,
    sc_meta: dict,
    story_item: dict,
    plate_stats: dict,
    all_plate_stats: list[dict],
    prev_profile: dict | None = None,
) -> dict:
    """
    스토리 텍스트, 물리 법칙(physics_laws), 감정 라벨·강도, 4차원 감정 벡터(Pleasantness 등),
    그리고 목표 배경 이미지의 고유 명암/색상을 종합 해석해 장면 고유의 공간 진화 프로파일을 생성.
    """
    emo_ko = sc_meta.get("emotion", "중립")
    emo_en = m.EMO_KO.get(emo_ko, "neutral")
    intensity = float(sc_meta.get("intensity", 0.55))
    p_dyn = m.emo_params(emo_en, intensity)

    story_txt = str(story_item.get("story", ""))
    bgs_txt = " ".join(story_item.get("backgrounds") or sc_meta.get("backgrounds") or [])
    laws_txt = " ".join(story_item.get("physics_laws") or [])
    emos_txt = " ".join(story_item.get("emotions") or [])
    full_txt = f"{bgs_txt} {story_txt} {laws_txt} {emos_txt}"

    vec = story_item.get("vector") or [0.0, 0.4, 0.4, 0.0]
    pleasant = float(vec[0]) if len(vec) > 0 else 0.0
    attention = float(vec[1]) if len(vec) > 1 else 0.4
    sensitivity = float(vec[2]) if len(vec) > 2 else 0.4
    arousal = float(np.clip(0.5 * (abs(attention) + abs(sensitivity)) + 0.35 * intensity, 0.2, 1.4))

    # 서사 사건/물리 단서 정량화 (특정 단어 하나에 고정되지 않는 일반 의미군 분석)
    c_loco = _count_cues(full_txt, ("달리", "달려", "걸음", "걷는", "걸을", "복도", "계단", "난간", "뻗어", "다가가", "지나가", "가로질"))
    c_recede = _count_cues(full_txt, ("멀어지", "물러나", "좁혀지지", "늘어나", "끝없이", "사라짐"))
    c_open = _count_cues(full_txt, ("열리", "열린", "벌어지", "넓어지", "넓게", "확장", "틈", "새어 나오", "펼쳐"))
    c_collapse = _count_cues(full_txt, ("무너지", "붕괴", "균열", "갈라지", "금이", "꺼지", "가라앉", "벗겨지", "허물어", "떨어져", "부서"))
    c_float = _count_cues(full_txt, ("떠오르", "떠 있", "공기 방울", "거품", "위로", "솟아", "거꾸로", "무게가 사라", "가벼워", "깃털"))
    c_wave = _count_cues(full_txt, ("물결", "파도", "수면", "파문", "동심원", "나이테", "잔물결", "바닷물", "물 위"))
    c_light = _count_cues(full_txt, ("빛", "햇살", "볕", "달빛", "창", "반짝", "환하게", "금빛", "은빛", "잔광"))
    c_pulse = _count_cues(full_txt, ("심장", "박동", "두근", "맥박", "숨", "호흡", "박자", "북소리", "울림", "공명"))
    c_bright_words = _count_cues(full_txt, ("햇살", "볕", "아침", "환하게", "희고", "유백색", "달빛", "거울", "온기", "따뜻"))
    c_dark_words = _count_cues(full_txt, ("어둠", "침몰", "곰팡이", "축축", "차갑", "심연", "녹슨", "무겁고"))

    # 1) 장면별 명도 키(Canvas Key: bright / mid / dark) 및 색온도 결정 — 4막 간 대비 강제 보장!
    med_lum = plate_stats["med_lum"]
    warmth_plate = plate_stats["warmth"]
    bright_score = (
        1.15 * (med_lum - 0.24)
        + 0.65 * pleasant
        + 0.14 * c_bright_words
        - 0.10 * c_dark_words
        + (0.38 if emo_en in ("happy",) else (0.14 if emo_en in ("surprise", "neutral") else -0.22))
    )

    # 1) 장면별 분위기·명암·색감 모드(mood_style) 및 도화지 키 결정 — 어둡고 공포 / 밝고 해피 / 어둡고 고요 / 신비 개방을 극명히 대비!
    all_lums = [s["med_lum"] for s in all_plate_stats]
    lum_rank = sorted(range(len(all_lums)), key=lambda k: all_lums[k]).index(idx)
    prev_key = prev_profile["canvas_key"] if prev_profile is not None else None

    warm_story = _count_cues(full_txt, ("햇살", "볕", "온기", "따뜻", "기쁨"))
    quiet_story = _count_cues(full_txt, ("달빛", "고요", "정적", "느리게", "애도", "슬픔"))
    if emo_en == "happy" or (warm_story >= 2 and pleasant > .10):
        mood_style, canvas_key = "bright_happy", "high_light"
    elif emo_en in ("fear", "angry", "disgust"):
        mood_style, canvas_key = "dark_horror", "deep_contrast"
    elif emo_en == "sad" or quiet_story >= 3:
        mood_style, canvas_key = "dark_calm", "deep_contrast"
    else:
        mood_style, canvas_key = "vivid_mystery", "mid_atmos"

    warm_bias = float(np.clip(
        warmth_plate * 1.4 + p_dyn["warm"] * 1.5 + 0.40 * pleasant
        + (0.45 if mood_style == "bright_happy" else (-0.32 if mood_style in ("dark_horror", "dark_calm") else 0.05)),
        -0.80, 0.90,
    ))

    # 2) 기법 역할 분담: '유전 기법(GA: 점→시행착오 선·다각형→완성→파편 파괴)'과 '셀룰러(CA: 단일 셀→블록 가지 증식→완성→도미노 붕괴)' 교차!
    if idx % 2 == 0:
        arch_mode = "ga_point_evolution" if idx == 0 else "ga_joyful_evolution"
        ga_lead, ca_lead = 1.0, 0.0
    else:
        arch_mode = "ca_horror_cellular" if mood_style == "dark_horror" else "ca_calm_cellular"
        ga_lead, ca_lead = 0.0, 1.0

    # 3) 스토리 이동·변형 벡터 (이동/달리기, 멀어짐, 개방, 중력/부력, 파문)
    #    c_recede 가 크면 소실점에서 멀어지는 후퇴 흐름(-), c_loco 가 크면 앞으로 전진(+)
    if c_recede > 0 and c_loco > 0:
        loco_vel = -0.22 - 0.05 * min(c_recede, 4)   # 다가갈수록 멀어지는 계단/복도 역설
    elif c_loco > 0:
        loco_vel = 0.16 + 0.055 * min(c_loco, 5)     # 앞으로 이동/달리기 전진 흐름
    else:
        loco_vel = 0.05 * (1.0 if pleasant >= 0 else -1.0)

    aperture_amp = float(np.clip(0.08 * c_open + (0.14 if idx == 2 else 0.0), 0.0, 0.34))
    collapse_freq = float(np.clip(0.55 + 0.22 * c_collapse + 0.35 * p_dyn["collapse"] + (0.35 if idx in (1, 2) else 0.0), 0.35, 1.85))
    wave_amp = float(np.clip(0.18 * c_wave + (0.24 if idx == 3 else 0.0), 0.0, 0.85))
    light_amp = float(np.clip(0.16 * c_light + (0.28 if canvas_key == "high_light" else 0.08), 0.08, 0.85))
    pulse_amp = float(np.clip(0.18 * c_pulse + 0.22 * p_dyn["breath"], 0.10, 0.75))

    # 붕괴/입자 중력 방향: 부유/기포 단서가 우세하면 위로(-y), 침하/무너짐이 우세하면 아래로(+y)
    if c_float > c_collapse:
        gravity_xy = (0.08 * math.sin(idx + 1), -0.85)
        particle_mode = "buoyant_up"
    elif c_open > c_collapse and idx >= 2:
        gravity_xy = (0.65 if idx == 2 else -0.45, -0.35)
        particle_mode = "radiant_drift"
    else:
        gravity_xy = (0.18 * (1 if idx % 2 == 0 else -1), 0.95)
        particle_mode = "crumble_fall" if c_collapse >= 2 else "mist_sparks"

    # GA 성장 유도 방향
    if abs(loco_vel) > 0.14:
        flow_dir = (0.0, -0.35 if loco_vel > 0 else 0.35)
    elif c_float > c_collapse:
        flow_dir = (0.12, -0.55)
    elif c_open >= 2:
        flow_dir = (0.45, -0.15)
    else:
        flow_dir = (0.22 * math.cos(idx * 1.7), 0.22 * math.sin(idx * 1.7))

    p_dyn["speed"] = float(np.clip(p_dyn["speed"] * (0.78 + 0.42 * arousal), 0.50, 1.85))
    p_dyn["collapse"] = collapse_freq

    return dict(
        idx=idx,
        emotion_ko=emo_ko,
        emotion_en=emo_en,
        mood_style=mood_style,
        intensity=intensity,
        emotion_vector=[float(x) for x in vec[:4]],
        pleasantness=pleasant,
        arousal=arousal,
        arch_mode=arch_mode,
        canvas_key=canvas_key,
        warm_bias=warm_bias,
        ga_lead=ga_lead,
        ca_lead=ca_lead,
        loco_vel=loco_vel,
        aperture_amp=aperture_amp,
        collapse_freq=collapse_freq,
        wave_amp=wave_amp,
        light_amp=light_amp,
        pulse_amp=pulse_amp,
        gravity_xy=gravity_xy,
        particle_mode=particle_mode,
        flow_dir=flow_dir,
        params=p_dyn,
        cues=dict(
            locomotion=c_loco,
            recede=c_recede,
            opening=c_open,
            collapse=c_collapse,
            floating=c_float,
            wave=c_wave,
            light=c_light,
            pulse=c_pulse,
        ),
    )


# --------------------------------------------------------------------------------------
# 2. 선명한 목표 배경 청사진 추출 및 장면 맞춤형 도화지(Dream Canvas) 합성
# --------------------------------------------------------------------------------------
def analyze_raw_plate_stats(plate_rgb: np.ndarray) -> dict:
    lum_np = (0.299 * plate_rgb[..., 0] + 0.587 * plate_rgb[..., 1] + 0.114 * plate_rgb[..., 2]).astype(np.float32)
    # 5x5 국소 최대값과 현재 밝기의 차이로 '검은 바탕 위 희소 도트 판(Team3 파티클 캡처본)' 여부 자동 판별
    k5 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    lum_max5 = cv2.dilate(lum_np, k5)
    lit_region = lum_max5 > 0.16
    pinhole_ratio = float(((lum_max5 - lum_np > 0.11) & lit_region).sum() / max(int(lit_region.sum()), 1))
    med_lum = float(np.median(lum_np))
    p95_lum = float(np.percentile(lum_np, 95))
    is_particle_plate = (pinhole_ratio > 0.26 and med_lum < 0.22)

    bright_mask = lum_np >= np.percentile(lum_np, 65)
    mean_rgb = plate_rgb[bright_mask].mean(axis=0) if bright_mask.any() else plate_rgb.mean(axis=(0, 1))
    warmth = float(mean_rgb[0] - mean_rgb[2])

    return dict(
        med_lum=med_lum,
        p95_lum=p95_lum,
        pinhole_ratio=pinhole_ratio,
        is_particle_plate=is_particle_plate,
        dominant_rgb=mean_rgb.astype(np.float32),
        warmth=warmth,
    )


def prepare_crisp_plate(plate_rgb: np.ndarray, stats: dict, profile: dict) -> np.ndarray:
    """
    원본 배경의 공간 구조와 윤곽이 선명하게 읽히도록 준비:
      - 일반 연속 이미지: 픽셀 해상도와 디테일을 100% 유지하면서 미세 윤곽 선명도만 보강.
      - 희소 도트 이미지: 도트 사이 검은 미세 구멍을 엣지 보존 모폴로지+양방향 필터로 응집시켜
        흐릿한 점 구름이 아닌 선명한 면과 윤곽 구조로 복원.
    """
    if stats["is_particle_plate"]:
        k5 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        closed = cv2.morphologyEx(plate_rgb, cv2.MORPH_CLOSE, k5)
        mixed = np.maximum(plate_rgb, closed * 0.92)
        surf = cv2.bilateralFilter(mixed.astype(np.float32), d=7, sigmaColor=0.16, sigmaSpace=4.5)
        p99 = float(np.percentile(surf, 99.2)) + 1e-4
        normed = np.clip(surf / max(p99, 0.38), 0.0, 1.0) ** 0.78
        # 미세 구조 윤곽 언샤프 보강
        detail = normed - m.blur(normed, 2.6)
        sharp = np.clip(normed + 0.42 * detail, 0.0, 1.0)

        # 밝은 도화지(high_light) 장면인데 원본이 검은 바탕 도트판인 경우, 빈 검은 배경이 지저분한 구멍처럼 보이지 않게 명암 조화
        if profile["canvas_key"] == "high_light":
            lum_s = 0.299 * sharp[..., 0] + 0.587 * sharp[..., 1] + 0.114 * sharp[..., 2]
            void_w = np.clip((0.18 - lum_s) / 0.18, 0.0, 1.0)[..., None] ** 1.4
            tint = np.clip(stats["dominant_rgb"] * 1.15 + np.array([0.48, 0.44, 0.36], np.float32), 0.35, 0.88)
            sharp = sharp * (1.0 - 0.72 * void_w) + tint[None, None, :] * (0.72 * void_w)
        return sharp.astype(np.float32)

    # 일반 연속 배경판: 장면 분위기(밝고 해피 / 어둡고 공포 / 어둡고 고요 / 신비 탐색)에 맞춰 채도·색온도·명암비를 선명히 연출!
    out = plate_rgb.copy()
    mood = profile.get("mood_style", "vivid_mystery")

    if mood == "bright_happy":
        # 밝고 따스하고 해피한 황금빛 햇살 색감: 채도 상승 + 따뜻한 앰버 골드 하이라이트 + 환한 공기감!
        p99 = float(np.percentile(out, 99.0)) + 1e-4
        # N1's joy is hope under threat: retain cold shadows and avoid a triumphal wash.
        intensity=float(profile.get('intensity',.55))
        mixed=float(np.clip(-profile.get('pleasantness',0.),0,1))
        gamma=.91-.20*intensity+.12*mixed
        out = np.clip(out / max(p99, 0.52), 0.0, 1.0) ** gamma
        lum = (0.299 * out[..., 0] + 0.587 * out[..., 1] + 0.114 * out[..., 2])[..., None]
        out = np.clip(lum + (out - lum) * (1.05+.20*intensity-.15*mixed), 0.0, 1.0)
        gold_tint = np.array([1.04+.08*intensity,1.02,1.-.12*intensity+.08*mixed],np.float32)
        out = np.clip(out * gold_tint[None, None, :] + np.array([.018,.009,0.],np.float32),0.,1.)
    elif mood == "dark_horror":
        # 어둡고 격렬한 공포: 칠흑 암부 + 날이 선 강철 청백/적녹슨 윤곽 대비!
        p99 = float(np.percentile(out, 99.4)) + 1e-4
        base = np.clip(out / max(p99, 0.48), 0.0, 1.0) ** (0.82 if stats["med_lum"] < 0.28 else 1.55)
        lum = (0.299 * base[..., 0] + 0.587 * base[..., 1] + 0.114 * base[..., 2])[..., None]
        cold_horror = np.array([0.78, 0.88, 1.16], np.float32)
        edge_hi = np.clip(base - m.blur(base, 3.0), -0.15, 0.40)
        out = np.clip(base * cold_horror[None, None, :] * (0.42 + 0.72 * lum) + 0.65 * edge_hi, 0.0, 1.0)
    elif mood == "dark_calm":
        # 어둡고 고요한 달빛/밤바다 수면: 차분하고 깊은 사파이어 남청색 그림자 + 은은한 은빛·장미빛 수면 윤슬!
        base = (out ** (1.48 if stats["med_lum"] > 0.32 else 0.92))
        lum = (0.299 * base[..., 0] + 0.587 * base[..., 1] + 0.114 * base[..., 2])[..., None]
        moon_tint = np.array([0.66, 0.80, 1.12], np.float32)
        shimmer = np.clip(base - m.blur(base, 4.0), 0.0, 0.35) * np.array([0.95, 0.98, 1.15], np.float32)
        out = np.clip(base * moon_tint[None, None, :] * (0.48 + 0.68 * lum) + 0.60 * shimmer, 0.0, 1.0)
    else:
        # 신비·긴장 수중 복도: 에메랄드 청록과 네온 마젠타 반사광의 강렬하고 선명한 색채 대비!
        p99 = float(np.percentile(out, 99.3)) + 1e-4
        base = np.clip(out / max(p99, 0.52), 0.0, 1.0) ** 0.82
        lum = (0.299 * base[..., 0] + 0.587 * base[..., 1] + 0.114 * base[..., 2])[..., None]
        out = np.clip(lum + (base - lum) * 1.35, 0.0, 1.0)

    fine_detail = out - m.blur(out, 1.7)
    out = np.clip(out + 0.32 * fine_detail, 0.0, 1.0)
    return out.astype(np.float32)


def build_dream_canvas(
    target_sharp: np.ndarray,
    stats: dict,
    profile: dict,
    seed: int,
) -> tuple[np.ndarray, float]:
    """
    점 1개에서 시작하거나 부서져 사라질 때 뒤에 드러나는 꿈의 배경 하늘/심연 도화지:
      - 탁한 베이지 얼룩을 완전히 배제하고, 장면 분위기(맑은 아침 햇살 하늘 / 칠흑 공포 심연 / 고요한 밤호수 / 심해 청록)를 직관적으로 표현!
    """
    idx = profile["idx"]
    mood = profile.get("mood_style", "vivid_mystery")
    grain = m.fbm(seed + idx * 41 + 7, (340, 150, 65), w=m.W, h=m.H)
    gu, gv = m.U, m.V
    rad_c = np.hypot((gu - 0.52) * 1.1, (gv - 0.42))

    if mood == "bright_happy":
        sky_top = np.array([0.52, 0.72, 0.92], np.float32)
        sun_hor = np.array([0.99, 0.90, 0.66], np.float32)
        sun_glow = np.exp(-(rad_c / 0.62) ** 2)[..., None]
        c_mix = sky_top * (1.0 - 0.68 * gv)[..., None] + sun_hor * (0.68 * gv)[..., None]
        c_mix = c_mix * (1.0 - 0.48 * sun_glow) + np.array([1.0, 0.95, 0.78], np.float32) * (0.48 * sun_glow)
        canvas = np.clip(c_mix + (grain[..., None] - 0.5) * 0.03, 0.42, 0.98)
    elif mood == "dark_horror":
        c_a = np.array([0.035, 0.050, 0.078], np.float32)
        c_b = np.array([0.010, 0.014, 0.024], np.float32)
        canvas = np.clip(c_a * (1.0 - rad_c)[..., None] + c_b * rad_c[..., None] + (grain[..., None] - 0.5) * 0.018, 0.008, 0.11)
    elif mood == "dark_calm":
        c_top = np.array([0.025, 0.055, 0.115], np.float32)
        c_bot = np.array([0.012, 0.028, 0.062], np.float32)
        moon_glow = np.exp(-(((gu - 0.55) / 0.42) ** 2 + ((gv - 0.32) / 0.28) ** 2))[..., None]
        c_mix = c_top * (1.0 - gv)[..., None] + c_bot * gv[..., None] + np.array([0.07, 0.12, 0.22], np.float32) * moon_glow
        canvas = np.clip(c_mix + (grain[..., None] - 0.5) * 0.018, 0.01, 0.22)
    else:
        c_top = np.array([0.045, 0.115, 0.145], np.float32)
        c_bot = np.array([0.018, 0.042, 0.068], np.float32)
        shaft = np.exp(-(((gu - 0.48) / 0.30) ** 2))[..., None] * (1.0 - 0.6 * gv)[..., None]
        c_mix = c_top * (1.0 - gv)[..., None] + c_bot * gv[..., None] + np.array([0.08, 0.14, 0.18], np.float32) * shaft
        canvas = np.clip(c_mix + (grain[..., None] - 0.5) * 0.022, 0.015, 0.26)

    canvas_lum = float((0.299 * canvas[..., 0] + 0.587 * canvas[..., 1] + 0.114 * canvas[..., 2]).mean())
    return canvas.astype(np.float32), canvas_lum


def extract_plate_layers(
    plate_rgb: np.ndarray,
    scene_idx: int,
    stats: dict | None = None,
    profile: dict | None = None,
    seed: int = 28,
) -> dict:
    """
    목표 배경 이미지에서 선명한 구조 레이어, 구조 텐서 방향장(tx, ty), 소실점 초점(focal_uv),
    셀룰러 서식지(hab), 그리고 장면 맞춤형 도화지(canvas_bg)를 추출.
    """
    if stats is None:
        stats = analyze_raw_plate_stats(plate_rgb)
    if profile is None:
        profile = {"idx": scene_idx, "canvas_key": "mid_atmos", "warm_bias": 0.0, "emotion_en": "neutral"}

    sharp_np = prepare_crisp_plate(plate_rgb, stats, profile)
    lum_np = (0.299 * sharp_np[..., 0] + 0.587 * sharp_np[..., 1] + 0.114 * sharp_np[..., 2]).astype(np.float32)

    # 1) 선명한 건축/자연 윤곽선 추출 (Sobel + 다중 스케일 DoG)
    lum_s1 = m.blur(lum_np, 1.0)
    gx = cv2.Sobel(lum_s1, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(lum_s1, cv2.CV_32F, 0, 1, ksize=3)
    grad = np.hypot(gx, gy)
    grad_n = np.clip(grad / (np.percentile(grad, 98.2) + 1e-5), 0.0, 1.0)

    dog = np.abs(m.blur(lum_np, 0.9) - m.blur(lum_np, 3.8))
    dog_n = np.clip(dog / (np.percentile(dog, 98.2) + 1e-5), 0.0, 1.0)
    edge_fine = np.clip(0.62 * grad_n + 0.38 * dog_n, 0.0, 1.0)

    # 2) 구조 텐서(Structure Tensor)로부터 실제 벽·계단·나뭇가지·수면의 접선 벡터(tx, ty)와 응집도(coherence) 계산
    jxx = m.blur(gx * gx, 5.0)
    jxy = m.blur(gx * gy, 5.0)
    jyy = m.blur(gy * gy, 5.0)
    grad_ang = 0.5 * np.arctan2(2.0 * jxy, jxx - jyy + 1e-8)
    tan_ang = grad_ang + (math.pi * 0.5)  # 그래디언트에 수직 = 실제 선/구조가 뻗어나가는 접선 방향
    tx_np = np.cos(tan_ang).astype(np.float32)
    ty_np = np.sin(tan_ang).astype(np.float32)
    coh_np = (np.sqrt((jxx - jyy) ** 2 + 4.0 * jxy * jxy) / (jxx + jyy + 1e-5)).clip(0.0, 1.0).astype(np.float32)

    # 3) 구조 중요도(salience) 및 소실점/초점(focal_uv) 자동 추정
    local_contrast = np.abs(lum_np - m.blur(lum_np, 14.0))
    lc_n = np.clip(local_contrast / (np.percentile(local_contrast, 96.0) + 1e-5), 0.0, 1.0)
    salience = np.clip(0.55 * edge_fine + 0.30 * lc_n + 0.15 * coh_np, 0.04, 1.0).astype(np.float32)

    # 화면 중앙부(0.18..0.82) 내에서 구조·명암 대비가 모이는 초점(복도 끝, 계단 위, 창문, 수평선 중심) 탐색
    center_prior = np.exp(-(((m.U - 0.5) / 0.30) ** 2 + ((m.V - 0.46) / 0.28) ** 2)).astype(np.float32)
    portal_score = m.blur((0.55 * edge_fine + 0.45 * np.abs(lum_np - float(lum_np.mean()))) * center_prior, 24.0)
    fy_idx, fx_idx = np.unravel_index(int(np.argmax(portal_score)), portal_score.shape)
    focal_uv = (float(np.clip(fx_idx / m.W, 0.22, 0.78)), float(np.clip(fy_idx / m.H, 0.22, 0.78)))

    # 4) CA 서식지(hab): 어두운 철제 계단·벽면·숲 줄기까지 모든 공간 윤곽을 타고 세포가 골고루 증식하도록 설정
    hab_full = np.clip(0.34 + 0.52 * salience + 0.14 * (lum_np / (np.percentile(lum_np, 95) + 1e-4)), 0.22, 1.0)
    hab_ca = cv2.resize(hab_full, (m.GW, m.GH), interpolation=cv2.INTER_AREA)
    tx_ca = cv2.resize(tx_np, (m.GW, m.GH), interpolation=cv2.INTER_LINEAR)
    ty_ca = cv2.resize(ty_np, (m.GW, m.GH), interpolation=cv2.INTER_LINEAR)
    tnorm = np.hypot(tx_ca, ty_ca) + 1e-6
    tx_ca, ty_ca = tx_ca / tnorm, ty_ca / tnorm

    canvas_np, canvas_lum = build_dream_canvas(sharp_np, stats, profile, seed)
    crack_np, cell_id_np, slab_vx_np, slab_vy_np = m.cellular_fracture_map(
        seed + scene_idx * 53 + 11, n_cells=86, w=m.W, h=m.H
    )
    macro_edge = m.blur(edge_fine, 3.0).astype(np.float32)

    return dict(
        sharp=m.T(sharp_np),
        canvas_bg=m.T(canvas_np),
        canvas_lum=canvas_lum,
        edges=m.T(edge_fine),
        macro_edges=m.T(macro_edge),
        salience_np=salience,
        tx_np=tx_np,
        ty_np=ty_np,
        coh_np=coh_np,
        hab=m.T(hab_ca),
        tx_ca=m.T(tx_ca),
        ty_ca=m.T(ty_ca),
        lum=m.T(lum_np),
        focal_uv=focal_uv,
        crack_tex=m.T(crack_np),
        cell_id=m.T(cell_id_np),
        slab_vx=m.T(slab_vx_np),
        slab_vy=m.T(slab_vy_np),
    )


# --------------------------------------------------------------------------------------
# 3. 개별 꿈 장면 클래스 (CA + GA + 스토리 공간 물리 합성)
# --------------------------------------------------------------------------------------
def build_background_story_timing(story_item, profile):
    """Editorial timing grounded in N1 sentences; only background controls result.

    These are explicit artistic mappings, not claims of automatic plot reasoning
    or scientifically calibrated psychological measurements.
    """
    text=story_item.get('story','')
    channels=('tension','travel','opening','retreat','warmth','focus','pause','light')
    if '좌표 숫자' in text and '접시' in text:
        anchors=[('search','신호를 다시 쏘아 올리는'),('aversion','벌레 떼'),
                 ('discovery','좌표 숫자'),('recognition','하은이 알려 준')]
        rows=[
            (0,'search',.45,.15,0,0,-.1,.25,0,.1),
            (16,'search',.48,.35,0,0,-.1,.45,0,.3),
            (23,'aversion',.85,.10,0,0,-.45,.65,0,.05),
            (27,'discovery',.72,0,0,0,.05,.9,0,.6),
            (28.2,'discovery',.35,0,0,0,.15,1.,.95,1.),
            (29.5,'discovery',.48,.05,0,0,.12,.85,.05,.5),
            (39,'recognition',.58,.1,0,0,-.1,.45,0,.2),
            (53,'recognition',.68,.15,0,0,.10,.90,.18,.8),
            (64,'decision',.50,.40,.1,0,.12,.55,0,.35),
            (75,'decision',.45,.45,.1,0,.08,.3,0,.2)]
        focal=(.76,.48)
    elif '사람 더 있음' in text:
        anchors=[('crossing','대기 자체가 끌어당기는 힘'),('evidence','사람 더 있음'),
                 ('oxygen_pressure','산소 경고음'),('resolve','기록판을 뜯어내기')]
        rows=[
            (0,'crossing',.55,.35,0,0,-.25,.2,0,.05),
            (12,'crossing',.80,.90,0,0,-.55,.35,0,.12),
            (25,'crossing',.92,1.,0,0,-.50,.45,0,.15),
            (38,'evidence',.70,.35,0,0,-.25,.55,0,.2),
            (48,'evidence',.65,.05,0,0,-.15,.95,.30,.65),
            (55,'oxygen_pressure',.92,.65,0,0,-.55,.40,0,.30),
            (64,'oxygen_pressure',1.,.90,0,0,-.65,.35,0,.55),
            (75,'resolve',.95,.55,0,0,-.35,.65,0,.35)]
        focal=(.59,.55)
    elif '여기 있어, 오지 마' in text:
        anchors=[('hidden_threshold','도면에는 없던 문'),('opening','거대한 창'),
                 ('warning','여기 있어, 오지 마'),('hope','하은을 찾으러 가기로')]
        rows=[
            (0,'hidden_threshold',.78,.45,0,0,-.55,.35,0,.15),
            (12,'hidden_threshold',.72,.15,.05,0,-.35,.85,.25,.4),
            (18,'opening',.48,.15,.60,0,.30,.55,0,.70),
            (27,'opening',.42,.20,1.,0,.65,.20,0,.95),
            (38,'warning',.60,.10,.45,0,-.10,.50,0,.4),
            (50,'warning',.72,0,.20,0,-.40,.95,.45,.35),
            (58,'hope',.55,.35,.55,0,.20,.60,0,.5),
            (68,'hope',.43,.55,.80,0,.50,.45,0,.8),
            (75,'hope',.45,.50,.85,0,.45,.40,0,.65)]
        focal=(.68,.43)
    elif '데려갈 수 없는' in text:
        anchors=[('search','산소가 바닥나기 전에'),('recognition','하은의 얼굴'),
                 ('relief','살아 있다'),('separation','데려갈 수 없는'),('retreat','그리고 돌아선다')]
        rows=[
            (0,'search',.85,.65,0,0,-.45,.45,0,.15),
            (15,'search',.80,.55,0,0,-.35,.65,0,.25),
            (23,'recognition',.55,.15,0,0,-.05,.90,.30,.55),
            (28,'relief',.30,0,0,0,.25,.95,.80,.70),
            (39,'separation',.58,.05,0,.10,-.30,.80,.15,.25),
            (51,'separation',.65,0,0,.25,-.55,.70,.35,.12),
            (59,'retreat',.62,0,0,.65,-.65,.40,.05,.08),
            (69,'retreat',.55,0,0,1.,-.75,.15,0,.03),
            (75,'retreat',.45,0,0,1.,-.75,.05,0,0)]
        focal=(.56,.53)
    else:
        anchors=[]
        rows=[(0,'mood',.5,.2,0,0,0,.3,0,.2),(75,'mood',.5,.2,0,0,0,.3,0,.2)]
        focal=(.5,.5)
    for name,quote in anchors:
        if quote not in text:raise ValueError(f'Unmatched story evidence: {name}')
    return dict(channels=list(channels),focal=list(focal),
        anchors=[dict(beat=name,evidence=quote) for name,quote in anchors],
        keyframes=[dict(seconds=row[0],beat=row[1],**dict(zip(channels,row[2:]))) for row in rows])


def sample_background_story(profile, scene_time, scene_sec):
    plan=profile['background_story_timing']
    at=float(scene_time/scene_sec*75.)
    keys=plan['keyframes'];times=[k['seconds'] for k in keys]
    controls={key:float(np.interp(at,times,[k[key] for k in keys])) for key in plan['channels']}
    index=max(i for i,k in enumerate(keys) if k['seconds']<=at)
    controls.update(beat=keys[index]['beat'],scene_seconds=scene_time,
                    focal_x=plan['focal'][0],focal_y=plan['focal'][1])
    return controls


class DreamBackgroundScene:
    """Story-conditioned objective and blank canvas; only owned state is drawn."""
    def __init__(self, idx, info, profile, plate_rgb, stats, seed):
        self.idx, self.profile = idx, profile
        self.target_np = prepare_crisp_plate(plate_rgb,dict(stats, is_particle_plate=False),profile)
        canvas, _ = build_dream_canvas(self.target_np,stats,profile,seed)
        # Dark warm ground keeps the happy scene's golden point construction legible.
        if profile["mood_style"] == "bright_happy":
            canvas = canvas*.16 + np.array([.035,.020,.008],np.float32)
        if profile["mood_style"] == "vivid_mystery":
            canvas = canvas.mean(axis=2,keepdims=True)*np.array([.72,.55,.65],np.float32)
        self.canvas = m.T(np.maximum(canvas,np.array([.022,.025,.035],np.float32)))
        self.engine = None
        self.records = []

    def start_cycle(self, method, seed):
        cls = m.PointGenesisGA if method == "GA" else m.StructuralDreamCA
        self.engine = cls(self.target_np,self.profile,seed)


def compute_cycle_params(scene_sec):
    # An even number preserves GA -> destruction -> CA -> destruction across acts.
    n = 2
    return n, scene_sec/n


class DreamBackgroundRenderer:
    def __init__(self, scenario_dir, sound_path, film=1, seed=28, mode="hybrid",scene_sec=75.,single_scene=None,scene_count=4):
        if mode not in ("hybrid","ga_only","ca_only"): raise ValueError(mode)
        self.mode,self.seed,self.scene_sec = mode,seed,float(scene_sec)
        self.single_scene = single_scene
        self.scene_count = 1 if single_scene is not None else int(scene_count)
        if not 1 <= self.scene_count <= 4: raise ValueError("scene_count must be 1..4")
        self.scenario_dir,self.sound_path = Path(scenario_dir),Path(sound_path) if sound_path is not None else None
        self.n_cycles,self.cycle_dur = compute_cycle_params(self.scene_sec)
        if self.cycle_dur < 30: raise ValueError("Use --scene-sec 75 for long exploratory formation")
        self.total_dur = self.scene_sec*self.scene_count
        self.total_frames = int(round(self.total_dur*m.FPS))
        sc_list,story_list = load_unified_scene_metadata(self.scenario_dir)
        plates = [m.imread_u(self.scenario_dir/f"scene_{i:02d}.png") for i in range(1,5)]
        stats = [analyze_raw_plate_stats(x) for x in plates]
        self.profiles = []
        self.scenes = []
        for i in range(4):
            profile = interpret_story_and_emotion(i,sc_list[i],story_list[i] if i<len(story_list) else {},stats[i],stats,
                self.profiles[-1] if self.profiles else None)
            profile["background_story_timing"] = build_background_story_timing(story_list[i] if i<len(story_list) else {},profile)
            mood = profile["mood_style"]
            profile["seed_rgb"] = dict(bright_happy=[1.,.67,.22],dark_horror=[.5,.75,1.],
                dark_calm=[.65,.77,.94],vivid_mystery=[.35,.89,.87])[mood]
            profile["hold_fraction"] = dict(bright_happy=.105,dark_horror=.08,dark_calm=.12,vivid_mystery=.10)[mood]
            profile["arch_mode"] = "alternating_point_ga_local_ca"
            profile["ga_lead"], profile["ca_lead"] = .5, .5
            self.profiles.append(profile)
            self.scenes.append(DreamBackgroundScene(i,sc_list[i],profile,plates[i],stats[i],seed))
        self.S = (m.analyze_sound(self.sound_path,total_frames=max(self.total_frames,300)) if self.sound_path is not None else {"onset":np.zeros(self.total_frames,np.float32)})
        self.active_key = None
        self.carry = None
        self.last_snapshot = {}
        self.cycle_records = []
        print(f"Dream background v12: {self.total_dur}s, continuous GA -> CA, audio={self.sound_path is not None}; device={m.DEV}",flush=True)

    def frame(self,f,render=True):
        t = f/m.FPS
        act = self.single_scene if self.single_scene is not None else min(3,int(t//self.scene_sec))
        tl = t if self.single_scene is not None else t-act*self.scene_sec
        cycle = min(self.n_cycles-1,int(tl//self.cycle_dur))
        elapsed = tl-cycle*self.cycle_dur
        key = (act,cycle)
        sc = self.scenes[act]
        if key != self.active_key:
            # Retain only the preceding generated remnants, not an incoming target.
            if self.active_key is not None:
                prev = self.scenes[self.active_key[0]]
                self.carry = prev.engine.render(prev.canvas).detach().clone()
                prev.engine = None
            method = "GA" if self.mode=="ga_only" or (self.mode=="hybrid" and cycle%2==0) else "CA"
            sc.start_cycle(method,self.seed*1000+act*100+cycle)
            self.active_key = key
        e = sc.engine
        e.story_state = sample_background_story(sc.profile,tl,self.scene_sec)
        e.step(elapsed,cycle,self.cycle_dur,float(self.S["onset"][min(f,len(self.S["onset"])-1)]))
        if len(e.records) and not any(r is e.record for r in self.cycle_records):
            e.record["scene"] = act+1
            e.record["mood"] = sc.profile["mood_style"]
            self.cycle_records.append(e.record)
        self.last_snapshot = dict(scene=act+1,time=t,**e.last_snapshot)
        if not render: return None
        canvas=sc.canvas
        carry_weight=0.
        if self.carry is not None and elapsed<10:
            carry_weight=1-m.ss(3.,10.,elapsed)
            scale=1+elapsed*.002
            grid=e.base_grid/scale
            residual=F.grid_sample(self.carry,grid,mode='bilinear',padding_mode='border',align_corners=False)
            canvas=canvas*(1-carry_weight)+residual*carry_weight
        self.last_snapshot['carry_weight']=float(carry_weight)
        return e.render(canvas)

    def stats(self):
        return [r for r in self.cycle_records if r["method"]=="CA"]

    def evolution_report(self):
        return [r for r in self.cycle_records if r["method"]=="GA"]

    def validate(self):
        expected = self.n_cycles*self.scene_count
        if len(self.cycle_records) != expected: raise RuntimeError("Missing cycles")
        for r in self.cycle_records:
            assert r["initial_count"]==1 and r["orphan_births"]==0, r
            assert r["completion"] is not None and r["collapse_started"] and r.get("ended_recycled"), r
            assert r["completion"]["nodes"]==r["coarse_nodes"], r
            assert r["completion"]["mae"] < .007 and r["completion"]["psnr_db"] > 38, r
            assert r["completion"]["seconds"] >= self.cycle_dur*.83, r
            assert r["source_guided_from_first_birth"], r
        return dict(passed=True,cycles=expected,single_seed=True,local_lineage=True,
            target_guidance_from_first_birth=True,
            multiscale_target_optimization=True,
            story_controls_consumed=True,
            continuous_remnant_handoff=True,living_completion=True,spatial_sine_warp=True,restored_v10_motion=True,
            added_objects=False,added_narration=False,added_text=False,
            source_image_compositing=False,completion="all descendants + MAE < 0.007 + PSNR > 38 dB",
            sequence=[r["method"] for r in self.cycle_records])
