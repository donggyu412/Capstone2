"""
dream_object LoRA 학습 (kohya-ss sd-scripts)

경로는 모두 이 스크립트가 있는 폴더 기준이고, 인자로 바꿀 수 있다 — 어느 PC 에서든 그대로 돌아간다.

  python train_lora.py --model D:\\ComfyUI_windows_portable\\ComfyUI\\models\\checkpoints\\dreamshaper_8.safetensors
  python train_lora.py --comfy-dir D:\\ComfyUI_windows_portable          (체크포인트를 ComfyUI 폴더에서 찾기)
  set COMFY_DIR=D:\\ComfyUI_windows_portable  후  python train_lora.py    (환경변수로 한 번만 지정)

기본값
  --base-dir   이 스크립트가 있는 폴더 (dataset/, output_lora/, sd-scripts/ 를 여기서 찾는다)
  --comfy-dir  환경변수 COMFY_DIR → 없으면 base-dir 옆의 ComfyUI_windows_portable
  --model      <comfy-dir>/ComfyUI/models/checkpoints/dreamshaper_8.safetensors
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

ap = argparse.ArgumentParser(description="dream_object LoRA 학습")
ap.add_argument("--base-dir", default=HERE, help="dataset/ · output_lora/ · sd-scripts/ 가 있는 폴더")
ap.add_argument("--comfy-dir", default=os.environ.get("COMFY_DIR", os.path.join(os.path.dirname(HERE), "ComfyUI_windows_portable")))
ap.add_argument("--model", default="", help="베이스 체크포인트 경로 (주면 --comfy-dir 보다 우선)")
ap.add_argument("--epochs", type=int, default=10)
ap.add_argument("--save-every", type=int, default=5)
ap.add_argument("--skip-install", action="store_true", help="의존성 설치 건너뛰기")
args = ap.parse_args()

BASE_DIR = os.path.abspath(args.base_dir)
MODEL_PATH = args.model or os.path.join(args.comfy_dir, "ComfyUI", "models", "checkpoints", "dreamshaper_8.safetensors")
DATASET_DIR = os.path.join(BASE_DIR, "dataset")
OUTPUT_DIR = os.path.join(BASE_DIR, "output_lora")
SD_SCRIPTS_DIR = os.path.join(BASE_DIR, "sd-scripts")

if not os.path.exists(MODEL_PATH):
    sys.exit(f"베이스 모델을 찾을 수 없습니다: {MODEL_PATH}\n"
             f"  → --model 로 dreamshaper_8.safetensors 경로를 주거나, --comfy-dir / 환경변수 COMFY_DIR 로 ComfyUI 폴더를 알려 주세요.")
if not os.path.isdir(DATASET_DIR):
    sys.exit(f"데이터셋 폴더가 없습니다: {DATASET_DIR}  → prepare_dataset.py 를 먼저 실행하세요.")

os.makedirs(OUTPUT_DIR, exist_ok=True)

# sd-scripts 깃 리포지토리 클론 (없는 경우)
if not os.path.exists(SD_SCRIPTS_DIR):
    print("=== LoRA 학습 라이브러리(sd-scripts) 다운로드 중... ===")
    subprocess.run(["git", "clone", "https://github.com/kohya-ss/sd-scripts.git", SD_SCRIPTS_DIR], check=True)

if not args.skip_install:
    print("=== 필요한 의존성 패키지 확인 및 설치 중... ===")
    subprocess.run([sys.executable, "-m", "pip", "install", "accelerate", "transformers", "diffusers", "ftfy", "einops", "bitsandbytes"], check=False)

train_cmd = [
    sys.executable, os.path.join(SD_SCRIPTS_DIR, "train_network.py"),
    "--network_module=networks.lora",
    f"--pretrained_model_name_or_path={MODEL_PATH}",
    f"--train_data_dir={DATASET_DIR}",
    f"--output_dir={OUTPUT_DIR}",
    "--output_name=dream_object_lora",
    "--dataset_repeats=10",
    "--learning_rate=0.0001",
    "--network_dim=32",
    "--network_alpha=16",
    "--resolution=512,512",
    "--train_batch_size=1",
    f"--max_train_epochs={args.epochs}",
    f"--save_every_n_epochs={args.save_every}",
    "--mixed_precision=fp16",
    "--save_precision=fp16",
    "--cache_latents",
    "--optimizer_type=AdamW8bit",
]

print("\n=== LoRA 학습 시작 ===")
print(f"베이스 모델: {MODEL_PATH}")
print(f"데이터셋 경로: {DATASET_DIR}")
print(f"결과 저장 위치: {OUTPUT_DIR}\n")

try:
    subprocess.run(train_cmd, check=True)
    print("\nLoRA 학습 완료")
    print(f"생성된 LoRA: {os.path.join(OUTPUT_DIR, 'dream_object_lora.safetensors')}")
except Exception as e:
    print(f"\n학습 중 오류 발생: {e}")
