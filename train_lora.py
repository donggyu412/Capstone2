import os
import subprocess
import sys

# 1. 경로 설정
BASE_DIR = r"C:\Users\nodaf\Desktop\asd"
COMFY_DIR = r"C:\ComfyUI_windows_portable"

# 베이스 모델 및 데이터셋 경로
MODEL_PATH = os.path.join(COMFY_DIR, r"ComfyUI\models\checkpoints\dreamshaper_8.safetensors")
DATASET_DIR = os.path.join(BASE_DIR, "dataset")
OUTPUT_DIR = os.path.join(BASE_DIR, "output_lora")
SD_SCRIPTS_DIR = os.path.join(BASE_DIR, "sd-scripts")

os.makedirs(OUTPUT_DIR, exist_ok=True)

# 2. sd-scripts 깃 리포지토리 클론 (없는 경우)
if not os.path.exists(SD_SCRIPTS_DIR):
    print("=== LoRA 학습 라이브러리(sd-scripts) 다운로드 중... ===")
    subprocess.run(["git", "clone", "https://github.com/kohya-ss/sd-scripts.git", SD_SCRIPTS_DIR], check=True)

# 3. 필수 패키지 설치
print("=== 필요한 의존성 패키지 확인 및 설치 중... ===")
subprocess.run([sys.executable, "-m", "pip", "install", "accelerate", "transformers", "diffusers", "ftfy", "einops", "bitsandbytes"], check=False)

# 4. LoRA 학습 실행 명령어 구축
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
    "--max_train_epochs=10",
    "--save_every_n_epochs=5",
    "--mixed_precision=fp16",
    "--save_precision=fp16",
    "--cache_latents",
    "--optimizer_type=AdamW8bit"
]

print("\n=== LoRA 학습 시작 ===")
print(f"베이스 모델: {MODEL_PATH}")
print(f"데이터셋 경로: {DATASET_DIR}")
print(f"결과 저장 위치: {OUTPUT_DIR}\n")

try:
    subprocess.run(train_cmd, check=True)
    print("\n🎉 LoRA 학습 성공적으로 완료!")
    print(f"생성된 로라 모델 위치: {os.path.join(OUTPUT_DIR, 'dream_object_lora.safetensors')}")
except Exception as e:
    print(f"\n학습 중 오류 발생: {e}")
