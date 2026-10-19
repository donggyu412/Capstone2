"""꿈 사운드 생성기 (3팀 · 사운드) — 네 단계, 단계마다 파일 하나.

  1 읽기  read.py     이야기 문장 → 소리가 날 시각 · 그림 수치 → 음색 · 그림 인식(vision.py) → 무슨 소리인지
  2 재료  pieces.py   1~5초 짧은 소리 조각을 자체 합성 (synth.py)
  3 진화  evolve.py   조각을 어떻게 배치·혼합할지 MAP-Elites 로 탐색 — 품질 = 듣기 좋은 정도
  4 렌더  render.py   고른 구성으로 75초 배치 → 배경 분위기 작곡(composition.py) → 꿈의 변형(dreamfx.py) → 공간
  + 해설 guide.py · 출처 provenance.py · 길이·파일 timing.py
"""
