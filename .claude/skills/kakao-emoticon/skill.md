---
name: kakao-emoticon
description: "카카오 이모티콘 세트 생성 및 제출 파일 준비. Gemini로 병맛/스케치 이모티콘 시트를 생성하고, Gemini 비전으로 각 이모티콘을 분석·식별하여 개별 360x360 PNG로 분리. 메인/탭 이미지까지 포함한 전체 제출 패키지 생성. 카카오 이모티콘, 이모티콘 만들기, 이모티콘 제출, 병맛 이모티콘, 스케치 이모티콘 요청 시 사용."
---

# 카카오 이모티콘 제작 파이프라인

Gemini 이미지 생성 → Gemini 비전 분석 → 개별 분리 → 카카오 규격 패키징.

## 사전 준비

```bash
pip install google-genai pillow numpy --break-system-packages
```

`GOOGLE_API_KEY` 환경변수가 설정되어 있어야 한다.

## 워크플로우

### Phase 1: 이모티콘 컨셉 정의

1. 사용자에게 캐릭터 컨셉을 확인한다 (미지정 시 기본 캐릭터 사용)
2. 24개 이모티콘의 감정/상황 목록을 작성한다 (`references/kakao-spec.md`의 가이드 참조)
3. `_workspace/descriptions.json`에 저장한다:

```json
[
  "인사하며 손 흔드는 모습 (안녕!)",
  "하트 눈으로 좋아하는 모습 (사랑해)",
  ...
]
```

### Phase 2: 이모티콘 시트 생성

시트당 6개씩, 총 4장의 시트를 생성한다.

```bash
python .claude/skills/kakao-emoticon/scripts/generate_sheet.py \
  --descriptions _workspace/descriptions.json \
  --output-dir _workspace/sheets \
  --per-sheet 6 \
  --model gemini-3-pro-image-preview
```

생성된 각 시트를 Read 도구로 확인한다. 시트 품질이 나쁘면 해당 시트만 재생성:

```bash
python .claude/skills/kakao-emoticon/scripts/generate_sheet.py \
  --descriptions _workspace/descriptions.json \
  --output-dir _workspace/sheets \
  --sheet-index 2
```

### Phase 3: 시트 분석 및 개별 분리

각 시트를 순차적으로 분석·분리한다:

```bash
# 시트 0 (이모티콘 1~6)
python .claude/skills/kakao-emoticon/scripts/analyze_split.py \
  --sheet _workspace/sheets/sheet_00.png \
  --output-dir _workspace/emoticons \
  --start-index 1 --expected 6

# 시트 1 (이모티콘 7~12)
python .claude/skills/kakao-emoticon/scripts/analyze_split.py \
  --sheet _workspace/sheets/sheet_01.png \
  --output-dir _workspace/emoticons \
  --start-index 7 --expected 6

# 시트 2 (이모티콘 13~18)
python .claude/skills/kakao-emoticon/scripts/analyze_split.py \
  --sheet _workspace/sheets/sheet_02.png \
  --output-dir _workspace/emoticons \
  --start-index 13 --expected 6

# 시트 3 (이모티콘 19~24)
python .claude/skills/kakao-emoticon/scripts/analyze_split.py \
  --sheet _workspace/sheets/sheet_03.png \
  --output-dir _workspace/emoticons \
  --start-index 19 --expected 6
```

분리 후 자동으로 품질 검증이 수행된다. 잘림(clipping) 위험이 있는 파일은 보고된다.

### Phase 4: 품질 검증 및 재작업

전체 이모티콘에 대해 일괄 검증:

```bash
python .claude/skills/kakao-emoticon/scripts/analyze_split.py \
  --output-dir _workspace/emoticons \
  --validate-only
```

**잘림이 감지된 경우:**
1. 해당 시트를 재생성 (Phase 2의 `--sheet-index` 사용)
2. 재생성된 시트를 다시 분석·분리 (Phase 3)
3. 최대 2회 재시도. 반복 실패 시 사용자에게 알린다

**검증 기준:**
- 크기: 360×360px
- 투명 배경 존재
- 가장자리 잘림 없음 (테두리 5px 내 불투명 픽셀 < 10%)
- 콘텐츠가 캔버스의 5~85% 차지

### Phase 5: 메인/탭 이미지 생성

24개 이모티콘 중 대표적인 것을 메인/탭 이미지로 사용한다.

```python
from PIL import Image

# 메인 이미지 (240x240) — 01.png 사용
main = Image.open("_workspace/emoticons/01.png")
main = main.resize((240, 240), Image.LANCZOS)
main.save("_workspace/output/main.png")

# 탭 이미지 (96x74) — 01.png 축소
tab = Image.open("_workspace/emoticons/01.png")
tab = tab.resize((96, 74), Image.LANCZOS)
tab.save("_workspace/output/tab.png")
```

### Phase 6: 최종 패키징

```
_workspace/output/
├── main.png (240×240)
├── tab.png (96×74)
├── 01.png ~ 24.png (360×360)
```

모든 파일을 `_workspace/output/`에 복사하고 사용자에게 결과를 보여준다.

## 에러 핸들링

| 상황 | 전략 |
|------|------|
| Gemini API 키 없음 | 사용자에게 GOOGLE_API_KEY 설정 안내 |
| 시트 생성 실패 | 1회 재시도, 재실패 시 모델을 flash로 변경 시도 |
| 바운딩박스 감지 실패 | 프롬프트를 수정하여 재분석 (그리드 힌트 추가) |
| 잘림 검증 실패 | 해당 시트만 재생성 (최대 2회) |
| 이모티콘 수 불일치 | 감지된 수로 진행하되 사용자에게 알림 |

## 프롬프트 커스터마이징

사용자가 캐릭터나 스타일을 지정하면:
- `generate_sheet.py`의 `--character` 옵션으로 캐릭터 설명 전달
- 프롬프트의 스타일 섹션을 사용자 요청에 맞게 수정

## 테스트 시나리오

### 정상 흐름
1. 사용자가 "병맛 이모티콘 만들어줘" 요청
2. Phase 1: 24개 감정/상황 목록 생성, descriptions.json 저장
3. Phase 2: 4장 시트 생성 (각 6개)
4. Phase 3: 각 시트 분석 → 24개 개별 파일 생성
5. Phase 4: 전체 검증 통과
6. Phase 5-6: 메인/탭 생성, 최종 패키지 완성
7. 예상 결과: `_workspace/output/`에 26개 파일

### 에러 흐름
1. Phase 3에서 시트 2의 이모티콘 1개가 잘림 감지
2. Phase 4에서 해당 시트 재생성 (sheet_index=2)
3. 재분석 후 통과
4. 2회 재시도에도 실패 시 사용자에게 알리고 수동 확인 요청
