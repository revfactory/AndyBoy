#!/usr/bin/env python3
"""
이모티콘 시트 분석 및 개별 파일 분리 스크립트

2단계 접근:
1. Gemini 비전으로 그리드 레이아웃(행x열) 확인
2. 균등 분할 후 각 셀에서 콘텐츠 영역을 자동 감지하여 중앙 정렬

사용법:
    python analyze_split.py --sheet sheets/sheet_00.png --output-dir ./emoticons --start-index 1
    python analyze_split.py --sheet sheets/sheet_00.png --output-dir ./emoticons --expected 6
    python analyze_split.py --output-dir ./emoticons --validate-only
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path


def detect_grid_layout(
    sheet_path: str,
    expected_count: int = 6,
    model: str = "gemini-3-pro-image-preview",
) -> dict:
    """
    Gemini 비전으로 시트의 그리드 레이아웃을 확인한다.

    Returns:
        {"rows": int, "cols": int, "labels": list[str]}
    """
    from google import genai
    from google.genai import types
    from PIL import Image

    client = genai.Client()
    img = Image.open(sheet_path)

    prompt = f"""This image contains approximately {expected_count} emoticons arranged in a grid layout.

Analyze the grid structure and return ONLY a JSON object (no markdown, no code fence):
{{
  "rows": <number of rows>,
  "cols": <number of columns>,
  "labels": [<brief description of each emoticon, left-to-right top-to-bottom>]
}}

Count carefully. The grid is likely {expected_count // 3}x3 or {expected_count // 2}x2."""

    response = client.models.generate_content(
        model=model,
        contents=[prompt, img],
        config=types.GenerateContentConfig(
            response_modalities=["TEXT"],
        ),
    )

    text = response.text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            result = json.loads(match.group())
        else:
            # 기본값: 3x2 그리드
            result = {"rows": 2, "cols": 3, "labels": [f"emoticon {i+1}" for i in range(expected_count)]}

    return result


def grid_split(
    sheet_path: str,
    rows: int,
    cols: int,
    labels: list[str],
    output_dir: str,
    start_index: int = 1,
    target_size: int = 360,
    padding_pct: float = 0.05,
) -> list[dict]:
    """
    시트를 균등 그리드로 분할한 후, 각 셀에서 콘텐츠 영역을 감지하여
    정사각형으로 잘라내고 투명 배경 처리한다.

    Args:
        sheet_path: 시트 이미지 경로
        rows: 그리드 행 수
        cols: 그리드 열 수
        labels: 각 이모티콘 레이블
        output_dir: 출력 디렉토리
        start_index: 시작 파일 번호
        target_size: 출력 크기 (정사각형)
        padding_pct: 콘텐츠 주변 여백 비율
    """
    from PIL import Image
    import numpy as np

    img = Image.open(sheet_path).convert("RGBA")
    w, h = img.size
    cell_w = w // cols
    cell_h = h // rows

    os.makedirs(output_dir, exist_ok=True)
    results = []

    for idx in range(rows * cols):
        row = idx // cols
        col = idx % cols

        # 셀 영역 크롭 (그리드 라인 제거를 위해 안쪽으로 약간 오프셋)
        margin = 3  # 그리드 라인 두께 대비 여유
        x1 = col * cell_w + margin
        y1 = row * cell_h + margin
        x2 = (col + 1) * cell_w - margin
        y2 = (row + 1) * cell_h - margin

        cell = img.crop((x1, y1, x2, y2))

        # 콘텐츠 영역 감지 (비-흰색 픽셀 찾기)
        cell_data = np.array(cell.convert("RGB"))
        # 흰색이 아닌 픽셀 (R,G,B 중 하나라도 230 이하)
        content_mask = (cell_data[:, :, 0] < 230) | (cell_data[:, :, 1] < 230) | (cell_data[:, :, 2] < 230)

        if not content_mask.any():
            print(f"  [건너뜀] 셀 {idx}: 콘텐츠 없음")
            continue

        # 콘텐츠 바운딩박스
        rows_with_content = np.any(content_mask, axis=1)
        cols_with_content = np.any(content_mask, axis=0)
        cy1 = np.argmax(rows_with_content)
        cy2 = len(rows_with_content) - np.argmax(rows_with_content[::-1])
        cx1 = np.argmax(cols_with_content)
        cx2 = len(cols_with_content) - np.argmax(cols_with_content[::-1])

        content_w = cx2 - cx1
        content_h = cy2 - cy1

        # 정사각형으로 확장 + 여백 추가
        size = max(content_w, content_h)
        padding = int(size * padding_pct)
        size += padding * 2

        # 콘텐츠 중심
        center_x = (cx1 + cx2) // 2
        center_y = (cy1 + cy2) // 2

        # 정사각형 영역 (셀 내 좌표)
        sq_x1 = max(0, center_x - size // 2)
        sq_y1 = max(0, center_y - size // 2)
        sq_x2 = min(cell.width, center_x + size // 2)
        sq_y2 = min(cell.height, center_y + size // 2)

        cropped = cell.crop((sq_x1, sq_y1, sq_x2, sq_y2))

        # 정사각형 캔버스에 중앙 배치
        canvas = Image.new("RGBA", (size, size), (255, 255, 255, 255))
        paste_x = (size - cropped.width) // 2
        paste_y = (size - cropped.height) // 2
        canvas.paste(cropped, (paste_x, paste_y))

        # 흰색 → 투명
        canvas = remove_white_background(canvas)

        # 타겟 크기로 리사이즈
        canvas = canvas.resize((target_size, target_size), Image.LANCZOS)

        # 저장
        file_num = start_index + idx
        filename = f"{file_num:02d}.png"
        filepath = os.path.join(output_dir, filename)
        canvas.save(filepath, "PNG")

        label = labels[idx] if idx < len(labels) else f"emoticon {idx + 1}"
        results.append({
            "file": filepath,
            "index": file_num,
            "label": label,
            "cell": {"row": row, "col": col},
            "content_box": {"x": cx1, "y": cy1, "w": content_w, "h": content_h},
        })
        print(f"  [{file_num:02d}] {label} → {filepath}")

    return results


def remove_white_background(img, threshold: int = 235):
    """흰색 배경을 투명으로 변환."""
    from PIL import Image
    import numpy as np

    data = np.array(img.convert("RGBA"))
    white_mask = (data[:, :, 0] >= threshold) & (data[:, :, 1] >= threshold) & (data[:, :, 2] >= threshold)
    data[white_mask, 3] = 0
    return Image.fromarray(data)


def validate_emoticon(filepath: str, target_size: int = 360) -> dict:
    """개별 이모티콘 파일의 품질 검증."""
    from PIL import Image
    import numpy as np

    img = Image.open(filepath).convert("RGBA")
    data = np.array(img)

    size_ok = img.size == (target_size, target_size)

    alpha = data[:, :, 3]
    transparent_ratio = (alpha == 0).sum() / alpha.size

    # 가장자리 잘림 검사 (테두리 3px)
    border = 3
    edges = np.concatenate([
        alpha[:border, :].flatten(),
        alpha[-border:, :].flatten(),
        alpha[:, :border].flatten(),
        alpha[:, -border:].flatten(),
    ])
    edge_opaque_ratio = (edges > 128).sum() / edges.size
    clipping_risk = edge_opaque_ratio > 0.15  # 15% 이상이면 잘림

    # 콘텐츠 영역 비율
    content_mask = alpha > 128
    if content_mask.any():
        rows_any = np.any(content_mask, axis=1)
        cols_any = np.any(content_mask, axis=0)
        content_h = rows_any.sum()
        content_w = cols_any.sum()
        content_ratio = (content_h * content_w) / (target_size * target_size)
    else:
        content_ratio = 0

    return {
        "file": filepath,
        "size_ok": size_ok,
        "transparent_ratio": round(transparent_ratio, 3),
        "clipping_risk": clipping_risk,
        "edge_opaque_ratio": round(edge_opaque_ratio, 3),
        "content_ratio": round(content_ratio, 3),
        "pass": size_ok and not clipping_risk and 0.03 < content_ratio < 0.95,
    }


def main():
    parser = argparse.ArgumentParser(description="이모티콘 시트 분석 및 분리")
    parser.add_argument("--sheet", help="시트 이미지 경로")
    parser.add_argument("--output-dir", default="./emoticons", help="출력 디렉토리")
    parser.add_argument("--start-index", type=int, default=1, help="시작 파일 번호")
    parser.add_argument("--expected", type=int, default=6, help="예상 이모티콘 수")
    parser.add_argument("--target-size", type=int, default=360, help="출력 크기 (기본: 360)")
    parser.add_argument("--model", default="gemini-3-pro-image-preview", help="Gemini 모델")
    parser.add_argument("--validate-only", action="store_true", help="검증만 수행")
    parser.add_argument("--rows", type=int, default=None, help="그리드 행 수 (미지정 시 Gemini로 감지)")
    parser.add_argument("--cols", type=int, default=None, help="그리드 열 수 (미지정 시 Gemini로 감지)")

    args = parser.parse_args()

    if args.validate_only:
        from glob import glob
        files = sorted(glob(os.path.join(args.output_dir, "[0-9]*.png")))
        print(f"\n🔍 {len(files)}개 파일 검증 중...")
        all_pass = True
        for f in files:
            result = validate_emoticon(f, args.target_size)
            status = "✅" if result["pass"] else "❌"
            issues = []
            if not result["size_ok"]:
                issues.append("크기 불일치")
            if result["clipping_risk"]:
                issues.append(f"잘림 위험(edge={result['edge_opaque_ratio']})")
            if result["content_ratio"] < 0.03:
                issues.append("콘텐츠 너무 작음")
            if result["content_ratio"] > 0.95:
                issues.append("콘텐츠 너무 큼")

            issue_str = f" — {', '.join(issues)}" if issues else ""
            print(f"  {status} {os.path.basename(f)}: 투명={result['transparent_ratio']:.0%}, 콘텐츠={result['content_ratio']:.0%}{issue_str}")
            if not result["pass"]:
                all_pass = False

        print(f"\n{'✅ 모든 파일 통과' if all_pass else '❌ 일부 파일 문제 있음'}")
        return

    if not args.sheet:
        print("오류: --sheet 필요 (또는 --validate-only)")
        sys.exit(1)

    # 1. 그리드 레이아웃 확인
    if args.rows and args.cols:
        rows, cols = args.rows, args.cols
        labels = [f"emoticon {i+1}" for i in range(rows * cols)]
        print(f"\n📐 수동 그리드: {rows}x{cols}")
    else:
        print(f"\n🔍 시트 분석 중: {args.sheet}")
        layout = detect_grid_layout(args.sheet, args.expected, args.model)
        rows = layout["rows"]
        cols = layout["cols"]
        labels = layout.get("labels", [])
        print(f"   감지된 레이아웃: {rows}행 x {cols}열 ({rows * cols}개)")

    # 2. 균등 분할 + 콘텐츠 감지
    print(f"\n✂️ 개별 파일 분리 중...")
    results = grid_split(
        sheet_path=args.sheet,
        rows=rows,
        cols=cols,
        labels=labels,
        output_dir=args.output_dir,
        start_index=args.start_index,
        target_size=args.target_size,
    )

    # 3. 품질 검증
    print(f"\n🔍 품질 검증 중...")
    all_pass = True
    for r in results:
        validation = validate_emoticon(r["file"], args.target_size)
        r["validation"] = validation
        status = "✅" if validation["pass"] else "❌"
        if not validation["pass"]:
            all_pass = False
            issues = []
            if validation["clipping_risk"]:
                issues.append(f"잘림(edge={validation['edge_opaque_ratio']})")
            if validation["content_ratio"] < 0.03:
                issues.append("콘텐츠 작음")
            print(f"  {status} {os.path.basename(r['file'])}: {', '.join(issues)}")
        else:
            print(f"  {status} {os.path.basename(r['file'])}")

    # 4. 결과 저장
    report_path = os.path.join(args.output_dir, "split_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({
            "sheet": args.sheet,
            "grid": f"{rows}x{cols}",
            "files_created": len(results),
            "all_pass": all_pass,
            "files": results,
        }, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n📋 리포트: {report_path}")
    print(f"{'✅ 모든 파일 통과' if all_pass else '❌ 일부 파일 문제 있음'}")

    if not all_pass:
        failed = [r for r in results if not r.get("validation", {}).get("pass", True)]
        print(f"문제 파일: {', '.join(os.path.basename(r['file']) for r in failed)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
