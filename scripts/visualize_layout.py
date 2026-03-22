from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
from typing import Any


def _load_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_dp_result(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        if {"fabricWidthMm", "consumedLengthMm", "placements"}.issubset(payload.keys()):
            return payload

        data = payload.get("data")
        if isinstance(data, dict):
            return _extract_dp_result(data)

        result = payload.get("result")
        if isinstance(result, dict):
            try:
                return _extract_dp_result(result)
            except ValueError:
                pass

        if payload.get("type") == "dp_nesting" and isinstance(result, dict):
            return _extract_dp_result(result)

        for value in payload.values():
            if isinstance(value, dict):
                if value.get("type") == "dp_nesting" and isinstance(value.get("result"), dict):
                    return _extract_dp_result(value["result"])

    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict) and item.get("type") == "dp_nesting":
                return _extract_dp_result(item)

    raise ValueError("Could not find dp_nesting result in input JSON")


def _color_for_name(name: str) -> str:
    digest = hashlib.md5(name.encode("utf-8")).hexdigest()
    r = 80 + int(digest[0:2], 16) % 140
    g = 80 + int(digest[2:4], 16) % 140
    b = 80 + int(digest[4:6], 16) % 140
    return f"rgb({r},{g},{b})"


def _render_html(dp: dict[str, Any], title: str) -> str:
    fabric_w = float(dp["fabricWidthMm"])
    fabric_h = float(dp["consumedLengthMm"])
    placements = dp.get("placements", [])

    max_w = 1200.0
    max_h = 900.0
    scale = min(max_w / fabric_w, max_h / fabric_h)
    if scale <= 0:
        raise ValueError("Invalid layout dimensions")

    svg_w = fabric_w * scale
    svg_h = fabric_h * scale

    rects: list[str] = []
    labels: list[str] = []
    legend: list[str] = []

    for part in placements:
        cid = str(part.get("componentId", "unknown"))
        x = float(part.get("xMm", 0.0))
        y = float(part.get("yMm", 0.0))
        w = float(part.get("widthMm", 0.0))
        h = float(part.get("heightMm", 0.0))
        rotated = bool(part.get("rotated", False))

        fill = _color_for_name(cid)
        px = x * scale
        py = y * scale
        pw = w * scale
        ph = h * scale
        dash = "6,3" if rotated else "none"
        name = f"{cid} (R)" if rotated else cid

        rects.append(
            f"<rect class='piece' x='{px:.2f}' y='{py:.2f}' width='{pw:.2f}' height='{ph:.2f}' "
            f"fill='{fill}' fill-opacity='0.78' stroke='#1f2937' stroke-width='1.2' stroke-dasharray='{dash}'/>"
        )
        labels.append(
            f"<text class='label' x='{(px + pw / 2):.2f}' y='{(py + ph / 2):.2f}'>{name}</text>"
        )
        legend.append(f"<li><span style='background:{fill}'></span>{name} - {w:.0f} x {h:.0f} mm</li>")

    utilization = dp.get("utilization")
    utilization_text = f"{float(utilization) * 100:.2f}%" if utilization is not None else "N/A"

    return f"""<!doctype html>
<html lang='zh-CN'>
<head>
  <meta charset='utf-8'/>
  <meta name='viewport' content='width=device-width, initial-scale=1'/>
  <title>{title}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 24px; color: #111827; background: #f3f4f6; }}
    h1 {{ margin: 0 0 8px; font-size: 22px; }}
    .meta {{ margin: 0 0 16px; color: #374151; }}
    .wrap {{ display: grid; grid-template-columns: 1fr 320px; gap: 20px; align-items: start; }}
    .card {{ background: white; border-radius: 12px; box-shadow: 0 4px 20px rgba(15,23,42,.08); padding: 16px; }}
    svg {{ width: 100%; height: auto; border: 1px solid #d1d5db; border-radius: 8px; background: #fffbea; }}
    .label {{ font-size: 11px; fill: #111827; text-anchor: middle; dominant-baseline: middle; pointer-events: none; }}
    ul {{ list-style: none; padding: 0; margin: 0; max-height: 70vh; overflow: auto; }}
    li {{ display: flex; gap: 8px; align-items: center; margin: 8px 0; font-size: 13px; }}
    li span {{ width: 14px; height: 14px; border-radius: 3px; border: 1px solid #1f2937; display: inline-block; }}
    .hint {{ margin-top: 10px; color: #6b7280; font-size: 12px; }}
  </style>
</head>
<body>
  <h1>{title}</h1>
  <p class='meta'>Fabric: {fabric_w:.0f} x {fabric_h:.0f} mm | Utilization: {utilization_text} | Pieces: {len(placements)}</p>
  <div class='wrap'>
    <div class='card'>
      <svg viewBox='0 0 {svg_w:.2f} {svg_h:.2f}' xmlns='http://www.w3.org/2000/svg'>
        <rect x='0' y='0' width='{svg_w:.2f}' height='{svg_h:.2f}' fill='#fff7d6' stroke='#b45309' stroke-width='2'/>
        {''.join(rects)}
        {''.join(labels)}
      </svg>
    </div>
    <div class='card'>
      <h3 style='margin-top:0'>Components</h3>
      <ul>{''.join(legend)}</ul>
      <div class='hint'>Dashed border / (R) means rotated=true.</div>
    </div>
  </div>
</body>
</html>
"""


def _render_svg(dp: dict[str, Any]) -> str:
    fabric_w = float(dp["fabricWidthMm"])
    fabric_h = float(dp["consumedLengthMm"])
    placements = dp.get("placements", [])

    parts: list[str] = [
        f"<rect x='0' y='0' width='{fabric_w:.2f}' height='{fabric_h:.2f}' fill='#fff7d6' stroke='#b45309' stroke-width='3'/>"
    ]
    for p in placements:
        cid = str(p.get("componentId", "unknown"))
        x = float(p.get("xMm", 0.0))
        y = float(p.get("yMm", 0.0))
        w = float(p.get("widthMm", 0.0))
        h = float(p.get("heightMm", 0.0))
        rotated = bool(p.get("rotated", False))
        fill = _color_for_name(cid)
        dash = " stroke-dasharray='24,12'" if rotated else ""
        name = f"{cid} (R)" if rotated else cid
        parts.append(
            f"<rect x='{x:.2f}' y='{y:.2f}' width='{w:.2f}' height='{h:.2f}' fill='{fill}' fill-opacity='0.78' stroke='#111827' stroke-width='2'{dash}/>"
        )
        parts.append(
            f"<text x='{x + w / 2:.2f}' y='{y + h / 2:.2f}' text-anchor='middle' dominant-baseline='middle' font-size='24' fill='#111827'>{name}</text>"
        )
    return (
        "<?xml version='1.0' encoding='UTF-8'?>"
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{fabric_w:.2f}' height='{fabric_h:.2f}' viewBox='0 0 {fabric_w:.2f} {fabric_h:.2f}'>"
        + "".join(parts)
        + "</svg>"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Visualize dp_nesting placements as HTML/SVG")
    parser.add_argument("input", help="Input JSON path (dp result or action/e2e details JSON)")
    parser.add_argument("-o", "--output", help="Output path (default: layout.html beside input)")
    parser.add_argument("--format", choices=["html", "svg"], default="html", help="Output format")
    parser.add_argument("--title", default="DP Nesting Layout", help="Document title")
    args = parser.parse_args()

    input_path = pathlib.Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")

    payload = _load_json(input_path)
    dp_result = _extract_dp_result(payload)

    if args.output:
        output_path = pathlib.Path(args.output)
    else:
        ext = ".svg" if args.format == "svg" else ".html"
        output_path = input_path.with_name("layout" + ext)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if args.format == "svg":
        output = _render_svg(dp_result)
    else:
        output = _render_html(dp_result, args.title)

    output_path.write_text(output, encoding="utf-8")
    print(json.dumps({
        "input": str(input_path),
        "output": str(output_path),
        "fabricWidthMm": dp_result.get("fabricWidthMm"),
        "consumedLengthMm": dp_result.get("consumedLengthMm"),
        "pieceCount": len(dp_result.get("placements", [])),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
