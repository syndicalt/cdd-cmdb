"""Compliance badge generator.

After passing a profile's test suite, generates:
- An SVG badge showing the compliance tier
- A markdown snippet for embedding in READMEs
"""
from __future__ import annotations

import time
from pathlib import Path


# Color scheme per profile
_COLORS = {
    "minimal": "#4c1",       # green
    "standard": "#0779e4",   # blue
    "enterprise": "#9b59b6", # purple
}

_LABELS = {
    "minimal": "CMDB Minimal",
    "standard": "CMDB Standard",
    "enterprise": "CMDB Enterprise",
}


def _svg_badge(label: str, status: str, color: str) -> str:
    """Generate a shields.io-style SVG badge."""
    label_width = len(label) * 6.5 + 12
    status_width = len(status) * 6.5 + 12
    total_width = label_width + status_width

    return f"""\
<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="20" role="img" aria-label="{label}: {status}">
  <title>{label}: {status}</title>
  <linearGradient id="s" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="r">
    <rect width="{total_width}" height="20" rx="3" fill="#fff"/>
  </clipPath>
  <g clip-path="url(#r)">
    <rect width="{label_width}" height="20" fill="#555"/>
    <rect x="{label_width}" width="{status_width}" height="20" fill="{color}"/>
    <rect width="{total_width}" height="20" fill="url(#s)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" text-rendering="geometricPrecision" font-size="11">
    <text aria-hidden="true" x="{label_width / 2}" y="15" fill="#010101" fill-opacity=".3">{label}</text>
    <text x="{label_width / 2}" y="14">{label}</text>
    <text aria-hidden="true" x="{label_width + status_width / 2}" y="15" fill="#010101" fill-opacity=".3">{status}</text>
    <text x="{label_width + status_width / 2}" y="14">{status}</text>
  </g>
</svg>"""


def generate_badge(
    profile: str,
    passed: int,
    total: int,
    output_dir: Path | None = None,
) -> tuple[str, str]:
    """Generate a compliance badge.

    Args:
        profile: The compliance profile (minimal/standard/enterprise)
        passed: Number of tests passed
        total: Total number of tests
        output_dir: Where to write badge files. If None, returns content only.

    Returns:
        (svg_content, markdown_snippet)
    """
    all_passed = passed == total
    label = _LABELS.get(profile, f"CMDB {profile.title()}")
    status = "passing" if all_passed else f"{passed}/{total}"
    color = _COLORS.get(profile, "#4c1") if all_passed else "#e05d44"  # red for failing

    svg = _svg_badge(label, status, color)
    date_str = time.strftime("%Y-%m-%d")

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)

        svg_path = output_dir / f"badge-{profile}.svg"
        svg_path.write_text(svg, encoding="utf-8")

        # Also write a summary JSON
        summary = {
            "profile": profile,
            "passed": passed,
            "total": total,
            "compliant": all_passed,
            "date": date_str,
        }
        import json
        summary_path = output_dir / f"compliance-{profile}.json"
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    # Markdown snippet — works with relative path or as inline SVG
    if output_dir:
        md = f"![{label} {status}](badge-{profile}.svg)"
    else:
        # Inline data URI approach
        import base64
        b64 = base64.b64encode(svg.encode()).decode()
        md = f"![{label} {status}](data:image/svg+xml;base64,{b64})"

    return svg, md


def generate_all_badges(
    results: dict[str, tuple[int, int]],
    output_dir: Path,
) -> str:
    """Generate badges for multiple profiles.

    Args:
        results: {profile: (passed, total)} dict
        output_dir: Where to write badge files

    Returns:
        Markdown snippet showing all badges
    """
    snippets: list[str] = []
    for profile, (passed, total) in sorted(results.items()):
        _, md = generate_badge(profile, passed, total, output_dir)
        snippets.append(md)

    return " ".join(snippets)
