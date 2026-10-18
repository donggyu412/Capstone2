# -*- coding: utf-8 -*-
"""
scene_decomposer.py — 원본 배경판 4계층 분해 + Open-Ended 변형장 진화 + 셀룰러 오토마타 통합 렌더러

핵심 구조:
  1. 4계층 시각 분해 (extract_plate_layers):
     - 원본 배경판(scene_01~04.png)을 인위적 도형 추가 없이 심층 안개 바탕(deep_bg), 중간 공간 구조(mid_body),
       고휘도 점묘 입자(high_dots), 공간 윤곽 선화(lines) 및 셀룰러 서식지(hab)로 분해.
  2. 비동기 셀룰러 기억 동역학 + 도트 박리 상전이:
     - 공간 위상이 서로 다른 셀룰러 에너지(ca.E)와 이동 파동(travel_wave)을 통해 한 장면(75초) 안에서도
       응집된 공간 구조가 점묘 입자와 선화로 박리(delamination)되었다가 재발아하며 끊임없이 유영.
  3. Open-Ended 변형장 진화 (FieldEvolution):
     - 18개 변형장 후보를 적합도(Fitness) + 새로움(Novelty) + 생존자 간 다양성(Diversity)으로 진화시켜
       기억 공간의 굴절·원근·열림을 비반복적으로 변주.
  4. 서사 물리 사건 및 3:15(195.0초) 클라이맥스 반전 + 장면 간 유산(Relic) 전이.
"""
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


def extract_plate_layers(plate_rgb: np.ndarray, scene_idx: int) -> dict:
    """원본 배경판(1920x1080 RGB float32 0..1)에서 4개 물리 계층과 셀룰러 서식지(habitat)를 추출."""
    lum_np = (0.299 * plate_rgb[..., 0] + 0.587 * plate_rgb[..., 1] + 0.114 * plate_rgb[..., 2]).astype(np.float32)

    # 1) 다중 스케일 주파수 분해: 심층 안개 바탕(deep_bg) / 중간 공간 몸체(mid_body) / 고휘도 도트 입자(high_dots)
    deep_bg = m.blur(plate_rgb, 38.0)
    mid_smooth = m.blur(plate_rgb, 4.2)
    mid_body = np.clip(mid_smooth - deep_bg * 0.72, 0.0, 1.2)
    high_dots = np.clip(plate_rgb - mid_smooth, 0.0, 1.0)

    # 2) 원본 기억 공간의 실제 구조 윤곽선(edge_lines): Sobel + DoG 결합
    gx = cv2.Sobel(m.blur(lum_np, 1.4), cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(m.blur(lum_np, 1.4), cv2.CV_32F, 0, 1, ksize=3)
    grad = np.hypot(gx, gy)
    grad = grad / (np.percentile(grad, 98.5) + 1e-5)
    dog = np.abs(m.blur(lum_np, 1.2) - m.blur(lum_np, 4.5))
    dog = dog / (np.percentile(dog, 98.5) + 1e-5)
    edge_lines = np.clip(0.55 * grad + 0.45 * dog, 0.0, 1.0) ** 1.15
    edge_lines = m.blur(edge_lines, 0.8)

    # 3) 셀룰러 오토마타 서식지(habitat, GH x GW): 밝기 분포 + 윤곽 밀도 결합
    hab_full = np.clip(0.14 + 0.68 * (lum_np / (np.percentile(lum_np, 96) + 1e-4)) + 0.32 * edge_lines, 0.08, 1.0)
    hab_small = cv2.resize(hab_full, (m.GW, m.GH), interpolation=cv2.INTER_AREA)

    return dict(
        raw=m.T(plate_rgb),
        deep_bg=m.T(deep_bg),
        mid_body=m.T(mid_body),
        high_dots=m.T(high_dots),
        lines=m.T(edge_lines),
        hab=m.T(hab_small),
        lum=m.T(lum_np),
    )


class DreamBackgroundScene:
    """원본 배경판 1장을 셀룰러 오토마타 및 시나리오별 서사 물리 법칙과 연동하는 장면 클래스."""

    FOG_COLORS_BY_FILM = {
        1: [
            ("#2a1723", 0.34, (6.0, -3.5)),   # 시나리오 1 - 1막(기, 놀람): 자홍·적갈색 바다 안개와 바람
            ("#141324", 0.44, (-4.0, 2.0)),   # 시나리오 1 - 2막(승, 공포): 좁은 선체 틈새의 서늘한 보라·암청 안개
            ("#122624", 0.32, (4.5, -7.0)),   # 시나리오 1 - 3막(전, 중립): 깊은 청록 어둠과 위로 피어오르는 황금빛 김
            ("#0f1830", 0.48, (3.5, 4.0)),    # 시나리오 1 - 4막(결, 공포): 푸른 창가 복도의 서늘한 심연 안개
        ],
        2: [
            ("#1e2114", 0.36, (-4.5, 2.0)),   # 시나리오 2 - 1막(기, 혐오): 파도 끝 녹슨 청동·올리브 수면 안개
            ("#171422", 0.46, (2.0, 4.8)),    # 시나리오 2 - 2막(승, 공포): 습한 복도와 바닥으로 꺼지는 곰팡이 암청 안개
            ("#282012", 0.28, (3.2, -4.5)),   # 시나리오 2 - 3막(전, 기쁨): 수면 위 천장처럼 번지는 따뜻한 황금빛 공기
            ("#0e162e", 0.42, (2.0, -6.5)),   # 시나리오 2 - 4막(결, 슬픔): 위로 솟구치는 푸른 천장 빛과 넓어지는 공간
        ],
        3: [
            ("#1a1a24", 0.42, (-2.5, 5.2)),   # 시나리오 3 - 1막(기, 공포): 벽 없는 회색 공간과 빗소리를 삼키는 구멍 안개
            ("#181822", 0.45, (1.5, 4.0)),    # 시나리오 3 - 2막(승, 공포): 차가운 회색 바닥과 무거운 정적 공기
            ("#142426", 0.30, (2.5, -5.2)),   # 시나리오 3 - 3막(전, 중립): 지붕의 흰 점으로 떠오르는 물방울과 햇살 먼지
            ("#121a2d", 0.38, (3.5, 2.2)),    # 시나리오 3 - 4막(결, 중립): 폐창고 슬레이트 틈 빛줄기와 맴도는 먼지 공기
        ],
    }

    def __init__(self, idx: int, info: dict, plate_rgb: np.ndarray, seed: int, film: int = 1):
        self.idx = idx
        self.film = film if film in self.FOG_COLORS_BY_FILM else 1
        self.info = info
        self.fog_color, self.fog_density, self.wind = self.FOG_COLORS_BY_FILM[self.film][idx]
        L = extract_plate_layers(plate_rgb, idx)
        self.base = L["raw"]
        self.deep_bg = L["deep_bg"]
        self.mid_body = L["mid_body"]
        self.high_dots = L["high_dots"]
        self.lines = L["lines"]
        self.hab = L["hab"]
        self.lum = L["lum"]
        self.glow_static = m.up(m.gblur(m.down(self.base), 4.0))

        self.flow_noise_x = m.T(m.fbm(seed + idx * 31 + 1, (180, 90, 45))) - 0.5
        self.flow_noise_y = m.T(m.fbm(seed + idx * 31 + 2, (180, 90, 45))) - 0.5

        gy, gx = torch.meshgrid(
            torch.linspace(-1.0, 1.0, m.H, device=m.DEV),
            torch.linspace(-1.0, 1.0, m.W, device=m.DEV),
            indexing="ij",
        )
        self.base_grid = torch.stack([gx, gy], dim=-1)[None]

    def attention(self, t: float, tl: float, S: dict, f: int) -> torch.Tensor:
        """장면 내부에서 셀룰러 발아 중심이 계속 이동하도록 시변 서식지 가중치(hab_dyn) 생성."""
        low = float(S["low"][f])
        mid = float(S["mid"][f])
        high = float(S["high"][f])
        on = float(S["onset"][f])

        u = torch.linspace(0.0, 1.0, m.GW, device=m.DEV).view(1, 1, 1, m.GW)
        v = torch.linspace(0.0, 1.0, m.GH, device=m.DEV).view(1, 1, m.GH, 1)

        if self.film == 2:
            if self.idx == 0:
                cx = 0.70 + 0.12 * math.sin(tl * 0.13)
                cy = 0.28 + 0.09 * math.cos(tl * 0.10)
                mass = torch.exp(-(((u - cx) / 0.26) ** 2 + ((v - cy) / 0.22) ** 2)) * (0.35 + 0.45 * high)
                sea_line = torch.exp(-((v - (0.56 + 0.06 * torch.sin(tl * 0.15 + u * 4.0))) / 0.12) ** 2) * (0.28 + 0.55 * low)
                return mass + sea_line
            if self.idx == 1:
                sink_y = 0.48 + 0.14 * m.ss(0.0, 68.0, tl)
                core = torch.exp(-(((u - 0.48) / 0.20) ** 2 + ((v - sink_y) / 0.22) ** 2))
                wall_l = torch.exp(-((u - (0.18 + 0.10 * math.sin(tl * 0.11))) / 0.16) ** 2)
                return 0.36 * core * (1.0 + 0.45 * low) + 0.30 * wall_l * (1.0 + 0.40 * on)
            if self.idx == 2:
                rev = m.gauss(t, m.CLIMAX, 5.0)
                dome = torch.exp(-(((u - (0.60 - 0.10 * math.sin(tl * 0.09))) / 0.28) ** 2 + ((v - 0.48) / 0.26) ** 2))
                rev_ring = torch.exp(-((torch.hypot(u - 0.58, v - 0.48) - 0.24) / 0.15) ** 2) * rev
                return 0.34 * dome * (1.0 + 0.38 * mid) + 0.68 * rev_ring
            rise_v = 0.65 - 0.45 * ((tl * 0.09) % 1.0)
            up_ray = torch.exp(-(((u - 0.36) / 0.24) ** 2 + ((v - rise_v) / 0.20) ** 2))
            fade_out = 1.0 - m.ss(54.0, 73.0, tl)
            return (0.36 * up_ray * (1.0 + 0.35 * mid)) * fade_out

        if self.film == 3:
            if self.idx == 0:
                rad = 0.22 + 0.06 * math.sin(tl * 0.18)
                hole = torch.exp(-(((u - 0.64) / rad) ** 2 + ((v - 0.24) / (rad * 0.85)) ** 2))
                floor_wet = torch.exp(-(((u - 0.64) / 0.25) ** 2 + ((v - 0.74) / 0.12) ** 2)) * (1.0 - 0.5 * m.ss(30.0, 70.0, tl))
                return 0.36 * hole * (1.0 + 0.45 * on) + 0.28 * floor_wet
            if self.idx == 1:
                stretch_v = 0.34 + 0.10 * m.ss(0.0, 68.0, tl)
                membrane = torch.exp(-(((u - 0.44) / 0.18) ** 2 + ((v - stretch_v) / 0.22) ** 2))
                floor_line = torch.exp(-((v - 0.72) / 0.09) ** 2) * torch.exp(-((u - 0.50) / 0.28) ** 2)
                return 0.34 * membrane + 0.34 * floor_line * (1.0 + 0.50 * on)
            if self.idx == 2:
                rev = m.gauss(t, m.CLIMAX, 5.0)
                cone = torch.exp(-(((u - (0.50 + 0.08 * math.sin(tl * 0.08))) / (0.16 + 0.14 * v)) ** 2))
                rev_halo = torch.exp(-((torch.hypot(u - 0.52, v - 0.52) - 0.22) / 0.15) ** 2) * rev
                return 0.34 * cone * (1.0 + 0.35 * mid) + 0.68 * rev_halo
            beam_u = 0.36 + 0.20 * math.sin(tl * 0.08)
            slate_beam = torch.exp(-((u - beam_u - 0.18 * v) / 0.22) ** 2)
            fade_out = 1.0 - m.ss(54.0, 73.0, tl)
            return (0.35 * slate_beam * (1.0 + 0.35 * mid)) * fade_out

        # 시나리오 1 (1_놀람공포중립공포)
        if self.idx == 0:
            cx = 0.34 + 0.18 * math.sin(tl * 0.14)
            cy = 0.30 + 0.12 * math.cos(tl * 0.11)
            cloud_wave = torch.exp(-(((u - cx) / 0.28) ** 2 + ((v - cy) / 0.24) ** 2))
            shock = sum(m.gauss(t, b / m.FPS, 0.9) for b in S["ev"]["s1_bounce"])
            deck_line = torch.exp(-((v - (0.56 - 0.12 * (u - 0.3))) / 0.11) ** 2) * (0.32 + 0.75 * shock + 0.35 * low)
            return 0.28 * cloud_wave + 0.38 * deck_line

        if self.idx == 1:
            pulse_u = (tl * 0.11) % 0.85
            wedge_wave = torch.exp(-((u - pulse_u) / 0.22) ** 2) * torch.exp(-((v - (0.42 + 0.12 * u)) / 0.26) ** 2)
            drip = sum(m.gauss(t, b / m.FPS, 1.1) for b in S["ev"]["s2_creak"])
            ring_d = torch.hypot((u - 0.58) * 1.4, v - 0.48)
            ring = torch.exp(-((ring_d - ((tl * 0.20) % 0.55)) / 0.08) ** 2) * (0.28 + 0.7 * drip + 0.3 * high)
            return 0.30 * wedge_wave + 0.36 * ring

        if self.idx == 2:
            diag = (u * 0.65 + v * 0.55)
            beam = torch.exp(-((diag - (0.52 + 0.12 * math.sin(tl * 0.10))) / (0.20 + 0.08 * m.ss(5, 60, tl))) ** 2)
            rev = m.gauss(t, m.CLIMAX, 5.0)
            rev_corona = torch.exp(-((torch.hypot(u - 0.44, v - 0.48) - 0.22) / 0.16) ** 2) * rev
            right_pillar = torch.exp(-((u - 0.75) / 0.09) ** 2) * (0.35 + 0.65 * rev)
            return 0.32 * beam * (1.0 + 0.4 * mid) + 0.65 * rev_corona + 0.28 * right_pillar

        shaft_phase = 0.28 + 0.24 * math.sin(tl * 0.09)
        shaft = torch.exp(-((u - shaft_phase - 0.22 * v) / 0.22) ** 2)
        fade_out = 1.0 - m.ss(54.0, 73.0, tl)
        return (0.34 * shaft * (1.0 + 0.35 * on)) * fade_out

    def compose_with_ca(self, t: float, tl: float, S: dict, f: int, ca: m.MemoryCA, evo_disp: torch.Tensor):
        """
        원본 배경판의 4개 물리 계층(deep_bg, mid_body, high_dots, lines)을
        셀룰러 상태(ca.M, ca.E, ca.ex, ca.Dm) 및 진화 변위장(evo_disp)으로 차등 변형·합성.
        """
        low = float(S["low"][f])
        mid = float(S["mid"][f])
        high = float(S["high"][f])
        on = float(S["onset"][f])

        M_up = m.up(m.gblur(ca.M, 1.6)).clamp(0.0, 1.0)
        E_up = m.up(m.gblur(ca.E, 1.8)).clamp(0.0, 1.0)
        ex_up = m.up(m.gblur(ca.ex, 2.0)).clamp(0.0, 1.0)
        front = (4.0 * M_up * (1.0 - M_up)).clamp(0.0, 1.0)

        shift_x = int((tl * 13.0) % m.W)
        shift_y = int((tl * 8.0) % m.H)
        nx = torch.roll(self.flow_noise_x, shifts=(shift_y, shift_x), dims=(2, 3))
        ny = torch.roll(self.flow_noise_y, shifts=(-shift_y, shift_x // 2), dims=(2, 3))

        wave_u = 0.5 + 0.5 * torch.sin(m.UT * 5.2 - m.VT * 3.8 - tl * 0.24 + self.idx * 1.3)
        wave_v = 0.5 + 0.5 * torch.cos(m.UT * 3.6 + m.VT * 4.8 - tl * 0.19 + self.idx * 0.9)
        spatial_wave = (0.62 + 0.52 * (0.6 * wave_u + 0.4 * wave_v)).clamp(0.45, 1.15)

        if self.film == 2:
            if self.idx == 0:
                water_zone = m.tss(0.46, 0.62, m.VT)
                cloud_zone = 1.0 - water_zone
                pinch = 0.024 * math.sin(tl * 0.15) - 0.022 * m.ss(10.0, 65.0, tl)
                scene_dx = (m.UT - 0.72) * pinch * cloud_zone + torch.sin(m.VT * 56.0 - tl * 3.2) * (0.010 + 0.016 * high) * water_zone + nx * 0.020
                scene_dy = (m.VT - 0.28) * pinch * cloud_zone + torch.cos(m.UT * 28.0 + tl * 2.2) * (0.008 + 0.012 * low) * water_zone + ny * 0.018
            elif self.idx == 1:
                sink = 0.032 * m.ss(5.0, 70.0, tl) * torch.exp(-((m.UT - 0.48) / 0.28) ** 2)
                stretch = 0.026 * math.sin(tl * 0.14) * (m.UT - 0.48)
                scene_dx = stretch + nx * (0.015 + 0.018 * ex_up)
                scene_dy = -sink + ny * (0.015 + 0.018 * ex_up)
                for b in S["ev"]["s2_creak"]:
                    dt_b = t - b / m.FPS
                    if 0.0 < dt_b < 3.2:
                        rd = torch.hypot((m.UT - 0.48) * 1.4, m.VT - 0.56)
                        ripple = torch.sin((rd - dt_b * 0.20) * 52.0) * torch.exp(-((rd - dt_b * 0.20) / 0.09) ** 2) * math.exp(-dt_b * 0.9)
                        scene_dx = scene_dx + ripple * 0.014
                        scene_dy = scene_dy + ripple * 0.014
            elif self.idx == 2:
                rev_env = m.gauss(t, m.CLIMAX, 4.5)
                rev_flip = 1.0 - 2.2 * rev_env
                dome_open = 0.030 * math.sin(tl * 0.10) + 0.026 * (M_up - 0.45)
                scene_dx = (m.UT - 0.58) * dome_open * rev_flip - (m.VT - 0.48) * 0.030 * rev_env + nx * (0.018 + 0.030 * rev_env)
                scene_dy = (0.016 * M_up * rev_flip) + (m.UT - 0.58) * 0.030 * rev_env + ny * (0.018 + 0.032 * rev_env)
            else:
                dissolve = m.ss(52.0, 74.0, tl)
                scene_dx = (m.UT - 0.42) * (-0.022 * m.ss(0.0, 68.0, tl)) + nx * (0.014 + 0.040 * dissolve)
                scene_dy = (0.022 * math.sin(tl * 0.11) + 0.018 * M_up) + ny * (0.015 + 0.045 * dissolve)

        elif self.film == 3:
            if self.idx == 0:
                breathe_hole = 0.032 * math.sin(tl * 0.18 + 0.8 * on)
                dx_h = m.UT - 0.64
                dy_h = m.VT - 0.24
                pull = torch.exp(-(dx_h ** 2 + dy_h ** 2) / 0.14)
                scene_dx = dx_h * breathe_hole * pull + nx * (0.018 + 0.018 * ex_up)
                scene_dy = dy_h * breathe_hole * pull + ny * (0.018 + 0.018 * ex_up)
            elif self.idx == 1:
                elongate = 0.028 * m.ss(0.0, 68.0, tl) * torch.exp(-((m.UT - 0.44) / 0.24) ** 2)
                scene_dx = (m.UT - 0.44) * 0.020 * math.sin(tl * 0.13) + nx * (0.014 + 0.016 * ex_up)
                scene_dy = -elongate * (1.0 - m.VT) + ny * (0.014 + 0.016 * ex_up)
                for b in S["ev"]["s2_creak"]:
                    dt_b = t - b / m.FPS
                    if 0.0 < dt_b < 3.2:
                        rd = torch.hypot((m.UT - 0.46) * 1.4, (m.VT - 0.72) * 1.8)
                        ripple = torch.sin((rd - dt_b * 0.22) * 54.0) * torch.exp(-((rd - dt_b * 0.22) / 0.09) ** 2) * math.exp(-dt_b * 0.9)
                        scene_dx = scene_dx + ripple * 0.014
                        scene_dy = scene_dy + ripple * 0.014
            elif self.idx == 2:
                rev_env = m.gauss(t, m.CLIMAX, 4.5)
                rev_flip = 1.0 - 2.2 * rev_env
                aperture = 0.030 * math.sin(tl * 0.10) + 0.026 * (M_up - 0.45)
                scene_dx = (m.UT - 0.52) * aperture * rev_flip - (m.VT - 0.52) * 0.030 * rev_env + nx * (0.018 + 0.030 * rev_env)
                scene_dy = (0.018 * M_up * rev_flip) + (m.UT - 0.52) * 0.030 * rev_env + ny * (0.018 + 0.032 * rev_env)
            else:
                dissolve = m.ss(52.0, 74.0, tl)
                swirl_ang = tl * 0.12
                scene_dx = 0.022 * math.cos(swirl_ang) * (m.VT - 0.45) + nx * (0.014 + 0.042 * dissolve)
                scene_dy = -0.022 * math.sin(swirl_ang) * (m.UT - 0.45) + ny * (0.014 + 0.045 * dissolve)

        else:
            if self.idx == 0:
                shock = sum(m.gauss(t, b / m.FPS, 0.55) * math.sin((t - b / m.FPS) * 16.0) for b in S["ev"]["s1_bounce"])
                water_zone = m.tss(0.44, 0.62, m.VT)
                cloud_zone = 1.0 - water_zone
                wave_x = torch.sin(m.VT * 48.0 - tl * 2.8 + m.UT * 6.0) * (0.010 + 0.014 * low + 0.016 * abs(shock)) * water_zone
                wave_y = (torch.cos(m.UT * 22.0 + tl * 1.9) * 0.006 * water_zone + shock * 0.015)
                swirl_x = (nx * (0.022 + 0.018 * ex_up) + 0.014 * math.sin(tl * 0.12) * (m.UT - 0.35)) * cloud_zone
                swirl_y = (ny * (0.018 + 0.015 * ex_up) + 0.010 * math.cos(tl * 0.10) * (m.VT - 0.30)) * cloud_zone
                scene_dx = wave_x + swirl_x
                scene_dy = wave_y + swirl_y
            elif self.idx == 1:
                breathe = 0.028 * math.sin(tl * 0.16) + 0.034 * m.ss(0.0, 70.0, tl)
                left_wedge = m.tss(0.65, 0.25, m.UT)
                scene_dx = (m.UT - 0.58) * breathe * (0.6 + 0.9 * left_wedge) + nx * (0.014 + 0.016 * ex_up)
                scene_dy = (m.VT - 0.48) * breathe * 0.72 + ny * (0.014 + 0.016 * ex_up)
                for b in S["ev"]["s2_creak"]:
                    dt_b = t - b / m.FPS
                    if 0.0 < dt_b < 3.2:
                        rd = torch.hypot((m.UT - 0.56) * 1.5, m.VT - 0.48)
                        ripple = torch.sin((rd - dt_b * 0.22) * 55.0) * torch.exp(-((rd - dt_b * 0.22) / 0.09) ** 2) * math.exp(-dt_b * 0.9)
                        scene_dx = scene_dx + ripple * 0.014
                        scene_dy = scene_dy + ripple * 0.014
            elif self.idx == 2:
                open_w = 0.032 * math.sin(tl * 0.11) + 0.028 * (M_up - 0.45)
                rev_env = m.gauss(t, m.CLIMAX, 4.5)
                rev_flip = 1.0 - 2.2 * rev_env
                scene_dx = (m.UT - 0.44) * open_w * rev_flip - (m.VT - 0.48) * 0.032 * rev_env + nx * (0.018 + 0.032 * rev_env)
                scene_dy = (-0.016 * M_up * rev_flip) + (m.UT - 0.44) * 0.032 * rev_env + ny * (0.020 + 0.034 * rev_env)
            else:
                dissolve = m.ss(52.0, 74.0, tl)
                push = sum(m.gauss(t, b, 2.2) for b in S["ev"]["s4_pushes"])
                scene_dx = (0.024 * math.sin(tl * 0.10) + 0.016 * push) * (m.VT - 0.28) + nx * (0.014 + 0.042 * dissolve)
                scene_dy = (-0.016 * m.ss(0.0, 68.0, tl)) + ny * (0.014 + 0.045 * dissolve)

        ca_disp = m.up(ca.Dm) / torch.tensor([m.W, m.H], device=m.DEV).view(1, 2, 1, 1)
        total_dx = scene_dx + evo_disp[:, 0:1] + ca_disp[:, 0:1]
        total_dy = scene_dy + evo_disp[:, 1:2] + ca_disp[:, 1:2]
        flow_vec = torch.cat([total_dx, total_dy], dim=1).permute(0, 2, 3, 1)

        # 3개 층을 서로 다른 배율(차등 패럴랙스)로 변형하여 깊이감과 입자 분리감을 형성
        dot_parallax = 1.45 + 0.75 * ex_up.permute(0, 2, 3, 1)
        grid_deep = (self.base_grid + flow_vec * 0.35).clamp(-1.0, 1.0)
        grid_mid = (self.base_grid + flow_vec * 1.00).clamp(-1.0, 1.0)
        grid_dots = (self.base_grid - flow_vec * dot_parallax).clamp(-1.0, 1.0)

        w_deep = F.grid_sample(self.deep_bg, grid_deep, mode="bilinear", padding_mode="reflection", align_corners=False)
        w_mid = F.grid_sample(self.mid_body, grid_mid, mode="bilinear", padding_mode="reflection", align_corners=False)
        w_dots = F.grid_sample(self.high_dots, grid_dots, mode="bilinear", padding_mode="reflection", align_corners=False)
        w_lines = F.grid_sample(self.lines, grid_mid, mode="bilinear", padding_mode="reflection", align_corners=False)

        body_vis = (0.38 + 0.74 * (M_up ** 0.78)) * (1.0 - 0.34 * ex_up) * (0.76 + 0.24 * E_up) * spatial_wave
        dots_vis = (0.36 + 0.88 * M_up + 0.78 * front + 0.55 * ex_up) * (1.0 + 0.35 * on + 0.22 * high)

        rgb = w_deep * (0.42 + 0.54 * M_up) + w_mid * body_vis * 1.24 + w_dots * dots_vis * 1.42

        # 3막 3:15(195.0s) 클라이맥스 반전 연출
        if self.idx == 2:
            rev = m.gauss(t, m.CLIMAX, 4.0)
            if rev > 1e-3:
                lum_c = m.lum(rgb)
                comp = torch.cat([rgb[:, 2:3] * 1.15, rgb[:, 0:1] * 1.05 + rgb[:, 1:2] * 0.35, rgb[:, 1:2] * 1.25], dim=1)
                cx_r = 0.58 if self.film == 2 else (0.52 if self.film == 3 else 0.45)
                radial = torch.hypot(m.UT - cx_r, m.VT - 0.50)
                ring_wave = 0.5 + 0.5 * torch.cos(radial * 28.0 - (t - m.CLIMAX) * 8.5)
                c1 = "#e8f6ff" if self.film == 2 else ("#ffe6a3" if self.film == 3 else "#ffe89e")
                c2 = "#ffd97d" if self.film == 2 else ("#7af0d8" if self.film == 3 else "#6bf2e6")
                corona_glow = (lum_c + 0.18 * front) * (m.col(c1) * ring_wave + m.col(c2) * (1.0 - ring_wave)) * 1.35
                rgb = rgb * (1.0 - 0.42 * rev) + (comp * 1.15 + corona_glow) * (0.78 * rev)

        line_vis = w_lines * (0.42 + 0.98 * front + 0.58 * ex_up)
        return rgb.clamp(0.0, 1.45), line_vis.clamp(0.0, 1.0)

    def motion(self, t: float, tl: float, S: dict, f: int):
        trem = S["trem"][f]
        if self.idx == 0:
            return math.sin(t * 0.14) * 3.5 + trem[0] * 0.5, math.cos(t * 0.11) * 2.5 + trem[1] * 0.5, 1.025 + 0.015 * math.sin(tl * 0.08), math.sin(t * 0.05) * 0.004
        if self.idx == 1:
            return trem[0] * 0.9, trem[1] * 0.9, 1.02 + 0.045 * m.ss(0, 75, tl), math.sin(t * 0.07) * 0.005
        if self.idx == 2:
            rev = m.gauss(t, m.CLIMAX, 3.5)
            return math.sin(t * 0.10) * 2.5, -tl * 0.08, 1.02 + 0.03 * math.sin(tl * 0.06) + 0.06 * rev, math.sin(t * 0.04) * 0.004 + 0.018 * rev
        return trem[0] * 0.6, trem[1] * 0.6, 1.05 - 0.04 * m.ss(0, 75, tl), math.sin(t * 0.04) * 0.003

    def spawn(self, t: float, tl: float, S: dict, f: int, P: m.Particles, rng: np.random.Generator, ca: m.MemoryCA):
        on = float(S["onset"][f])
        if self.film == 2:
            if self.idx == 0:
                if f in S["ev"]["s1_bounce"] or (on > 0.50 and rng.random() < 0.40):
                    n = 22 if f in S["ev"]["s1_bounce"] else 8
                    x = rng.uniform(0.35, 0.92, n) * m.W
                    y = rng.uniform(0.48, 0.85, n) * m.H
                    P.spawn(x, y, rng.normal(-6, 18, n), rng.uniform(-65, -18, n), rng.uniform(2.5, 5.2, n), grav=-12.0,
                            size=(rng.random(n) < 0.35), color=np.array([[0.86, 0.88, 0.68]]), amp=rng.uniform(0.40, 0.85, n), drag=0.30)
            elif self.idx == 1:
                if f in S["ev"]["s2_creak"] or rng.random() < 0.28:
                    n = 12 if f in S["ev"]["s2_creak"] else 3
                    x = rng.uniform(0.18, 0.68, n) * m.W
                    y = rng.uniform(0.10, 0.48, n) * m.H
                    P.spawn(x, y, rng.normal(0, 6, n), rng.uniform(60, 135, n), rng.uniform(1.8, 3.6, n), grav=68.0,
                            size=(rng.random(n) < 0.32), color=np.array([[0.82, 0.80, 0.96]]), amp=rng.uniform(0.42, 0.88, n), drag=0.15)
            elif self.idx == 2:
                rev = m.gauss(t, m.CLIMAX, 2.5)
                n = 14 if rev > 0.25 else (3 if rng.random() < 0.65 else 0)
                if n > 0:
                    x = rng.uniform(0.28, 0.86, n) * m.W
                    y = rng.uniform(0.22, 0.82, n) * m.H
                    col_p = np.array([[0.98, 0.92, 0.70]]) if rev < 0.3 else np.array([[0.88, 0.96, 1.00]])
                    P.spawn(x, y, rng.normal(4, 14, n), rng.uniform(-52, -16, n) * (1.0 + 1.2 * rev), rng.uniform(3.5, 6.8, n), grav=-10.0,
                            size=(rng.random(n) < 0.45), color=col_p, amp=rng.uniform(0.35, 0.80, n), drag=0.24)
            else:
                if tl < 64.0 and rng.random() < 0.55:
                    n = 4
                    x = rng.uniform(0.12, 0.68, n) * m.W
                    y = rng.uniform(0.25, 0.88, n) * m.H
                    P.spawn(x, y, rng.normal(6, 12, n), rng.uniform(-58, -22, n), rng.uniform(4.0, 7.8, n), grav=-18.0,
                            size=(rng.random(n) < 0.38), color=np.array([[0.72, 0.82, 1.00]]), amp=rng.uniform(0.30, 0.68, n), drag=0.20)
            return

        if self.film == 3:
            if self.idx == 0:
                if f in S["ev"]["s1_bounce"] or rng.random() < 0.48:
                    n = 16 if f in S["ev"]["s1_bounce"] else 4
                    x = rng.uniform(0.15, 0.88, n) * m.W
                    y = rng.uniform(0.12, 0.82, n) * m.H
                    vx = (0.64 * m.W - x) * 0.35
                    vy = (0.24 * m.H - y) * 0.35
                    P.spawn(x, y, vx, vy, rng.uniform(2.2, 4.5, n), grav=-8.0,
                            size=(rng.random(n) < 0.32), color=np.array([[0.84, 0.84, 0.94]]), amp=rng.uniform(0.35, 0.78, n), drag=0.25)
            elif self.idx == 1:
                if f in S["ev"]["s2_creak"] or rng.random() < 0.26:
                    n = 12 if f in S["ev"]["s2_creak"] else 3
                    x = rng.uniform(0.28, 0.68, n) * m.W
                    y = rng.uniform(0.18, 0.65, n) * m.H
                    P.spawn(x, y, rng.normal(0, 6, n), rng.uniform(55, 125, n), rng.uniform(1.8, 3.5, n), grav=62.0,
                            size=(rng.random(n) < 0.32), color=np.array([[0.88, 0.88, 0.96]]), amp=rng.uniform(0.40, 0.85, n), drag=0.16)
            elif self.idx == 2:
                rev = m.gauss(t, m.CLIMAX, 2.5)
                n = 14 if rev > 0.25 else (3 if rng.random() < 0.65 else 0)
                if n > 0:
                    x = rng.uniform(0.28, 0.76, n) * m.W
                    y = rng.uniform(0.20, 0.86, n) * m.H
                    col_p = np.array([[0.96, 0.94, 0.82]]) if rev < 0.3 else np.array([[0.80, 0.98, 0.92]])
                    P.spawn(x, y, rng.normal(0, 12, n), rng.uniform(-50, -16, n) * (1.0 + 1.2 * rev), rng.uniform(3.8, 7.2, n), grav=-14.0,
                            size=(rng.random(n) < 0.42), color=col_p, amp=rng.uniform(0.34, 0.78, n), drag=0.22)
            else:
                if tl < 64.0 and rng.random() < 0.55:
                    n = 4
                    x = rng.uniform(0.14, 0.74, n) * m.W
                    y = rng.uniform(0.12, 0.82, n) * m.H
                    P.spawn(x, y, rng.normal(12, 16, n), rng.normal(6, 14, n), rng.uniform(4.2, 8.2, n), grav=0.0,
                            size=(rng.random(n) < 0.36), color=np.array([[0.82, 0.88, 0.98]]), amp=rng.uniform(0.30, 0.65, n), drag=0.25)
            return

        if self.idx == 0:
            if f in S["ev"]["s1_bounce"] or (on > 0.55 and rng.random() < 0.35):
                n = 28 if f in S["ev"]["s1_bounce"] else 10
                x = rng.uniform(0.12, 0.78, n) * m.W
                y = (0.56 - 0.10 * (x / m.W - 0.3) + rng.normal(0, 0.02, n)) * m.H
                P.spawn(x, y, rng.normal(12, 28, n), rng.uniform(-95, -28, n), rng.uniform(2.2, 4.5, n), grav=38.0,
                        size=(rng.random(n) < 0.35), color=np.array([[0.96, 0.78, 0.86]]), amp=rng.uniform(0.45, 0.90, n), drag=0.35)
            elif rng.random() < 0.45:
                x = rng.uniform(0.05, 0.85, 2) * m.W
                y = rng.uniform(0.08, 0.52, 2) * m.H
                P.spawn(x, y, rng.normal(6, 10, 2), rng.uniform(-12, 8, 2), rng.uniform(4.0, 7.5, 2),
                        size=(rng.random(2) < 0.25), color=np.array([[0.90, 0.72, 0.82]]), amp=rng.uniform(0.25, 0.55, 2), drag=0.2)
        elif self.idx == 1:
            if f in S["ev"]["s2_creak"] or rng.random() < 0.22:
                n = 12 if f in S["ev"]["s2_creak"] else 2
                x = rng.uniform(0.15, 0.75, n) * m.W
                y = rng.uniform(0.08, 0.35, n) * m.H
                P.spawn(x, y, rng.normal(-4, 8, n), rng.uniform(55, 130, n), rng.uniform(1.8, 3.4, n), grav=65.0,
                        size=(rng.random(n) < 0.3), color=np.array([[0.82, 0.80, 0.98]]), amp=rng.uniform(0.40, 0.85, n), drag=0.15)
        elif self.idx == 2:
            rev = m.gauss(t, m.CLIMAX, 2.5)
            n = 14 if rev > 0.25 else (3 if rng.random() < 0.65 else 0)
            if n > 0:
                u0 = rng.uniform(0.18, 0.78, n)
                v0 = np.clip(0.22 + 0.65 * u0 + rng.normal(0, 0.08, n), 0.10, 0.92)
                col_p = np.array([[0.98, 0.90, 0.68]]) if rev < 0.3 else np.array([[0.75, 0.98, 0.92]])
                P.spawn(u0 * m.W, v0 * m.H, rng.normal(8, 18, n), rng.uniform(-48, -14, n) * (1.0 + 1.2 * rev),
                        rng.uniform(3.5, 7.0, n), grav=-6.0, size=(rng.random(n) < 0.45), color=col_p,
                        amp=rng.uniform(0.32, 0.78, n), drag=0.25)
        else:
            if tl < 64.0 and rng.random() < 0.50:
                n = 3
                x = rng.uniform(0.18, 0.62, n) * m.W
                y = rng.uniform(0.08, 0.72, n) * m.H
                P.spawn(x, y, rng.uniform(10, 26, n), rng.uniform(12, 32, n), rng.uniform(4.0, 8.0, n),
                        size=(rng.random(n) < 0.35), color=np.array([[0.68, 0.78, 1.00]]), amp=rng.uniform(0.28, 0.62, n), drag=0.22)


class FieldEvolution:
    """Open-Ended 공간 변형장 진화 탐색기 (적합도 + 새로움 + 생존 다양성 기반 유전자 선발)."""

    def __init__(self, seed: int):
        self.rng = np.random.default_rng(seed)
        self.yy, self.xx = np.mgrid[-1:1:36j, -1:1:64j].astype(np.float32)
        self.parents = self.rng.normal(0.0, 0.24, (3, 10)).astype(np.float32)
        self.archive = []
        self.logs = []
        self.target = np.zeros((2, 36, 64), np.float32)
        self.current = self.target.copy()
        self.last = -999.0
        self.memory = 0.20

    def field(self, g: np.ndarray) -> np.ndarray:
        x, y = self.xx, self.yy
        dx = g[0] * np.sin(2.1 * y + g[4]) + g[1] * np.sin(3.0 * x + 2.0 * y + g[5]) + g[6] * y * x
        dy = g[2] * np.sin(2.4 * x + g[5]) + g[3] * np.sin(2.0 * x - 3.0 * y + g[4]) + g[7] * (x * x - y * y)
        return np.stack([dx, dy]).astype(np.float32)

    def step(self, t: float, affect: float, energy: float, onset: float):
        self.memory = 0.999 * self.memory + 0.001 * (0.65 * affect + 0.25 * energy + 0.10 * onset)
        if t - self.last >= 11.5:
            candidates = [p.copy() for p in self.parents]
            for _ in range(15):
                a, b = self.parents[self.rng.integers(3, size=2)]
                child = 0.5 * (a + b) + self.rng.normal(0.0, 0.11 + 0.13 * self.memory, 10)
                candidates.append(np.clip(child, -1.0, 1.0).astype(np.float32))
            results = []
            for g in candidates:
                fld = self.field(g)
                desc = fld[:, ::7, ::12].ravel()
                novel = min([float(np.sqrt(np.mean((desc - old) ** 2))) for old in self.archive], default=0.32)
                slope = np.mean(np.abs(np.diff(fld, axis=1))) + np.mean(np.abs(np.diff(fld, axis=2)))
                continuity = np.mean((fld - self.current) ** 2)
                fitness = float(np.exp(-3.8 * slope - 1.2 * continuity))
                score = 0.54 * fitness + 0.46 * min(novel, 1.0)
                results.append((score, g, fld, desc, fitness, novel))
            results.sort(key=lambda r: r[0], reverse=True)
            chosen = []
            for r in results:
                if not chosen or min(np.sqrt(np.mean((r[3] - q[3]) ** 2)) for q in chosen) > 0.12:
                    chosen.append(r)
                if len(chosen) == 3:
                    break
            while len(chosen) < 3:
                chosen.append(results[len(chosen)])
            self.parents = np.stack([c[1] for c in chosen])
            self.target = chosen[0][2]
            self.archive.append(chosen[0][3])
            self.archive = self.archive[-24:]
            self.logs.append(dict(
                seconds=round(t, 2),
                fitness=round(chosen[0][4], 4),
                novelty=round(chosen[0][5], 4),
                survivor_distance=round(float(np.linalg.norm(chosen[0][3] - chosen[1][3])), 4),
                affect_memory=round(float(self.memory), 4),
            ))
            self.last = t
        self.current += (self.target - self.current) * 0.0045
        return self.current


class DreamBackgroundRenderer:
    """원본 배경판 + 점묘 입자계 + 기억 셀룰러 오토마타 + Open-Ended 변형장 진화를 통합한 렌더러."""

    def __init__(self, scenario_dir: Path, sound_path: Path, film: int = 1, seed: int = 28):
        self.film = film
        self.seed = seed
        self.scenario_dir = Path(scenario_dir)
        self.sound_path = Path(sound_path)

        t0 = time.time()
        self.scenes_json = json.loads((self.scenario_dir / "scenes.json").read_text(encoding="utf-8-sig"))
        story_file = self.scenario_dir / "dream_scenes.json"
        self.story = json.loads(story_file.read_text(encoding="utf-8-sig")) if story_file.exists() else []

        infos = []
        for sc in self.scenes_json["scenes"]:
            en = m.EMO_KO[sc["emotion"]]
            infos.append(dict(
                stage=sc.get("stage") or sc.get("act", ""),
                title=sc.get("title", ""),
                emotion_ko=sc["emotion"],
                emotion=en,
                intensity=float(sc.get("intensity", 0.6)),
                backgrounds=sc.get("backgrounds", []),
                params=m.emo_params(en, float(sc.get("intensity", 0.6))),
            ))
        self.infos = infos

        print(f"[1/3] 사운드 다대역 스펙트럼 분석 ({self.scenario_dir.name}): {self.sound_path.name}")
        S = m.analyze_sound(self.sound_path)
        S["ev"] = m.build_events(S, seed)
        rng = np.random.default_rng(seed + 1)
        trem = np.cumsum(rng.normal(0, 0.5, (m.N, 2)), 0)
        trem -= np.stack([m.ema(trem[:, 0], 0.6), m.ema(trem[:, 1], 0.6)], 1)
        S["trem"] = np.clip(trem, -3, 3)
        self.S = S

        print("[2/3] 원본 배경판 4장 4계층 분해 및 비동기 MemoryCA 초기화")
        plates = [m.imread_u(self.scenario_dir / f"scene_{i:02d}.png") for i in range(1, 5)]
        self.scenes = [DreamBackgroundScene(i, infos[i], plates[i], seed, film=film) for i in range(4)]
        self.cas = [m.MemoryCA(s.hab, seed * 100 + i) for i, s in enumerate(self.scenes)]

        u_ca = torch.linspace(0.0, 1.0, m.GW, device=m.DEV).view(1, 1, 1, m.GW)
        v_ca = torch.linspace(0.0, 1.0, m.GH, device=m.DEV).view(1, 1, m.GH, 1)
        self.u_ca, self.v_ca = u_ca, v_ca
        for idx_c, ca in enumerate(self.cas):
            phase_f = 0.5 + 0.5 * torch.sin(u_ca * 6.28 + v_ca * 4.71 + idx_c * 1.57)
            ca.E = (0.38 + 0.58 * phase_f * ca.rand()).clamp(0.25, 1.0)
            ca.cons = (0.42 + 0.55 * (1.0 - phase_f) + 0.25 * ca.rand()).clamp(0.35, 1.15)

        self.evo = [FieldEvolution(seed * 10 + i) for i in range(4)]
        self.relics = [torch.zeros_like(c.M) for c in self.cas]

        self.lat8 = m.Lattice(8, seed + 11, 1.0, aa=1.1, rmax=0.47, jit=0.16)
        self.lat4 = m.Lattice(4, seed + 12, 1.0, aa=0.9, rmax=0.46, jit=0.10)
        self.lat24 = m.Lattice(24, seed + 13, 0.24, aa=3.0, rmax=0.50, jit=0.20)
        self.P = m.Particles()
        self.prng = np.random.default_rng(seed + 2)
        self.fogA = m.T(m.fbm(91 + film, (200, 100, 50), w=960, h=540))
        self.fogB = m.T(m.fbm(92 + film, (140, 70, 35), w=960, h=540))
        self.windX = m.T(m.fbm(93 + film, (300, 150, 75), w=960, h=540))
        self.windY = m.T(m.fbm(94 + film, (300, 150, 75), w=960, h=540))
        self.linephase = m.up(m.T(np.random.default_rng(seed + 3).random((m.GH // 4 + 1, m.GW // 4 + 1)).astype(np.float32)) * 6.28)
        self.prev = None
        self.vg = None
        print(f"      초기화 완료 ({time.time() - t0:.1f}s)")

    def active(self, t: float) -> list[int]:
        acts = []
        for i in range(4):
            a, b = m.SCENE_T[i], m.SCENE_T[i + 1]
            lo = a - m.PRE if i > 0 else -1.0
            hi = b + m.POST if i < 3 else 1e9
            if lo <= t < hi:
                acts.append(i)
        return acts

    def scene_gate(self, i: int, t: float) -> float:
        a, b = m.SCENE_T[i], m.SCENE_T[i + 1]
        g_in = 1.0 if i == 0 else m.ss(a - m.PRE, a + 8.0, t)
        g_out = 1.0 if i == 3 else 1.0 - m.ss(b - 2.0, b + m.POST, t)
        return g_in * g_out

    def global_gate(self, t: float) -> float:
        return m.ss(1.0, 15.0, t) * (1.0 - m.ss(286.0, 299.3, t))

    def params_at(self, t: float):
        i = min(3, max(0, int(np.searchsorted(m.SCENE_T, t, side="right") - 1)))
        p = self.infos[i]["params"]
        if i < 3:
            w = m.ss(m.SCENE_T[i + 1] - m.PRE, m.SCENE_T[i + 1] + 8.0, t)
            if w > 0:
                p = m.mix_params(p, self.infos[i + 1]["params"], w)
        return p, i

    def scene_layer(self, i: int, t: float, f: int, p: dict, gate: float, render: bool = True):
        sc, ca = self.scenes[i], self.cas[i]
        tl = t - m.SCENE_T[i]
        S = self.S
        g_s = self.scene_gate(i, t)

        force = 0.0
        if i < 3:
            force = 0.88 * m.ss(m.SCENE_T[i + 1] - 2.0, m.SCENE_T[i + 1] + m.POST, t)
        else:
            force = 0.72 * m.ss(54.0, 73.5, tl)

        seed_bias = None
        if i > 0 and t < m.SCENE_T[i] + 12.0:
            seed_bias = torch.maximum(self.cas[i - 1].M, self.relics[i - 1])

        travel_wave = 0.5 + 0.5 * torch.sin(self.u_ca * 5.5 - self.v_ca * 4.2 - tl * 0.22 + i * 1.4)
        ca.E = (ca.E + m.DT * 0.018 * travel_wave * sc.hab).clamp(0.0, 1.0)

        if i == 2:
            rev_ca = m.gauss(t, m.CLIMAX, 4.2)
            if rev_ca > 1e-3:
                cx_ca = 0.58 if self.film == 2 else (0.52 if self.film == 3 else 0.45)
                corona_ca = torch.exp(-((torch.hypot(self.u_ca - cx_ca, self.v_ca - 0.50) - 0.18) / 0.22) ** 2)
                ca.E = (ca.E + 0.08 * rev_ca * (0.4 + 0.6 * corona_ca)).clamp(0.0, 1.0)
                ca.ex = torch.where(corona_ca * rev_ca > 0.25, torch.zeros_like(ca.ex), ca.ex)
                ca.M = (ca.M + 0.06 * rev_ca * (sc.hab + 0.5 * corona_ca)).clamp(0.0, 1.0)

        ca.step(p, float(S["onset"][f]), gate * max(g_s, 0.02), sc.attention(t, tl, S, f), force, seed_bias)
        self.relics[i] = torch.maximum(self.relics[i], ca.M * 0.82)
        self.evo[i].step(t, float(p["mut"]) / 1.6, float(ca.E.mean()), float(S["onset"][f]))

        if g_s > 0.25:
            sc.spawn(t, tl, S, f, self.P, self.prng, ca)
        if not render:
            return None

        fld = m.T(self.evo[i].current.transpose(1, 2, 0))
        evo_disp = F.interpolate(fld, size=(m.H, m.W), mode="bilinear", align_corners=False) * (0.026 + 0.018 * float(ca.ex.mean()))

        rgb, ln = sc.compose_with_ca(t, tl, S, f, ca, evo_disp)

        if i > 0:
            for prev_i in range(max(0, i - 2), i):
                w_decay = math.exp(-max(t - m.SCENE_T[prev_i + 1], 0.0) / (75.0 if i == 3 else 52.0))
                if w_decay > 0.03:
                    rel_mask = m.up(self.relics[prev_i] * (0.4 + 0.6 * ca.M)).clamp(0.0, 1.0)
                    wave_band = 0.5 + 0.5 * torch.sin(m.UT * 14.0 + m.VT * 11.0 + tl * 0.12 + prev_i * 1.7)
                    recall = (rel_mask * wave_band * (0.14 + 0.16 * float(S["mid"][f])) * w_decay).clamp(0.0, 0.34)
                    donor = self.scenes[prev_i].mid_body * 1.15 + self.scenes[prev_i].high_dots * 1.25
                    rgb = rgb * (1.0 - recall * 0.55) + donor * recall

        x = torch.cat([rgb, ln], 1)
        ox, oy, zoom, rot = sc.motion(t, tl, S, f)
        wa = 2.4 * p["flow"] + 1.5
        wx = m.sample_noise(self.windX, t * 0.0035 * p["flow"], t * 0.002, 1.0) - 0.5
        wy = m.sample_noise(self.windY, -t * 0.0025, t * 0.0035 * p["flow"], 1.0) - 0.5
        disp = torch.cat([wx, wy], 1) * wa * 1.6 + ca.Dm * 0.75
        if p["twist"] > 0.01:
            disp = disp + torch.cat([wy, -wx], 1) * 10.0 * p["twist"] * (0.5 + 0.5 * math.sin(t * 0.28))
        trem = S["trem"][f] * p["jitter"] * 1.2
        grid = m.make_grid(ox + trem[0], oy + trem[1], zoom, rot, m.up(disp))
        x = F.grid_sample(x, grid, mode="bilinear", padding_mode="border", align_corners=False)
        rgb, ln = x[:, :3].clamp(min=0.0), x[:, 3:4]

        M = ca.M
        M_dot = (M + 0.58 * ca.ex * sc.hab).clamp(0.0, 1.0)
        Cc = m.down(rgb)
        Mg = m.up(m.gblur(M_dot, 2.0))
        glow = m.up(m.gblur(Cc, 2.4))
        base_vis = gate * g_s * (0.24 + 0.76 * Mg)
        layer = glow * base_vis * 0.56 + rgb * base_vis * 0.46

        breath = p["breath"] + 0.24 * float(S["mid"][f])
        swell = 0.20 * float(S["onset"][f]) * p["flash"]
        Vc = (m.lum(Cc).clamp(0.0, 1.25) ** 0.80) * (0.26 + 0.86 * M_dot) * 1.32
        dots = self.lat8.render(Cc * 1.32 + 0.01, Vc, t, breath, gate * g_s, swell)

        Cc4 = m.down(rgb, m.H // 4, m.W // 4)
        M4 = F.interpolate(M_dot, size=(m.H // 4, m.W // 4), mode="bilinear", align_corners=False)
        fine = self.lat4.render(Cc4 * 1.25, ((m.lum(Cc4) - 0.20).clamp(min=0.0) * 1.85) * (0.28 + 0.78 * M4), t * 1.25, breath * 0.6, gate * g_s) * 0.24

        Cc24 = m.down(rgb, m.H // 24, m.W // 24)
        M24 = m.down(M_dot, m.H // 24, m.W // 24)
        bok = self.lat24.render(Cc24 * 1.18, (m.lum(Cc24).clamp(0.0, 1.0) ** 1.05) * M24 * 0.96, t * 0.55, breath * 1.35, gate * g_s, swell) * 0.32

        reveal = m.tss(0.14, 0.58, m.up(M_dot)) * (0.65 + 0.35 * torch.sin(t * 1.6 + self.linephase))
        lines = ln * reveal * gate * g_s * 0.28 * (rgb * 0.78 + 0.42)
        return layer + dots * 0.92 + fine + bok + lines

    def frame(self, f: int, render: bool = True):
        for relic in self.relics:
            relic.mul_(0.99982)
        t = f / m.FPS
        S = self.S
        p, si = self.params_at(t)
        gate = self.global_gate(t)
        acts = self.active(t)
        img = None
        for i in acts:
            L = self.scene_layer(i, t, f, p, gate, render)
            if render:
                img = L if img is None else 1 - (1 - img.clamp(0, 1)) * (1 - L.clamp(0, 1))
        sc = self.scenes[si]
        self.P.step(sc.wind)
        if not render:
            return None
        img = img + self.P.render(gate)

        fd = sc.fog_density
        fc = m.col(sc.fog_color)
        if si < 3:
            w = m.ss(m.SCENE_T[si + 1] - m.PRE, m.SCENE_T[si + 1] + 8.0, t)
            if w > 0:
                fd = fd + (self.scenes[si + 1].fog_density - fd) * w
                fc = fc + (m.col(self.scenes[si + 1].fog_color) - fc) * w
        ox, oy = sc.wind[0] * t / m.W * 0.6, sc.wind[1] * t / m.H * 0.6
        fog = 0.6 * m.sample_noise(self.fogA, ox, oy, 1.0) + 0.4 * m.sample_noise(self.fogB, -ox * 0.7, oy * 1.3 + t * 0.001, 1.4)
        fog = m.up(m.tss(0.32, 0.85, fog))
        fd = fd * (0.85 + 0.3 * float(S["low"][f]))
        img = img * (1 - fd * 0.30 * fog) + fc * fog * fd * 0.32 * gate

        L_ = m.lum(img)
        img = L_ + (img - L_) * p["sat"]
        img = img * torch.tensor([1 + p["warm"] * 0.6, 1.0, 1 - p["warm"] * 0.6], device=m.DEV).view(1, 3, 1, 1)
        img = 1 - torch.exp(-img.clamp(min=0) * 1.15)

        vign = p["vign"]
        if si == 3:
            vign = vign + 0.25 * m.ss(225, 290, t) + 0.05 * math.sin(t * 1.1)
        if self.vg is None:
            self.vg = torch.hypot((m.UT - 0.5) * 1.5, (m.VT - 0.5) * 1.15)
        img = img * (1 - vign * self.vg ** 2.2).clamp(0, 1)

        if self.prev is not None:
            img = img + (self.prev * p["trail"] - img).clamp(min=0) * 0.65
        self.prev = img

        hl = m.up(m.gblur(m.down((m.lum(img) - 0.55).clamp(min=0)), 3.0))
        img = img + hl * torch.tensor([1.0, 0.55, 0.42], device=m.DEV).view(1, 3, 1, 1) * 0.35
        fl = 1 + 0.012 * math.sin(t * 13.7) + p["flicker"] * 0.05 * math.sin(t * 7.3 + math.sin(t * 2.1) * 3)
        gr = F.interpolate(torch.randn((1, 1, m.H // 2, m.W // 2), device=m.DEV), scale_factor=2, mode="nearest")
        img = (img * fl + gr * 0.007 * (0.4 + gate)).clamp(0, 1)
        return img

    def stats(self) -> list[dict]:
        return [dict(scene=i + 1, sparks=int(c.births), forgets=int(c.forgets)) for i, c in enumerate(self.cas)]

    def evolution_report(self) -> list[dict]:
        return [dict(scene=i + 1, generations=e.logs) for i, e in enumerate(self.evo)]

