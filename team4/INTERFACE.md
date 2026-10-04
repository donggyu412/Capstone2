# Team 1/2/3 → Team 4 입력 계약

현재 단계는 **Interface / Pipeline Skeleton Prototype**이다. 이 문서는 저장소에서 확인한 출력 형태와 Team 4가 임시로 수용하는 입력을 구분한다. 팀 간 합의가 필요한 내용은 **예정 / 확인 필요**로 표시한다.

## 계약 상태

| 제공 팀 | 확인한 내용 | 예정 / 확인 필요 |
| --- | --- | --- |
| Team 1 | 감정·집단 공감 데이터를 향후 사용한다는 설계 맥락 | 원본 스키마, 집단 반응의 정의·정규화, 전달 위치·주기, Team 2를 통한 전달 방식 |
| Team 2 | 현재 `team2/step2_story_v2.py`가 `dream_scenes.json`을 `{"scenes": [...]}`로 내보냄 | 운영 시 실제 저장 위치, 버전 관리, Team 4와의 전달 절차 |
| Team 3 | 배경 이미지·투명 오브제 PNG·`scenes.json`이 입력 후보 | 현재 기준 저장소에는 `team3/` 디렉터리가 없음. 실제 생성 경로, 파일명, manifest 형식, 장면·오브제 연결 규칙 모두 협의 후 확정 |

Team 2의 현재 코드에서 확인한 형식은 연동 근거이며, 다른 팀과 합의가 완료되었다는 뜻은 아니다. `dream_scenes.json`은 실제 출력 코드로 확인한 파일명이다. 구체적인 디렉터리는 한 위치로 고정하지 않는다.

## Team 2: 확인된 출력 형태

아래는 현재 `team2/step2_story_v2.py`의 export 구조를 설명하는 예시다. 값은 설명용이며 실제 분석·생성 결과가 아니다.

```json
{
  "scenes": [
    {
      "scene": 1,
      "story": "설명용 장면 이야기",
      "backgrounds": ["설명용 배경"],
      "objects": ["설명용 오브제"],
      "emotions": ["설명용 감정"],
      "physics_laws": [],
      "main_emotion": {"label": "중립", "intensity": 0.5},
      "vector": [0.5, 0.5, 0.5, 0.5]
    }
  ]
}
```

실제 Team 2 생성 코드는 장면 4개를 내보낸다. `vector`의 순서는 **`tension`, `strangeness`, `density`, `temperature`**다. `backgrounds`·`objects`의 문자열은 의미상 항목 이름이며, 이미지 파일 경로라고 간주하지 않는다.

## Team 4의 임시 수용 규칙

| 입력 | 처리 |
| --- | --- |
| `scenes` 배열 또는 최상위 배열 | 입력 순서대로 최대 4개를 사용 |
| `scene` | 문자열·정수이면 `source_scene`으로 보존, 그 외 `null`. 내부 장면 단계는 배열 순서로 배정 |
| `story` | 장면 설명 후보. 실제 렌더링에는 아직 사용하지 않음 |
| `background` / `backgrounds` | 배경 설명 후보. 자산의 존재를 보장하지 않음 |
| `objects` | 오브제 설명 후보. 이름만으로 파일을 합성하지 않음 |
| `physics_laws` | 향후 엔진용 메타데이터 후보. 실제 물리 규칙 적용은 TODO |
| `main_emotion.label` | 현재 Team 2 형식의 감정 이름 |
| `main_emotion.intensity` | 현재 Team 2 형식의 감정 강도 |
| 단순 문자열 `main_emotion` 및 최상위 `intensity` / `emotion_intensity` | 평탄한 입력 형식을 위한 fallback |
| `collective_response` | 집단 반응의 임시 입력 필드. Team 1 공식 계약은 예정 / 확인 필요 |
| `vector` | 현재 Team 2의 4차원 순서 배열 또는 이름별 객체를 수용 |
| `tension`, `strangeness`, `density`, `temperature` | 최상위에 있으면 `vector`의 같은 성분보다 우선 |

JSON 구조 수용은 `pipeline_io/adapters.py`, 상태 필드 선택과 정규화는 `models/state.py`가 담당한다. 감정 강도는 중첩 `main_emotion.intensity`, 최상위 `intensity`, 최상위 `emotion_intensity` 순으로 **존재하는 필드**를 선택한다. 선택한 값이 잘못되면 `0.5`를 사용하며 하위 우선순위 값으로 다시 대체하지 않는다. 최상위 vector 성분에도 같은 원칙을 적용한다. 필드 누락·자료형 오류가 `KeyError`로 실행을 중단시키지 않는다. 현재 허용 입력을 타 팀의 확정 스키마로 해석하면 안 된다.

### 장면과 수치 규칙

- 내부 `scene_index`는 입력 순서대로 `1~4`이며 `narrative_stage`는 각각 `기`, `승`, `전`, `결`이다.
- 4개 미만이면 있는 장면만 사용한다. 4개 초과이면 경고하고 첫 4개를 사용한다.
- 장면 항목이 객체가 아니면 해당 위치에 기본 상태를 생성하고 경고한다.
- 감정 이름의 임시 기본값은 `중립`이다.
- 감정 강도, 집단 반응, 긴장, 낯섦, 밀도, 온도의 임시 기본값은 각각 `0.5`다.
- 숫자 및 숫자 문자열은 유한한 `0.0~1.0`으로 clamp한다. boolean, 해석할 수 없는 값, 비유한 값에는 임시 기본값을 사용한다.
- 상태 수치는 현재 인터페이스를 위한 정규화 값이다. 감정 강도·집단 반응의 실제 척도와 `temperature`의 의미는 **예정 / 확인 필요**다.

기본값 사용은 실제 관측 결과의 존재를 의미하지 않는다. 감정별 의미를 학습하거나 과학적으로 보정한 매핑은 아직 구현하지 않았다.

## 경로 탐색

`pipeline_io/adapters.py`의 `STORY_SEARCH_ROOTS`와 `ASSET_SEARCH_ROOTS`가 탐색 후보를 관리한다. `team2/`, `team3/` 및 저장소 내부의 input/storyboard 관련 위치는 후보이며, 특정 팀의 확정 출력 경로가 아니다. 후보 루트 순서와 정렬된 하위 경로 순서로 탐색하고, 심볼릭 링크·Windows junction·가상환경 등은 제외한다. 자동 JSON 탐색은 유효한 첫 입력을 선택한다. 후보가 여러 개면 선택한 파일을 경고에 표시한다.

```console
python team4/main.py
python team4/main.py --input path/to/dream_scenes.json --seed 42
```

`--input`은 자동 탐색 대신 사용할 파일을 명시한다. 상대경로는 명령을 실행한 작업 디렉터리 기준이다. 지정한 파일에 문제가 있어도 다른 파일을 자동 선택하지 않는다. 사용자 PC의 절대경로를 코드에 하드코딩하지 않는다. 파일 탐색과 입력 처리는 기존 팀 파일을 변경하지 않는다.

UTF-8과 UTF-8 BOM JSON을 읽는다. 사용할 입력을 찾지 못하면 안내와 경고를 남기고, 장면이 없는 계획 파일을 생성하여 정상 종료한다. 자동 탐색 중 읽기·파싱에 실패한 후보는 경고하고 다음 후보를 확인한다. 출력 디렉터리에 저장할 수 없는 상황까지 성공으로 보고하지는 않는다.

## Team 3: 예정 자산 계약

| 자산 후보 | 현재 처리 | 예정 / 확인 필요 |
| --- | --- | --- |
| `scene_01.png`~`scene_04.png` | 존재하는 장면별 배경 경로만 기록 | 실제 파일명, 저장 경로, 해상도, 배경·완성 장면의 구분 |
| 오브제 이미지 폴더 | 발견한 자산 경로를 기록 | 장면별 디렉터리 구조, 오브제 ID, 투명도, 좌표·스케일 |
| `scenes.json` | 존재하는 manifest 경로만 기록 | JSON 스키마와 장면·배경·오브제 매핑 규칙 |

현재 `scenes.json`의 내용은 파싱하지 않는다. `objects`·`object`·`object_images` 디렉터리 안의 이미지가 오브제 후보이며, 조상 디렉터리에 `scene_01`·`scene-1` 같은 명시적 장면 폴더가 있을 때만 해당 장면에 연결한다. 이 규칙은 Team 4의 임시 탐색 규칙이며 Team 3의 확정 계약은 아니다. 공용 파일은 `asset_inventory.shared_object_asset_paths`에 기록하고 모든 장면에 임의 배정하지 않는다. 동일 장면의 배경이 여럿이면 후보 순서의 첫 경로를 사용하고 경고한다.

배경이 없으면 `background_asset_path`는 `null`, 해당 장면에 연결된 오브제가 없으면 `object_asset_paths`는 `[]`다. 투명 PNG 여부나 이미지의 시각적 품질은 현재 검증하지 않는다.

## Team 4 출력 계약

항상 `team4/output/pipeline_plan.json`에 계획을 저장한다. 최상위 구조는 다음과 같다.

| 출력 필드 | 의미 |
| --- | --- |
| `schema_version`, `stage`, `rendered` | 현재 스키마 버전 `1`, prototype 단계, 실제 렌더링 여부 `false` |
| `source_path` | 선택된 유효 입력 경로 또는 `null` |
| `seed`, `seed_usage` | seed와 현재 메타데이터 전용이라는 설명 |
| `warnings` | 입력·자산·임시 기본값에 관한 안내 |
| `asset_inventory` | `backgrounds`, `object_directories`, `shared_object_asset_paths`, `scene_manifest_paths`, `manifest_status` |
| `scenes` | 장면별 계획 목록. 사용할 입력이 없으면 `[]` |

경로는 저장소 내부이면 `/` 구분자의 저장소 상대경로로 기록한다. 명시적으로 지정한 외부 입력은 해석된 절대경로로 기록한다. 이 방식은 실행 환경에서 경로를 계산하는 것이며 코드에 사용자 경로를 고정하지 않는다.

각 장면의 계획에는 다음 항목을 포함한다.

| 출력 필드 | 의미 |
| --- | --- |
| `scene_index` / `source_scene` | 입력 순서에 따른 내부 번호 / 보존 가능한 원본 장면 ID |
| `narrative_stage` | 입력 순서에 따른 기·승·전·결 |
| `story`, `backgrounds`, `objects`, `physics_laws` | 문자열·문자열 목록으로 정리한 설명 메타데이터 |
| `emotion` / `emotion_intensity` | 감정 이름·정규화된 강도 |
| `collective_response` | 정규화된 집단 반응 또는 임시 기본값 |
| `state_vector` | `tension`, `strangeness`, `density`, `temperature`의 객체 |
| `mapped_parameters` | 향후 엔진에 전달할 `0.0~1.0`의 prototype 파라미터 |
| `background_asset_path` | 발견하고 연결한 배경 경로 또는 `null` |
| `object_asset_paths` | 발견하고 연결한 오브제 경로 목록 |
| `planned_background_engine` | 향후 CA 배경 엔진 계획 |
| `planned_object_engine` | 향후 swarm/particle 오브제 엔진 계획 |
| `planned_interaction` | 향후 배경·오브제 상호작용 계획 |
| `planned_transition` | 향후 장면 전환 계획 |

`mapped_parameters`는 `ca_activity`, `ca_birth_bias`, `object_speed`, `object_cohesion`, `object_dispersion`, `stochasticity`, `transition_threshold`를 포함한다. 임시 공식과 한계는 [README.md](README.md)의 Prototype mapping 항목을 따른다.

seed의 기본값은 `42`다. 기본 파이프라인은 이를 메타데이터로 저장하며 임의의 수치 변동을 자동 적용하지 않는다. 확률 변동 보조 함수는 향후 엔진에서 별도로 연결해야 한다.

이 출력은 **계획 파일**이다. 실제 CA·Object Swarm·상호작용 프레임·MP4·사운드·영상 평가 결과는 포함하지 않는다. Controller·Mapper 등 모듈명은 Team 4 내부 설계 명칭이다.

## 연동 전에 확인할 사항

1. Team 1: 집단 반응 값의 정의·범위·결측값 정책 및 Team 2/4로 전달하는 방법.
2. Team 2: 실제 출력 디렉터리, 장면 식별자·순서, 필드 및 vector 버전 관리.
3. Team 3: 배경과 투명 오브제의 저장 위치, 장면별 연결 규칙, `scenes.json` 스키마.
4. Team 4: 프레임 크기·길이·FPS, 오브제 좌표, 사운드 입력과 최종 출력 계약.

이 항목들은 모두 **예정 / 확인 필요**이며 현재 구현 완료 또는 팀 간 합의 사항으로 취급하지 않는다.
