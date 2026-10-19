"""경로 — 저장소 루트 기준으로 잡아, 어느 폴더에서 실행해도 같은 파일을 찾는다.

  Capstone2/
  └─ team3/
     ├─ background/input/storyboard/   dream_scenes.json · scene_01.png …   (읽기만)
     ├─ object/                         output_objects/ 또는 dataset/10_dream_object/ (읽기만)
     └─ sound/                          ← 이 코드
"""
import os

SOUND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # team3/sound
TEAM3_DIR = os.path.dirname(SOUND_DIR)
REPO_DIR = os.path.dirname(TEAM3_DIR)

BACKGROUND_DIR = os.path.join(TEAM3_DIR, 'background')
STORYBOARD_DIR = os.path.join(BACKGROUND_DIR, 'input', 'storyboard')
OBJECT_DIR = os.path.join(TEAM3_DIR, 'object')

OUTPUT_DIR = os.path.join(SOUND_DIR, 'output')          # 가장 최근 결과가 바로 여기 (새로 만들면 바뀜) · .gitignore 로 깃 제외
CACHE_DIR = os.path.join(SOUND_DIR, 'cache')            # 그림 인식 결과 캐시 (깃 제외)

IMAGE_EXT = ('.png', '.jpg', '.jpeg')
VIDEO_EXT = ('.mp4', '.webm', '.mov', '.mkv', '.avi')


def rel(path):
    """보고서·로그용 — 저장소 루트 기준 상대경로."""
    try:
        return os.path.relpath(path, REPO_DIR).replace('\\', '/')
    except ValueError:
        return path
