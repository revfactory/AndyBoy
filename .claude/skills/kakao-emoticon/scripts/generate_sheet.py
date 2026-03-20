#!/usr/bin/env python3
"""
카카오 이모티콘 시트 생성 스크립트

Gemini 이미지 생성 API로 이모티콘 시트를 생성한다.
한 장에 여러 이모티콘을 그리드 형태로 배치.

사용법:
    python generate_sheet.py --descriptions descriptions.json --output-dir ./sheets
    python generate_sheet.py --descriptions descriptions.json --output-dir ./sheets --per-sheet 6
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path


def generate_emoticon_sheet(
    descriptions: list[str],
    sheet_index: int,
    output_dir: str,
    character_desc: str = "",
    model: str = "gemini-3-pro-image-preview",
    per_sheet: int = 6,
) -> str | None:
    """
    Gemini API로 이모티콘 시트 1장 생성

    Args:
        descriptions: 이모티콘 설명 리스트 (이 시트에 포함할 것들)
        sheet_index: 시트 번호 (0-based)
        output_dir: 출력 디렉토리
        character_desc: 캐릭터 외형 설명
        model: Gemini 모델명
        per_sheet: 시트당 이모티콘 수

    Returns:
        생성된 이미지 파일 경로 또는 None
    """
    from google import genai
    from google.genai import types

    client = genai.Client()

    # 그리드 레이아웃 결정
    count = len(descriptions)
    if count <= 3:
        cols, rows = count, 1
    elif count <= 6:
        cols, rows = 3, 2
    elif count <= 8:
        cols, rows = 4, 2
    else:
        cols, rows = 4, 3

    # 이모티콘 목록 포매팅
    desc_list = "\n".join(f"  {i+1}. {d}" for i, d in enumerate(descriptions))

    if not character_desc:
        character_desc = (
            "둥글고 하얀 떡 같은 얼굴에 짧은 팔다리가 달린 단순한 캐릭터. "
            "두꺼운 검은 외곽선, 최소한의 디테일. "
            "눈은 점 두 개, 입은 상황에 따라 과장되게 변함."
        )

    prompt = f"""Draw a {cols}x{rows} grid of Korean-style "병맛" (absurdly funny) emoticons on a pure white background.

Character: {character_desc}

Style rules:
- Thick black outlines, minimal detail, intentionally crude/wobbly lines
- Exaggerated facial expressions (huge mouth, tiny eyes or vice versa)
- Each emoticon must be clearly separated with generous white space between them
- Each emoticon sits in its own equal-sized cell in the grid
- NO overlap between emoticons
- Every emoticon must be FULLY visible (no clipping at edges)
- Simple sketch style, like doodled on a napkin
- No text or labels inside the emoticons

The {count} emoticons in order (left to right, top to bottom):
{desc_list}

IMPORTANT: Keep each emoticon well within its grid cell boundaries. Leave clear margins around each one."""

    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
                image_config=types.ImageConfig(
                    aspect_ratio="1:1" if rows == cols else ("3:2" if cols > rows else "2:3"),
                    image_size="2K",
                ),
            ),
        )

        output_path = os.path.join(output_dir, f"sheet_{sheet_index:02d}.png")

        for part in response.parts:
            if part.text:
                print(f"  [Gemini] {part.text[:200]}")
            elif image := part.as_image():
                image.save(output_path)
                print(f"  [저장됨] {output_path}")
                return output_path

        print(f"  [경고] 시트 {sheet_index}: 이미지가 생성되지 않음")
        return None

    except Exception as e:
        print(f"  [오류] 시트 {sheet_index}: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description="카카오 이모티콘 시트 생성")
    parser.add_argument(
        "--descriptions",
        required=True,
        help="이모티콘 설명 JSON 파일 경로 (리스트 형태)",
    )
    parser.add_argument(
        "--output-dir",
        default="./sheets",
        help="출력 디렉토리 (기본: ./sheets)",
    )
    parser.add_argument(
        "--character",
        default="",
        help="캐릭터 외형 설명",
    )
    parser.add_argument(
        "--per-sheet",
        type=int,
        default=6,
        help="시트당 이모티콘 수 (기본: 6)",
    )
    parser.add_argument(
        "--model",
        default="gemini-3-pro-image-preview",
        help="Gemini 모델 (기본: gemini-3-pro-image-preview)",
    )
    parser.add_argument(
        "--sheet-index",
        type=int,
        default=None,
        help="특정 시트만 생성 (0-based index)",
    )

    args = parser.parse_args()

    # 설명 로드
    with open(args.descriptions, "r", encoding="utf-8") as f:
        all_descriptions = json.load(f)

    os.makedirs(args.output_dir, exist_ok=True)

    # 시트별로 분할
    per = args.per_sheet
    sheets = [all_descriptions[i : i + per] for i in range(0, len(all_descriptions), per)]

    if args.sheet_index is not None:
        # 특정 시트만 생성
        if args.sheet_index >= len(sheets):
            print(f"오류: sheet_index {args.sheet_index}가 범위 밖 (총 {len(sheets)}장)")
            sys.exit(1)
        sheets_to_gen = [(args.sheet_index, sheets[args.sheet_index])]
    else:
        sheets_to_gen = list(enumerate(sheets))

    results = []
    for idx, desc_group in sheets_to_gen:
        print(f"\n📝 시트 {idx} 생성 중 ({len(desc_group)}개 이모티콘)...")
        result = generate_emoticon_sheet(
            descriptions=desc_group,
            sheet_index=idx,
            output_dir=args.output_dir,
            character_desc=args.character,
            model=args.model,
            per_sheet=per,
        )
        results.append({"sheet_index": idx, "path": result, "count": len(desc_group)})

        # API 레이트 리밋 방지
        if idx < len(sheets_to_gen) - 1:
            time.sleep(2)

    # 결과 요약
    success = sum(1 for r in results if r["path"])
    print(f"\n✅ {success}/{len(results)} 시트 생성 완료")

    # 결과 JSON 저장
    manifest_path = os.path.join(args.output_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"📋 매니페스트: {manifest_path}")


if __name__ == "__main__":
    main()
