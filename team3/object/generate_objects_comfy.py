"""
꿈 오브제 생성 — 스토리보드 json → ComfyUI(dreamshaper_8 + dream_object LoRA) → 장면별 투명 PNG
캡스톤 디자인2 · 3팀 · 시스템 II (꿈 오브제)

스토리보드 내용이 바뀌어도 그대로 돌아가도록:
  오브제 이름(한국어) → 영어 프롬프트를 자동 번역한다.
    1) translations.json  — 사람이 고친 번역이 있으면 그것을 최우선으로 쓴다
    2) 기본 사전          — 지난 스토리보드의 13개 (검수된 번역)
    3) 자동 번역          — 그 밖의 새 오브제는 구글 번역으로, 구글이 막히면 MyMemory 로 옮기고 translations.json 에 적어 둔다
    4) 번역 실패 시에만    — "surreal object" (경고 출력)

사용법
  번역만 먼저 확인 (ComfyUI 없이)   python generate_objects_comfy.py --dry-run
  생성                              python generate_objects_comfy.py
  다른 스토리보드                    python generate_objects_comfy.py --story new_scenes.json

결과
  output_objects/scene_01/obj_1_이름.png   투명 PNG (배경 엔진·4팀 입력)
  output_objects_raw/scene_01/...          흰 배경 원본 (누끼를 손으로 다시 딸 때)
  output_objects/objects.json              장면·오브제·번역·프롬프트·시드 대응표
  translations.json                        번역 기록 — 이상한 번역은 여기서 고치고 다시 돌리면 된다

필요 패키지: pip install pillow "rembg[cpu]" deep-translator scipy
누끼 모델은 --rembg-model 로 고른다 (기본 birefnet-general, 처음 실행 때 1GB 안팎 내려받음).
최종 제출물은 output_objects_raw 의 원본으로 여러 모델을 돌려 손으로 고르는 것이 가장 낫다 (compare.py).
ComfyUI 는 미리 켜 두고(run_nvidia_gpu.bat), models/loras 에 dream_object_lora.safetensors 가 있어야 한다.
"""
import argparse
import json
import os
import time
import urllib.parse
import urllib.request
from io import BytesIO

import numpy as np
from PIL import Image

# 지난 스토리보드에서 검수한 번역 — 자동 번역보다 우선한다
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
    "창백하고 얇은 손": "pale thin ghostly hand emerging",
}

TRIGGER = "dream_object"  # LoRA 학습 때 캡션 맨 앞에 붙인 트리거 워드
STYLE_PROMPT = "digital art style, abstract geometric shape, surreal, white background, standalone object"
NEGATIVE = "worst quality, low quality, blurry, distorted"  # ComfyUI 화면에서 쓴 것과 같게
FALLBACK = "surreal object"
TRANSLATIONS = "translations.json"


# ─────────────────────────────────────────────
# 번역
# ─────────────────────────────────────────────
def load_translations():
    if os.path.exists(TRANSLATIONS):
        with open(TRANSLATIONS, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_translations(tr):
    with open(TRANSLATIONS, "w", encoding="utf-8") as f:
        json.dump(tr, f, ensure_ascii=False, indent=2)


def clean_en(text):
    text = (text or "").strip().strip(".").strip()
    for art in ("The ", "the ", "A ", "a ", "An ", "an "):
        if text.startswith(art):
            text = text[len(art):]
    return text.lower()


_providers = None


def _make_providers():
    """구글 → MyMemory 순서. 구글이 네트워크(IP) 단위로 막히는 일이 있어 다른 번역기로 넘어간다"""
    try:
        from deep_translator import GoogleTranslator, MyMemoryTranslator
    except ImportError:
        print("  ! deep-translator 가 없습니다 → pip install deep-translator")
        return []
    return [("google", lambda: GoogleTranslator(source="ko", target="en")),
            ("mymemory", lambda: MyMemoryTranslator(source="korean", target="english us"))]


def auto_translate(ko):
    """(영어, 번역기 이름) — 모두 실패하면 (None, None)"""
    global _providers
    if _providers is None:
        _providers = _make_providers()
    for name, make in list(_providers):
        for attempt in range(2):
            try:
                en = clean_en(make().translate(ko))
                if en and en != ko.lower():
                    return en, name
                break
            except Exception as e:
                msg = type(e).__name__
                print(f"  ! {name} 번역 실패({msg}) — {'다시 시도' if attempt == 0 else '다음 번역기로'}")
                time.sleep(1.5)
        else:  # 두 번 다 막힌 번역기는 이번 실행에서 다시 부르지 않는다
            _providers = [p for p in _providers if p[0] != name]
    return None, None


def translate(ko, tr):
    """(영어, 출처) — 출처: manual / dict / auto / fallback"""
    entry = tr.get(ko)
    if entry and entry.get("en"):
        return entry["en"], entry.get("source", "manual")
    if ko in OBJ_ENGLISH_MAP:
        return OBJ_ENGLISH_MAP[ko], "dict"
    en, provider = auto_translate(ko)
    if en:
        tr[ko] = {"en": en, "source": "auto", "provider": provider}
        save_translations(tr)
        return en, "auto"
    print(f"  ! '{ko}' 번역 실패 → '{FALLBACK}' 로 생성합니다 (translations.json 에 직접 적어 주세요)")
    return FALLBACK, "fallback"


# ─────────────────────────────────────────────
# ComfyUI
# ─────────────────────────────────────────────
def get_workflow(prompt_text, negative_text, seed, lora_name, lora_strength):
    model_src, clip_src = ["4", 0], ["4", 1]
    wf = {
        "3": {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": 20, "cfg": 8.0, "sampler_name": "euler", "scheduler": "simple",
            "denoise": 1.0, "model": model_src, "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "dreamshaper_8.safetensors"}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt_text, "clip": clip_src}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative_text, "clip": clip_src}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "ComfyUI_Dream", "images": ["8", 0]}},
    }
    if lora_name:  # LoRA 를 체크포인트와 샘플러·텍스트 인코더 사이에 끼운다 (화면 워크플로와 같은 연결)
        wf["10"] = {"class_type": "LoraLoader", "inputs": {
            "lora_name": lora_name, "strength_model": lora_strength, "strength_clip": lora_strength,
            "model": ["4", 0], "clip": ["4", 1]}}
        wf["3"]["inputs"]["model"] = ["10", 0]
        wf["6"]["inputs"]["clip"] = ["10", 1]
        wf["7"]["inputs"]["clip"] = ["10", 1]
    return wf


def queue_prompt(server, workflow):
    data = json.dumps({"prompt": workflow}).encode("utf-8")
    req = urllib.request.Request(f"{server}/prompt", data=data)
    return json.loads(urllib.request.urlopen(req).read())


def wait_result(server, prompt_id, timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(1)
        try:
            history = json.loads(urllib.request.urlopen(f"{server}/history/{prompt_id}").read())
            if prompt_id in history:
                return history[prompt_id]
        except Exception:
            continue
    raise TimeoutError("ComfyUI 응답 시간 초과")


def get_image(server, filename, subfolder, folder_type):
    q = urllib.parse.urlencode({"filename": filename, "subfolder": subfolder, "type": folder_type})
    with urllib.request.urlopen(f"{server}/view?{q}") as r:
        return r.read()


# ─────────────────────────────────────────────
# 누끼 — rembg 한 모델로 따고, 물체 '안쪽'에 뚫린 구멍 중 배경색이 아닌 것만 메운다
#   (밤색 서류철 가운데 검은 마름모처럼 물체의 일부가 구멍으로 잘리는 것을 막고,
#    그림자 형상의 팔 사이처럼 진짜 배경이 보이는 틈은 그대로 둔다)
#   모델 비교: u2net · isnet-general-use · birefnet-general · bria-rmbg — 손으로 고를 때는 compare.py
# ─────────────────────────────────────────────
_session = None


def remove_bg(img, model="birefnet-general", hole_min_diff=30.0):
    global _session
    from rembg import new_session, remove
    from scipy.ndimage import binary_fill_holes, label
    if _session is None or _session[0] != model:
        _session = (model, new_session(model))
    src = img.convert("RGB")
    a = np.array(remove(src, session=_session[1], only_mask=True).convert("L"))
    rgb = np.asarray(src).astype(np.float32)
    border = np.concatenate([rgb[:4].reshape(-1, 3), rgb[-4:].reshape(-1, 3), rgb[:, :4].reshape(-1, 3), rgb[:, -4:].reshape(-1, 3)])
    bg = np.median(border, 0)  # 배경색 — 테두리의 대표색
    solid = a > 64
    holes = binary_fill_holes(solid) & ~solid
    lab, n = label(holes)
    for k in range(1, n + 1):
        m = lab == k
        if np.linalg.norm(rgb[m].mean(0) - bg) > hole_min_diff:  # 배경색과 다르면 물체의 일부 → 메운다
            a[m] = 255
    out = src.convert("RGBA")
    out.putalpha(Image.fromarray(a))
    return out


# ─────────────────────────────────────────────
def main():
    global TRANSLATIONS
    ap = argparse.ArgumentParser(description="꿈 오브제 생성 (ComfyUI + LoRA)")
    ap.add_argument("--story", default="dream_scenes.json")
    ap.add_argument("--out", default="output_objects")
    ap.add_argument("--server", default="http://127.0.0.1:8188")
    ap.add_argument("--lora", default="dream_object_lora.safetensors", help="빈 문자열이면 LoRA 없이")
    ap.add_argument("--lora-strength", type=float, default=0.6)
    ap.add_argument("--rembg-model", default="birefnet-general",
                    help="누끼 모델: birefnet-general(기본) · bria-rmbg · isnet-general-use · u2net")
    ap.add_argument("--translations", default=TRANSLATIONS, help="번역 기록 파일 (시험할 때는 다른 이름으로)")
    ap.add_argument("--dry-run", action="store_true", help="번역·프롬프트만 확인하고 생성하지 않음")
    args = ap.parse_args()

    if not os.path.exists(args.story):
        print(f"오류: {args.story} 파일을 찾을 수 없습니다.")
        return
    with open(args.story, "r", encoding="utf-8") as f:
        data = json.load(f)
    scenes = data.get("scenes", data) if isinstance(data, dict) else data

    TRANSLATIONS = args.translations
    tr = load_translations()
    raw_dir = args.out + "_raw"
    manifest = {"story": os.path.basename(args.story), "checkpoint": "dreamshaper_8.safetensors",
                "lora": args.lora or None, "lora_strength": args.lora_strength if args.lora else None,
                "style_prompt": STYLE_PROMPT, "negative": NEGATIVE,
                "background_removal": f"rembg {args.rembg_model} + 배경색이 아닌 안쪽 구멍만 메움", "scenes": []}

    for scene_data in scenes:
        n = int(scene_data.get("scene"))
        objects = scene_data.get("objects", [])
        folder = os.path.join(args.out, f"scene_{n:02d}")
        raw_folder = os.path.join(raw_dir, f"scene_{n:02d}")
        print(f"\n=== 장면 {n} · 오브제 {len(objects)}개 ===")
        entries = []
        for idx, ko in enumerate(objects, 1):
            en, source = translate(ko, tr)
            prompt = f"{TRIGGER}, {en}, {STYLE_PROMPT}"
            seed = idx * 777 + n * 100
            fname = f"obj_{idx}_{ko.replace(' ', '_')}.png"
            entries.append({"index": idx, "name_ko": ko, "name_en": en, "translation": source,
                            "prompt": prompt, "seed": seed, "file": f"scene_{n:02d}/{fname}"})
            tag = {"manual": "직접", "dict": "사전", "auto": "자동", "fallback": "실패"}.get(source, source)
            print(f"  [{idx}] {ko}  →  {en}   ({tag})")
            if args.dry_run:
                continue

            save_path = os.path.join(folder, fname)
            if os.path.exists(save_path):
                print("      패스 (이미 있음)")
                continue
            os.makedirs(folder, exist_ok=True)
            os.makedirs(raw_folder, exist_ok=True)
            try:
                wf = get_workflow(prompt, NEGATIVE, seed, args.lora, args.lora_strength)
                pid = queue_prompt(args.server, wf)["prompt_id"]
                hist = wait_result(args.server, pid)
                info = hist["outputs"]["9"]["images"][0]
                img = Image.open(BytesIO(get_image(args.server, info["filename"], info["subfolder"], info["type"])))
                img.save(os.path.join(raw_folder, fname))
                remove_bg(img, args.rembg_model).save(save_path, "PNG")
                print(f"      저장 → {save_path}")
            except urllib.error.URLError:
                print("      ! ComfyUI 에 연결할 수 없습니다 — run_nvidia_gpu.bat 으로 먼저 켜 주세요")
                return
            except Exception as e:
                print(f"      ! 오류: {e}")
        manifest["scenes"].append({"scene": n, "objects": entries})

    if not args.dry_run:
        os.makedirs(args.out, exist_ok=True)
        with open(os.path.join(args.out, "objects.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        print(f"\n대응표 → {os.path.join(args.out, 'objects.json')}")
    auto = [k for k, v in tr.items() if v.get("source") == "auto"]
    if auto:
        print(f"\n자동 번역 {len(auto)}개가 {TRANSLATIONS} 에 있습니다. 어색한 번역은 그 파일에서 'en' 을 고치고 "
              f"'source' 를 'manual' 로 바꾼 뒤, 해당 PNG 를 지우고 다시 돌리면 됩니다.")


if __name__ == "__main__":
    main()
