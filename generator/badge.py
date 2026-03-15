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

    lw = label_width
    sw = status_width
    tw = total_width
    font = "Verdana,Geneva,DejaVu Sans,sans-serif"
    shadow = 'fill="#010101" fill-opacity=".3"'

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{tw}" height="20"'
        f' role="img" aria-label="{label}: {status}">\n'
        f"  <title>{label}: {status}</title>\n"
        f'  <linearGradient id="s" x2="0" y2="100%">\n'
        f'    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>\n'
        f'    <stop offset="1" stop-opacity=".1"/>\n'
        f"  </linearGradient>\n"
        f'  <clipPath id="r">\n'
        f'    <rect width="{tw}" height="20" rx="3" fill="#fff"/>\n'
        f"  </clipPath>\n"
        f'  <g clip-path="url(#r)">\n'
        f'    <rect width="{lw}" height="20" fill="#555"/>\n'
        f'    <rect x="{lw}" width="{sw}" height="20" fill="{color}"/>\n'
        f'    <rect width="{tw}" height="20" fill="url(#s)"/>\n'
        f"  </g>\n"
        f'  <g fill="#fff" text-anchor="middle" font-family="{font}"'
        f' text-rendering="geometricPrecision" font-size="11">\n'
        f'    <text aria-hidden="true" x="{lw / 2}" y="15"'
        f" {shadow}>{label}</text>\n"
        f'    <text x="{lw / 2}" y="14">{label}</text>\n'
        f'    <text aria-hidden="true" x="{lw + sw / 2}" y="15"'
        f" {shadow}>{status}</text>\n"
        f'    <text x="{lw + sw / 2}" y="14">{status}</text>\n'
        f"  </g>\n"
        f"</svg>"
    )


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
