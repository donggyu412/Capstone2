# 이전 구현

현재 실행 경로는 `main.py` → `runtime/dream_pipeline.py` 또는 `runtime/render_final.py`다.
이 폴더는 이전 formation, geometric, painterly, developmental, emergence 실험과 회귀 테스트용 구현을 보존한다. 현재 렌더는 이 폴더를 불러오지 않는다.

공통으로 쓰던 영역 추출, 보간, 영상 인코딩, 오디오 구간 추출, 파일 해시는 `runtime`으로 분리했다. 이전 구현도 같은 공통 함수를 사용한다.

`notes/`는 로컬 작업 기록이며 Git에서 제외한다. 기존 MP4·실행 보고서·중간 상태는 `../output/`에 유지한다. 과거 보고서의 해시와 pickle 중간 상태는 당시 소스 기준이므로, 현재 버전의 결과로 간주하지 않는다. 과거 체크포인트를 다시 열 때는 해당 시점의 소스와 환경이 필요하다.
