"""
누끼 비교 — 같은 흰 배경 원본을 rembg 여러 모델로 따서 한 장에 나란히 놓고, 장마다 가장 나은 결과를 손으로 고른다.

자동 누끼(generate_objects_comfy.py)는 한 모델로만 따기 때문에, 흰 물체가 흰 배경에 지워지거나
물체 안쪽이 구멍으로 잘리는 장이 생길 수 있다. 최종 제출용은 이 도구로 비교해서 고르는 것을 권한다.

  1) 모델별로 누끼 따기 + 비교 이미지 만들기
       python compare.py --run
  2) 비교 이미지만 다시 만들기 (이미 딴 결과가 있을 때)
       python compare.py
  3) 고른 결과를 output_objects 로 옮기기 (장면-번호=모델)
       python compare.py --pick 2-3=bria-rmbg 3-1=birefnet-general

입력   output_objects_raw/scene_NN/obj_i_이름.png   (generate_objects_comfy.py 가 남기는 흰 배경 원본)
출력   cutouts/<모델>/scene_NN/obj_i_이름.png       모델별 누끼
       compare.png                                  왼쪽부터 원본 · 모델1 · 모델2 … (어두운 배경 위 — 흐릿한 잘림이 잘 보인다)

필요 패키지: pip install pillow "rembg[cpu]"
처음 실행 때 모델을 내려받는다 (birefnet-general · bria-rmbg 는 각 1GB 안팎).
"""
import argparse
import re
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

MODELS = ["u2net", "isnet-general-use", "birefnet-general", "bria-rmbg"]
NAME_RE = re.compile(r"scene_(\d+)[\\/]obj_(\d+)_")


def find_font(size):
    for p in ["C:/Windows/Fonts/malgun.ttf", "/System/Library/Fonts/AppleSDGothicNeo.ttc",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                pass
    return ImageFont.load_default()


def key_of(rel):
    m = NAME_RE.search(str(rel))
    return f"{int(m.group(1))}-{int(m.group(2))}" if m else rel.stem


def run_models(raw, files, models, out_root):
    from rembg import new_session, remove
    for model in models:
        print(f"\n=== {model} ===")
        session = None
        for rel in files:
            dst = out_root / model / rel
            if dst.exists():
                continue
            if session is None:
                session = new_session(model)
            dst.parent.mkdir(parents=True, exist_ok=True)
            remove(Image.open(raw / rel).convert("RGB"), session=session).save(dst)
            print(f"  {key_of(rel)}  {rel}")


def make_sheet(raw, files, models, out_root, path, cell=220):
    font, small = find_font(16), find_font(13)
    cols = ["원본"] + models
    sheet = Image.new("RGB", (cell * len(cols), 28 + (cell + 22) * len(files)), (20, 20, 28))
    d = ImageDraw.Draw(sheet)
    for c, name in enumerate(cols):
        d.text((c * cell + 6, 6), name, font=font, fill=(255, 120, 120))
    for r, rel in enumerate(files):
        y = 28 + r * (cell + 22)
        sheet.paste(Image.open(raw / rel).convert("RGB").resize((cell, cell)), (0, y))
        for c, model in enumerate(models, 1):
            p = out_root / model / rel
            if p.exists():
                im = Image.open(p).convert("RGBA")
                bg = Image.new("RGBA", im.size, (15, 15, 25, 255))
                bg.alpha_composite(im)
                sheet.paste(bg.convert("RGB").resize((cell, cell)), (c * cell, y))
        d.text((6, y + cell + 3), f"{key_of(rel)}  {rel.name}", font=small, fill=(230, 230, 230))
    sheet.save(path)
    print(f"\n비교 이미지 → {path}")


def pick(raw, files, out_root, choices, target):
    by_key = {key_of(rel): rel for rel in files}
    for choice in choices:
        k, _, model = choice.partition("=")
        rel = by_key.get(k)
        src = out_root / model / rel if rel else None
        if not src or not src.exists():
            print(f"  ! {choice}: 해당 결과가 없습니다 (--run 으로 먼저 따 주세요)")
            continue
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        print(f"  {k} ← {model}  ({dst})")
    print("objects.json 의 mask 기록도 고른 모델로 바꿔 두세요.")


def main():
    ap = argparse.ArgumentParser(description="누끼 모델 비교와 수동 선택")
    ap.add_argument("--raw", default="output_objects_raw", help="흰 배경 원본 폴더")
    ap.add_argument("--models", nargs="+", default=MODELS)
    ap.add_argument("--cutouts", default="cutouts", help="모델별 누끼 저장 폴더")
    ap.add_argument("--out", default="compare.png")
    ap.add_argument("--run", action="store_true", help="모델별 누끼를 새로 딴다 (이미 있는 파일은 건너뜀)")
    ap.add_argument("--pick", nargs="+", default=[], metavar="장면-번호=모델", help="고른 결과를 --target 으로 복사")
    ap.add_argument("--target", default="output_objects")
    args = ap.parse_args()

    raw, out_root = Path(args.raw), Path(args.cutouts)
    if not raw.is_dir():
        raise SystemExit(f"원본 폴더가 없습니다: {raw}  (generate_objects_comfy.py 로 생성하면 만들어집니다)")
    files = sorted((p.relative_to(raw) for p in raw.rglob("*.png")), key=lambda r: (key_of(r).zfill(5), str(r)))
    if not files:
        raise SystemExit(f"{raw} 에 PNG 가 없습니다")
    if args.pick:
        pick(raw, files, out_root, args.pick, Path(args.target))
        return
    if args.run:
        run_models(raw, files, args.models, out_root)
    make_sheet(raw, files, args.models, out_root, args.out)


if __name__ == "__main__":
    main()
