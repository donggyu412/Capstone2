# config.py — GridModel v2 scene/storyboard input
# ============================================================
# Unity Grid Image Model -> Python v1.3
# 추가점:
# 1) 이미지가 거의 완성된 뒤에도 CA가 완전히 멈추지 않음
# 2) 다만 원본 이미지에서 크게 벗어나지 않도록
#    "낮은 확률의 주변 영향" + "target으로 복귀하는 tether" 사용
# 3) 즉, 몽환적으로 미세하게 살아있는 화면을 만듦
# ============================================================

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ============================================================
# INPUT STRUCTURE
# Team4/
# ├─ GridModel/
# │  ├─ config.py
# │  └─ pythonimagemodel.py
# └─ input/
#    ├─ objects/
#    │  └─ scene_01~04/
#    └─ storyboard/
#       ├─ scene_01.png ~ scene_04.png
#       ├─ scenes.json
#       └─ dream_scenes.json
# ============================================================
INPUT_DIR = ROOT / "input"
OBJECTS_DIR = INPUT_DIR / "objects"
STORYBOARD_DIR = INPUT_DIR / "storyboard"

SCENES_JSON = STORYBOARD_DIR / "scenes.json"
DREAM_SCENES_JSON = STORYBOARD_DIR / "dream_scenes.json"

# 사운드는 input 아래 어디에 있어도 재귀적으로 찾습니다.
DATA_DIR = INPUT_DIR

# 결과물
OUT_DIR = ROOT / "output"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ------------------------------------------------------------
# GRID / OUTPUT
# 1920x1080 최종 출력용 설정
# 내부 CA grid는 960x540, 최종 출력은 2배 nearest upscale
# ------------------------------------------------------------
GRID_WIDTH = 960
GRID_HEIGHT = 540

OUTPUT_WIDTH = 1920
OUTPUT_HEIGHT = 1080

UPSCALE_INTEGER = 2
UPSCALED_WIDTH = GRID_WIDTH * UPSCALE_INTEGER     # 1200
UPSCALED_HEIGHT = GRID_HEIGHT * UPSCALE_INTEGER   # 720
PAD_BACKGROUND = 0.0

SIMULATION_FPS = 26
VIDEO_FPS = 30
MAX_FRONTIER_CELLS_PER_TICK = 16000

NOISE_RESOLUTION_DIVISOR = 8
NOISE_UPDATE_FPS = 6

# ------------------------------------------------------------
# AUDIO
# ------------------------------------------------------------
AMPLITUDE_MULTIPLIER = 50.0
SMOOTHING_FACTOR = 5.0
FFT_SIZE = 512
FFT_BINS = 256
FFT_COMPENSATION = 1.0

# ------------------------------------------------------------
# IMAGE SEQUENCE
# 배경1~배경4를 각각 75초씩 재생 -> 총 300초(5분)
# ------------------------------------------------------------
IMAGE_CHANGE_INTERVAL = 75.0
USE_FORCED_TIME_SEQUENCE = True
STOP_AFTER_LAST_IMAGE = True
FINAL_IMAGE_HOLD_TIME = 0.0
MAX_RENDER_SECONDS = 300.0

# ------------------------------------------------------------
# OBJECT OVERLAY
# 각 scene 폴더의 오브제를 dream_scenes.json 순서에 맞춰 표시합니다.
# 오브제가 없는 시간은 만들지 않습니다.
#
# scene_01: 3개 -> 각 25초
# scene_02: 3개 -> 각 25초
# scene_03: 4개 -> 각 18.75초
# scene_04: 3개 -> 각 25초
# (실제 시간은 JSON의 오브제 개수에 따라 자동 계산)
# ------------------------------------------------------------
USE_OBJECT_OVERLAY = True
OBJECT_FILL_SCENE = True

# 오브제는 표시되는 동안 고정된 랜덤 좌표를 사용합니다.
OBJECT_RANDOM_POSITION = True
OBJECT_RANDOM_SEED = 20261007

# 화면 가장자리에서 약간 안쪽에 배치
OBJECT_MARGIN_RATIO = 0.04

# 512x512 투명 PNG를 1920x1080 위에 적당히 확대
OBJECT_MIN_SCALE = 1.00
OBJECT_MAX_SCALE = 1.35
OBJECT_MAX_WIDTH_RATIO = 0.40
OBJECT_MAX_HEIGHT_RATIO = 0.65

# ------------------------------------------------------------
# COMPLETION (디버그 / 내부 진행도 용도)
# ------------------------------------------------------------
MIN_SPREAD_PROGRESS_FOR_NEXT_IMAGE = 0.995
MIN_VISUAL_COMPLETION_FOR_NEXT_IMAGE = 0.98
COMPLETED_IMAGE_HOLD_TIME = 2.0
COMPLETION_SAMPLE_STRIDE = 8

# Reveal 사용 안 함
USE_REVEAL_BLEND = False
REVEAL_START_PROGRESS = 0.72
MAX_ORIGINAL_BLEND = 0.0
REVEAL_SPEED = 1.5
FORCE_FULL_REVEAL_BEFORE_TRANSITION = False
FULL_REVEAL_START_PROGRESS = 0.94

# ------------------------------------------------------------
# PRIMARY / SECONDARY SEEDS
# ------------------------------------------------------------
USE_CLUSTERED_SEEDS = True
SEED_CLUSTER_COUNT = 5
SEED_CLUSTER_RADIUS = 10
CLUSTER_EDGE_ROUGHNESS = 0.30

USE_SECONDARY_CLUSTERS = True
SECONDARY_CLUSTER_COUNT = 35
SECONDARY_CLUSTER_RADIUS = 2
SECONDARY_CLUSTER_SIZE_VARIATION = 0.45

EXTRA_RANDOM_SEED_COUNT = 0

# ------------------------------------------------------------
# ORGANIC + NOISE CA
# ------------------------------------------------------------
BASE_SPREAD_RADIUS = 1
MAX_SPREAD_RADIUS = 4

AUDIO_RADIUS_BOOST = 1.2
STORY_RADIUS_BOOST = 1.0

BASE_SPREAD_CHANCE = 0.07
AUDIO_SPREAD_BONUS = 0.14

BASE_GROWTH_ATTEMPTS = 3
AUDIO_GROWTH_ATTEMPT_BONUS = 2
STORY_GROWTH_ATTEMPT_BONUS = 2

ORGANIC_INFLUENCE_POWER = 1.10

NOISE_DRIVEN_WEIGHT = 0.50
AUDIO_NOISE_WEIGHT_BONUS = 0.10
STORY_NOISE_WEIGHT_BONUS = 0.20

SPREAD_NOISE_SCALE = 0.025
SPREAD_NOISE_SPEED = 0.25
SPREAD_NOISE_THRESHOLD = 0.23

# ------------------------------------------------------------
# ADAPTIVE CATCH-UP
# ------------------------------------------------------------
USE_ADAPTIVE_CATCH_UP = True
CATCH_UP_START_TIME = 8.0
CATCH_UP_MAX_MULTIPLIER = 3.0
CATCH_UP_MAX_ADDITIONAL_ATTEMPTS = 4

# ------------------------------------------------------------
# COLOR
# ------------------------------------------------------------
BASE_COLOR_LERP_SPEED = 0.65
AUDIO_COLOR_LERP_BONUS = 2.2

NEIGHBOR_BLEND_CHANCE = 0.06
NEIGHBOR_BLEND_AMOUNT = 0.15

# ------------------------------------------------------------
# STORY
# dream_scenes.json의 scene별 story를 사용합니다.
# 각 scene의 모든 문장을 75초 안에 자동 배분합니다.
# ------------------------------------------------------------
USE_STORY_CONTROL = True
STORY_FIT_TO_SCENE = True
STORY_TRANSITION_DURATION = 1.5

USE_STORY_DISTORTION = True
NOISE_PIXEL_OFFSET = 4.0

# ------------------------------------------------------------
# AMBIENT DREAM DRIFT
# 이미지가 거의 다 나온 뒤에도 미세하게 살아있게 하는 규칙
# ------------------------------------------------------------
USE_AMBIENT_DRIFT = True

# 이 진행도 이후부터 ambient drift 가동
AMBIENT_DRIFT_START_PROGRESS = 0.92

# frame 단위(30fps 기준) 기본 확률
AMBIENT_DRIFT_BASE_CHANCE = 0.040

# 스토리 noise / spread에 따라 약간 증가
AMBIENT_DRIFT_STORY_NOISE_BONUS = 0.030
AMBIENT_DRIFT_STORY_SPREAD_BONUS = 0.024

# 오디오가 강하면 약간 증가
AMBIENT_DRIFT_AUDIO_BONUS = 0.018

# 주변 셀에 얼마나 끌릴지
AMBIENT_DRIFT_NEIGHBOR_BLEND = 0.22

# target 색으로 얼마나 빨리 다시 복귀할지
# 클수록 원형 유지가 강함
AMBIENT_RETURN_TO_TARGET = 0.045

# 경계선 쪽에서 조금 더 많이 움직이게
AMBIENT_EDGE_BONUS = 2.0

# 완전히 random 보다는 noise map이 높은 부분 위주로 조금 더 발생
AMBIENT_NOISE_GATE_WEIGHT = 0.45

# ------------------------------------------------------------
# OUTPUT UPSCALE
# 600x360 -> 1200x720 정수배 확대 시 nearest 사용
# ------------------------------------------------------------
USE_NEAREST_UPSCALE = True

# ------------------------------------------------------------
# DEBUG / RANDOM
# ------------------------------------------------------------
RANDOM_SEED = 20261003
PRINT_AUDIO_EVERY_SEC = 1.0
PRINT_DEBUG_EVERY_SEC = 1.0

# ------------------------------------------------------------
# OUTPUT
# ------------------------------------------------------------
OUTPUT_SILENT_NAME = "gridmodel_v2_silent.mp4"
OUTPUT_FINAL_NAME = "gridmodel_v2_final.mp4"
OUTPUT_LOG_NAME = "gridmodel_v2_log.txt"
