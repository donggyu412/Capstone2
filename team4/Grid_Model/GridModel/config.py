# config.py — GridModel v2 scene/storyboard input
# ============================================================
# GridModel object-only cellular automata settings.
# ============================================================

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# ============================================================
# INPUT STRUCTURE
# Team4/input/object/object_line_1.mp4 is the object-only source.
# ============================================================
INPUT_DIR = ROOT / "input"
OBJECT_INPUT_DIR = INPUT_DIR / "object"
OBJECT_VIDEO = OBJECT_INPUT_DIR / "object_line_1.mp4"

# 결과물
OUT_DIR = ROOT / "output"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ------------------------------------------------------------
# GRID / OUTPUT
# CA runs on a reduced grid, then nearest-neighbor upscales to the source size.
# ------------------------------------------------------------
CA_WIDTH = 480
CA_HEIGHT = 270

OUTPUT_WIDTH = 1920
OUTPUT_HEIGHT = 1080

OUTPUT_FPS = 30

OBJECT_MASK_THRESHOLD = 10
OBJECT_ALIVE_THRESHOLD = 0.18
CA_INITIAL_SEEDS = 12
CA_BIRTH_MIN_NEIGHBORS = 2
CA_DEATH_MAX_NEIGHBORS = 0
CA_CELL_FLICKER = 0.025
CA_DEATH_RETAIN = 0.12
CA_BIRTH_MIN_STATE = 0.45
CA_MIN_VISIBLE_STATE = 0.35
CA_STATE_JITTER = 0.12
CA_BASE_BRIGHTNESS = 0.84
CA_STATE_BRIGHTNESS = 0.42
CA_COLOR_JITTER = 0.09
RANDOM_SEED = 20261019

# Object-only output; black pixels stay transparent-ready for compositing.
OUTPUT_OBJECT_NAME = "gridmodel_object_ca.mp4"
