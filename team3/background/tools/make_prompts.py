# -*- coding: utf-8 -*-
"""꿈의 소산 — 배경 이미지 프롬프트 도구 (2팀 스토리보드 → 장면별 배경 프롬프트)

2팀 스토리보드에는 글만 있다. 우리 엔진은 이미지를 받아 아피찻퐁식으로 흩뜨리므로,
그 사이에 '글 → 배경 이미지' 단계가 필요하다(0917 미팅: 스토리보드 → 이미지는 3팀 몫).
이 도구는 그 단계의 앞절반 — 장면마다 생성기에 넣을 프롬프트를 만든다.

  (프로젝트 최상위에서)
  python tools/make_prompts.py        → 화면에 출력 + input/storyboard/prompts.txt 저장

쓰는 법 (지금 — 방법 A):
  prompts.txt 의 장면별 문장을 웹 이미지 생성기(ChatGPT, Bing Image Creator 등)에 붙여넣고,
  결과를 input/storyboard/scene_01.png … 로 저장한다. 그다음 python app.py → 새로고침이면 그려진다.
  (나중에 API 로 넘어가도 이 프롬프트를 그대로 쓴다 — 생성 방법만 바뀐다)

★ 역할 분담 — 생성기는 '무엇이 있는 장면인가'만 맡는다.
  아피찻퐁 스타일(색·구도·해체·안개)은 기존 DB·파티클 엔진이 입힌다. 그래서 프롬프트에
  작가 이름을 넣지 않는다: 생성기가 스타일까지 입히면 엔진이 한 번 더 입혀 이중으로 뭉개지고,
  '생성 모델이 스타일을 베꼈다'가 되어 우리 DB·Open-ended 엔진의 몫이 사라진다.

★ 오브제는 빼달라고 적는다. objects(새·책 표지 등)는 시스템 II(로봇의 꿈 = 오브제) 몫이다.
  배경에 박혀 나오면 나중에 오브제를 얹을 때 같은 것이 두 번 나온다.

★ 명암이 있는 사진을 요구한다. 엔진은 이미지 밝기 분포로 파편의 자리·안개·빛을 정하는데,
  순백·순흑처럼 균일한 이미지는 화면이 탄다(3-6 C-1, 실측 타는 면적 96~98%).

추가 설치 없음. app.py 와 같은 규칙(막 배정·감정 라벨)을 쓰려고 app.py 를 불러온다.
"""
import sys
sys.dont_write_bytecode = True   # 도구끼리 import 해도 __pycache__ 가 쌓이지 않게 (09-27 폴더 정리)
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import app  # noqa: E402  — 막·감정 규칙을 app.py 와 하나로 유지하려고 가져온다 (따로 베끼면 어긋난다)

# 막별 분위기 — index.html ACTS 의 물리 성격을 '사진으로 찍힐 수 있는 말'로 옮긴 것.
# 엔진이 막마다 하는 일(기 흩날림 · 승 안착 · 전 빛 · 결 안개)과 반대되는 사진이 오면
# 엔진이 싸우느라 결과가 흐려진다. 같은 방향으로 찍어 두면 엔진이 그 위에서 더 멀리 간다.
# 실내·야외 어느 쪽에도 맞는 말로 적는다(09-28) — 처음엔 호수·숲(야외) 기준이라 '눈발'·'나뭇가지 틈'·
# '자연광'이 박혀 있었고, 2팀 수정본이 복도·서가(실내)로 바뀌자 장소와 부딪혔다. 장소는 backgrounds 가 정한다.
ACT_MOOD = {
    '기': '흐리고 불안정한 빛, 공기 중에 떠다니는 먼지나 물기, 아직 자리 잡지 못한 듯 어수선한 공간',
    '승': '고요하고 가라앉은 공기, 부드럽게 퍼지는 확산광, 사물이 제자리에 멈춰 선 정적인 공간',
    '전': '틈으로 강하게 새어 들어오는 한 줄기 빛, 밝은 곳과 어두운 곳의 대비가 뚜렷함',
    '결': '짙은 안개나 뿌연 공기가 공간을 천천히 지워 가는 모습, 화면의 많은 부분이 비어 있는 넓은 여백',
}

# 감정 라벨 → 색·빛의 말. index.html EMOTIONS 표(채도·난색·안개·빛)와 같은 방향으로 적었다.
EMO_MOOD = {
    # 1팀 7종 (09-27) — 중립은 색을 밀지 않는다
    '슬픔':  '채도가 낮고 푸르스름한 회색 톤',
    '공포':  '차갑고 어두운 색조, 그림자가 깊음',
    '놀람':  '갑자기 트인 맑은 빛, 선명한 명암',
    '혐오':  '탁하고 칙칙한 색조, 빛이 가라앉은 공기',
    # 예전 라벨 (더미)
    '불안':  '차갑고 약간 푸른 색조, 불안정한 빛',
    '두려움': '차갑고 어두운 색조, 그림자가 깊음',
    '우울':  '채도가 낮고 푸르스름한 회색 톤',
    '공허':  '색이 거의 빠진 옅은 톤, 넓게 빈 공간',
    '평온':  '부드럽고 따뜻한 중간 톤',
    '그리움': '빛바랜 따뜻한 색조, 오래된 사진 같은 느낌',
    '경이':  '맑고 밝은 빛, 은은하게 빛나는 공기',
    '기쁨':  '따뜻하고 밝은 색조',
    '분노':  '붉고 따뜻한 색조, 강한 대비',
}

# PDF 시스템 I '아날로그 느낌' — 빛·몽환·단순·바람·비·안개·여백.
# '비'는 모든 장면에 강제하지 않는다(얼어붙은 호수에 비를 내리면 2팀 이야기를 바꾸게 된다).
# '자연광'·'풍경' 대신 장소에 있는 빛 그대로 — 형광등·알전구가 나오는 실내 장면과 부딪히지 않게(09-28).
COMMON = ('필름 카메라로 찍은 듯한 아날로그 사진, 은은한 필름 입자, 과장 없이 그 장소에 있는 빛 그대로, '
          '옅은 안개와 공기의 흐름, 단순한 구도와 넓은 여백, 몽환적이지만 사실적인 장소 사진, 가로로 넓은 16:9 화면')
AVOID_BASE = '사람, 동물, 글자, 로고, 테두리, 그림체·일러스트·3D 렌더링 느낌'
EXPOSURE = '화면 전체가 하얗거나 새까맣게 균일하지 않고, 밝은 부분과 어두운 부분이 함께 있을 것'


def split_objects(backgrounds, objects):
    """오브제 → (빼달라고 적을 것, 배경과 겹쳐 적지 않는 것).

       2팀 데이터는 배경과 오브제가 겹치기도 한다(4장면: 배경 '자작나무 껍질 더미' / 오브제 '자작나무 껍질').
       둘 다 적으면 '껍질 더미를 그리되 껍질은 빼라'가 되어 생성기가 헷갈린다. 배경이 우선이다 —
       배경은 우리 몫이고, 오브제는 나중에 시스템 II 가 그 위에 얹는다."""
    toks = set()
    for b in backgrounds:
        for t in b.replace('(', ' ').replace(')', ' ').replace(',', ' ').split():
            if len(t) >= 2:
                toks.add(t)
    keep, overlap = [], []
    for o in objects:
        (overlap if any(t in o for t in toks) else keep).append(o)
    return keep, overlap


def build_prompt(sc, objects):
    bg = sc['backgrounds'] or [sc['title']]
    lines = [
        '다음 장소의 사진을 만들어 주세요: ' + ', '.join(bg) + '.',
        ACT_MOOD.get(sc['stage'], '') + '.',
    ]
    if sc['emotion'] in EMO_MOOD:
        lines.append(EMO_MOOD[sc['emotion']] + '.')
    lines.append(COMMON + '.')
    lines.append(EXPOSURE + '.')
    avoid = AVOID_BASE + (', ' + ', '.join(objects) if objects else '')
    lines.append('들어가면 안 되는 것: ' + avoid + '.')
    return ' '.join(l for l in lines if l.strip('. '))


def main():
    mode, path, base_dir = app.pick_source()
    if mode != 'storyboard':
        sys.exit('input/storyboard/ 에 2팀 스토리보드 JSON 이 없습니다. (더미 자료는 이미지가 이미 있어 프롬프트가 필요 없습니다)')
    rows = app.read_scene_list(path) or []      # 번호순 정렬·번호 정리까지 끝나서 온다

    out = ['배경 이미지 프롬프트 — %s (%d장면)' % (os.path.relpath(path, ROOT).replace('\\', '/'), len(rows)),
           '각 문장을 이미지 생성기에 붙여넣고, 결과를 input/storyboard/ 에 옆에 적힌 이름으로 저장하세요.',
           '(가로 16:9, 1280px 이상 권장 · png 가 아니어도 이름만 scene_01.png 면 읽힙니다)', '']
    for i, row in enumerate(rows):
        sc = app.to_scene(i, len(rows), row, base_dir)
        objects = [o for o in (row.get('objects') or []) if isinstance(o, str)]
        objects, overlap = split_objects(sc['backgrounds'] or [], objects)
        name = 'scene_%02d.png' % sc['act']
        have = os.path.exists(os.path.join(base_dir, name))
        out += ['=' * 70,
                '%d. [%s] %s   → %s %s' % (sc['act'], sc['stage'], sc['title'], name, '(있음)' if have else '(필요)'),
                '   감정: %s%s' % (sc['emotion'] or '없음',
                                 ' ← "%s"' % sc['emotion_src'] if sc['emotion_src'] else ''),
                *(['   ※ 배경과 겹쳐 제외 목록에서 뺀 오브제: ' + ', '.join(overlap)] if overlap else []),
                '-' * 70,
                build_prompt(sc, objects), '']

    text = '\n'.join(out)
    print(text)
    # .txt 로 쓴다 — .json 이면 app.py 가 '가장 최근 스토리보드'로 착각해 읽어 버린다.
    dst = os.path.join(base_dir, 'prompts.txt')
    with open(dst, 'w', encoding='utf-8-sig') as f:   # BOM: 메모장에서 한글이 깨지지 않게
        f.write(text)
    print('저장: ' + os.path.relpath(dst, ROOT))


if __name__ == '__main__':
    main()
