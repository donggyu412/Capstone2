import json
import os
import time
import urllib.request
import urllib.parse
from io import BytesIO
from PIL import Image
from rembg import remove

OBJ_ENGLISH_MAP = {
    "낡은 항해일지": "old weathered navigation logbook",
    "푸른빛 냉동액 웅덩이": "puddle of glowing blue cryogenic fluid",
    "팔이 긴 부유하는 그림자": "floating surreal shadow figure with elongated arms",
    "떨어지는 물방울": "falling water droplet",
    "낡은 서류철과 종이": "old document folder and papers",
    "팔이 길게 늘어진 그림자 형상": "shadow entity with excessively long arms",
    "서류철": "document folder",
    "무게가 변하는 종이": "surreal floating paper with changing weight",
    "팔이 늘어진 형상": "creature silhouette with drooping arms",
    "벌어지는 타일 금": "cracking and widening floor tile fissures",
    "밤색 서류철": "dark brown leather document folder",
    "금이 간 타일 바닥": "cracked tiled floor surface",
    "창백하고 얇은 손": "pale thin ghostly hand emerging"
}

STYLE_PROMPT = "digital art style, abstract geometric shape, surreal, white background, standalone object"

def get_workflow(prompt_text, negative_text, seed):
    return {
        "3": {
            "inputs": {
                "seed": seed,
                "steps": 20,
                "cfg": 8.0,
                "sampler_name": "euler",
                "scheduler": "simple",
                "denoise": 1.0,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0]
            },
            "class_type": "KSampler"
        },
        "4": {
            "inputs": {
                "ckpt_name": "dreamshaper_8.safetensors"
            },
            "class_type": "CheckpointLoaderSimple"
        },
        "5": {
            "inputs": {
                "width": 512,
                "height": 512,
                "batch_size": 1
            },
            "class_type": "EmptyLatentImage"
        },
        "6": {
            "inputs": {
                "text": prompt_text,
                "clip": ["4", 1]
            },
            "class_type": "CLIPTextEncode"
        },
        "7": {
            "inputs": {
                "text": negative_text,
                "clip": ["4", 1]
            },
            "class_type": "CLIPTextEncode"
        },
        "8": {
            "inputs": {
                "samples": ["3", 0],
                "vae": ["4", 2]
            },
            "class_type": "VAEDecode"
        },
        "9": {
            "inputs": {
                "filename_prefix": "ComfyUI_Dream",
                "images": ["8", 0]
            },
            "class_type": "SaveImage"
        }
    }

def queue_prompt(workflow):
    data = json.dumps({"prompt": workflow}).encode('utf-8')
    req = urllib.request.Request("http://127.0.0.1:8188/prompt", data=data)
    return json.loads(urllib.request.urlopen(req).read())

def get_image(filename, subfolder, folder_type):
    data = {"filename": filename, "subfolder": subfolder, "type": folder_type}
    url_values = urllib.parse.urlencode(data)
    with urllib.request.urlopen(f"http://127.0.0.1:8188/view?{url_values}") as response:
        return response.read()

def main():
    json_path = "dream_scenes.json"
    output_dir = "output_objects"
    if not os.path.exists(json_path):
        print(f"오류: {json_path} 파일을 찾을 수 없습니다.")
        return

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    os.makedirs(output_dir, exist_ok=True)

    for scene_data in data.get("scenes", []):
        scene_num = scene_data.get("scene")
        objects = scene_data.get("objects", [])
        scene_folder = os.path.join(output_dir, f"scene_{scene_num}")
        os.makedirs(scene_folder, exist_ok=True)

        print(f"\n=== Scene {scene_num} 오브제 생성 시작 (총 {len(objects)}개) ===")

        for idx, obj_name in enumerate(objects, 1):
            safe_name = obj_name.replace(" ", "_")
            save_path = os.path.join(scene_folder, f"obj_{idx}_{safe_name}.png")

            if os.path.exists(save_path):
                print(f"[{idx}/{len(objects)}] 패스: {obj_name} (이미 존재함)")
                continue

            eng_obj = OBJ_ENGLISH_MAP.get(obj_name, "surreal object")
            prompt_text = f"{eng_obj}, {STYLE_PROMPT}"
            negative_text = "bad anatomy, blurry, low quality, distorted, deformed, text, watermark, bright daylight, harsh flashing lights"
            seed = idx * 777 + scene_num * 100

            workflow = get_workflow(prompt_text, negative_text, seed)
            print(f"[{idx}/{len(objects)}] ComfyUI 요청 전송 및 대기 중: {obj_name}")

            try:
                # 1. 작업 큐에 등록
                resp = queue_prompt(workflow)
                prompt_id = resp['prompt_id']

                # 2. 완료될 때까지 상태 확인 (폴링 방식)
                while True:
                    time.sleep(1)
                    try:
                        history_req = urllib.request.urlopen(f"http://127.0.0.1:8188/history/{prompt_id}")
                        history = json.loads(history_req.read())
                        if prompt_id in history:
                            break
                    except Exception:
                        continue

                # 3. 결과 이미지 가져오기
                node_output = history[prompt_id]['outputs']['9']
                image_info = node_output['images'][0]
                img_bytes = get_image(image_info['filename'], image_info['subfolder'], image_info['type'])
                
                # 4. 누끼(배경 제거) 처리 후 저장
                orig_image = Image.open(BytesIO(img_bytes))
                nobg_image = remove(orig_image)
                nobg_image.save(save_path, "PNG")

                print(f" -> 성공: {save_path} 저장 완료")

            except Exception as e:
                print(f" -> 오류 발생: {e}")

if __name__ == "__main__":
    main()
