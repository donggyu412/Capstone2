import os
import shutil

# 한글 -> 영문 캡션 매핑
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

# 학습 시 이 화풍을 불러올 키워드(Trigger Word)
TRIGGER_WORD = "dream_object" 
COMMON_STYLE = "digital art style, abstract geometric shape, surreal, white background, standalone object"

source_dir = "output_objects"
# Kohya_ss 표준 폴더 구조: {반복횟수}_{개념이름}
target_dir = os.path.join("dataset", "10_dream_object") 

os.makedirs(target_dir, exist_ok=True)

copied_count = 0

for root, dirs, files in os.walk(source_dir):
    for file in files:
        if file.endswith(".png"):
            src_path = os.path.join(root, file)
            
            # 한글 오브제명 찾기
            eng_desc = "surreal object"
            for kor_key, eng_val in OBJ_ENGLISH_MAP.items():
                if kor_key.replace(" ", "_") in file or kor_key in file:
                    eng_desc = eng_val
                    break
            
            # 학습용 파일명 지정 (img_01, img_02 ...)
            copied_count += 1
            new_basename = f"obj_{copied_count:02d}"
            dst_img_path = os.path.join(target_dir, f"{new_basename}.png")
            dst_txt_path = os.path.join(target_dir, f"{new_basename}.txt")

            # 1. 이미지 복사
            shutil.copy2(src_path, dst_img_path)

            # 2. 1:1 매칭 캡션(.txt) 파일 생성
            caption = f"{TRIGGER_WORD}, {eng_desc}, {COMMON_STYLE}"
            with open(dst_txt_path, "w", encoding="utf-8") as f:
                f.write(caption)

            print(f"[{copied_count}] 생성 완료: {new_basename}.png / .txt")

print(f"\n총 {copied_count}개의 데이터셋 준비 완료!")
print(f"저장 위치: {os.path.abspath(target_dir)}")
