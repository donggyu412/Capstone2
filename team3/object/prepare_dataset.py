"""
LoRA 학습용 데이터셋 준비 — 장면별 오브제 PNG 를 Kohya 폴더 구조(dataset/10_dream_object)로 복사하고 1:1 캡션을 만든다.

  python prepare_dataset.py                          (기본: output_objects → dataset/10_dream_object)
  python prepare_dataset.py --source 다른_폴더

캡션 짝짓기
  파일 이름 obj_<번호>_<오브제_이름>.png 에서 이름을 그대로 꺼내 사전과 '정확히' 맞춘다.
  정확히 맞는 것이 없을 때만 긴 이름부터 부분 일치를 본다 — '밤색 서류철' 이 '서류철' 로 잡히던 문제 수정.
  사전에 없는 이름은 translations.json(generate_objects_comfy.py 가 만든 번역 기록)에서 찾는다.

주의: 이미 LoRA 로 만든 결과(output_objects)를 다시 학습 데이터로 쓰면 LoRA 가 자기 결과를 다시 배우게 된다.
      재학습할 때는 --source 로 원하는 학습용 이미지 폴더를 명시하는 것을 권한다.
"""
import argparse
import json
import os
import re
import shutil

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

TRIGGER_WORD = "dream_object"  # 학습 시 이 화풍을 불러올 키워드
COMMON_STYLE = "digital art style, abstract geometric shape, surreal, white background, standalone object"
NAME_RE = re.compile(r"^obj_\d+_(.+)\.png$")


def load_extra(path="translations.json"):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return {k: v.get("en") for k, v in json.load(f).items() if v.get("en")}
    return {}


def caption_for(filename, table):
    m = NAME_RE.match(filename)
    if m:
        name = m.group(1).replace("_", " ")
        if name in table:  # 정확히 일치
            return table[name], name
    for key in sorted(table, key=len, reverse=True):  # 긴 이름부터 부분 일치
        if key.replace(" ", "_") in filename or key in filename:
            return table[key], key
    return "surreal object", None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="output_objects", help="장면별 오브제 PNG 폴더 (scene_NN/obj_i_이름.png)")
    ap.add_argument("--target", default=os.path.join("dataset", "10_dream_object"), help="Kohya 형식: {반복횟수}_{개념이름}")
    args = ap.parse_args()

    table = {**load_extra(), **OBJ_ENGLISH_MAP}
    os.makedirs(args.target, exist_ok=True)
    count = 0
    for root, dirs, files in sorted(os.walk(args.source)):
        dirs.sort()
        for file in sorted(files):
            if not NAME_RE.match(file):  # obj_*.png 만 — _review_sheet.png 같은 검수 이미지는 제외
                continue
            eng, key = caption_for(file, table)
            if key is None:
                print(f"  ! {file}: 캡션을 찾지 못해 'surreal object' 로 적습니다")
            count += 1
            base = f"obj_{count:02d}"
            shutil.copy2(os.path.join(root, file), os.path.join(args.target, f"{base}.png"))
            with open(os.path.join(args.target, f"{base}.txt"), "w", encoding="utf-8") as f:
                f.write(f"{TRIGGER_WORD}, {eng}, {COMMON_STYLE}")
            print(f"[{count}] {base}.png ← {os.path.basename(root)}/{file}  ({eng})")
    print(f"\n총 {count}개 준비 완료 → {os.path.abspath(args.target)}")


if __name__ == "__main__":
    main()
