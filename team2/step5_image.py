# -*- coding: utf-8 -*-
"""prompts_per_point.json → ComfyUI API로 이미지 생성 → scene_N_image.png"""
import json
import shutil
import sys
import time
import uuid
from pathlib import Path

import requests

COMFY_URL = "http://127.0.0.1:8188"


def generate_image(prompt_text, scene_num, workflow_path, prompt_node_id,
                   output_dir="output", comfy_output_dir=None):
    with open(workflow_path, encoding="utf-8") as f:
        workflow = json.load(f)

    workflow[prompt_node_id]["inputs"]["text"] = prompt_text
    client_id = str(uuid.uuid4())

    resp = requests.post(
        f"{COMFY_URL}/prompt",
        json={"prompt": workflow, "client_id": client_id},
        timeout=30,
    )
    resp.raise_for_status()
    prompt_id = resp.json()["prompt_id"]
    print(f"    ComfyUI 작업 시작: prompt_id={prompt_id}")

    # 완료 대기 (폴링)
    for _ in range(300):  # 최대 5분 대기
        hist = requests.get(f"{COMFY_URL}/history/{prompt_id}", timeout=10).json()
        if prompt_id in hist:
            break
        time.sleep(1)
    else:
        raise TimeoutError(f"장면#{scene_num} 이미지 생성 타임아웃 (5분 초과)")

    # 생성된 이미지 파일 경로 추출
    outputs = hist[prompt_id].get("outputs", {})
    image_filename = None
    for node_output in outputs.values():
        images = node_output.get("images", [])
        if images:
            image_filename = images[0]["filename"]
            subfolder = images[0].get("subfolder", "")
            break

    if not image_filename:
        raise RuntimeError(f"장면#{scene_num}: 출력 이미지 파일명을 찾을 수 없음")

    # ComfyUI output 폴더에서 파일 찾기
    if comfy_output_dir:
        comfy_out = Path(comfy_output_dir)
    else:
        # ComfyUI 기본 output 폴더 자동 탐색
        comfy_out = _find_comfy_output()

    src = comfy_out / subfolder / image_filename if subfolder else comfy_out / image_filename
    if not src.exists():
        raise FileNotFoundError(f"ComfyUI 출력 파일을 찾을 수 없음: {src}")

    dest = Path(output_dir) / f"scene_{scene_num}_image.png"
    shutil.copy2(src, dest)
    print(f"    이미지 저장 완료: {dest}")
    return dest


def _find_comfy_output():
    """ComfyUI output 폴더 자동 탐색 (일반적인 설치 경로 순서대로)"""
    candidates = [
        Path("C:/ComfyUI/output"),
        Path("C:/ComfyUI_windows_portable/ComfyUI/output"),
        Path.home() / "ComfyUI/output",
        Path.home() / "Desktop/ComfyUI/output",
        Path.home() / "Desktop/ComfyUI_windows_portable/ComfyUI/output",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        "ComfyUI output 폴더를 찾을 수 없습니다.\n"
        "step5_image.py 실행 시 --comfy-output 옵션으로 직접 지정하세요.\n"
        "예: python step5_image.py --comfy-output C:/ComfyUI/output"
    )


def main(
    prompts_path: str = "output/prompts_per_point.json",
    workflow_path: str = "image_workflow_api.json",
    prompt_node_id: str = "6",
    output_dir: str = "output",
    comfy_output_dir: str = None,
):
    if not Path(workflow_path).exists():
        print(f"오류: 워크플로우 파일 없음 → {workflow_path}")
        print("ComfyUI UI에서 워크플로우를 'Save (API Format)'으로 저장한 뒤")
        print(f"'{workflow_path}' 경로에 놓으세요.")
        sys.exit(1)

    # ComfyUI 연결 확인
    try:
        requests.get(f"{COMFY_URL}/system_stats", timeout=5)
    except Exception:
        print(f"오류: ComfyUI에 연결할 수 없습니다 ({COMFY_URL})")
        print("ComfyUI를 API 모드로 실행하세요: python main.py --listen")
        sys.exit(1)

    prompts = json.loads(Path(prompts_path).read_text(encoding="utf-8"))
    Path(output_dir).mkdir(exist_ok=True)

    for i, p in enumerate(prompts, 1):
        scene_num = p["장면번호"]
        prompt_text = p["이미지_프롬프트_영문"]
        print(f"[{i}/{len(prompts)}] 장면#{scene_num} 이미지 생성 중...")
        print(f"    프롬프트: {prompt_text[:80]}...")
        generate_image(
            prompt_text, scene_num, workflow_path, prompt_node_id,
            output_dir, comfy_output_dir,
        )

    print(f"\n이미지 생성 완료: {len(prompts)}개 → {output_dir}/")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompts",       default="output/prompts_per_point.json")
    parser.add_argument("--workflow",      default="image_workflow_api.json")
    parser.add_argument("--node-id",       default="6", dest="node_id")
    parser.add_argument("--output-dir",    default="output")
    parser.add_argument("--comfy-output",  default=None, dest="comfy_output")
    args = parser.parse_args()
    main(args.prompts, args.workflow, args.node_id, args.output_dir, args.comfy_output)
