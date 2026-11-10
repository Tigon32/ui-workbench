"""Validation and bounded settings for rendered target profiles."""

import hashlib
import json
from pathlib import Path


DEFAULT_WIDTHS = {
    "mobile": 390,
    "tablet": 768,
    "laptop": 1280,
    "desktop": 1920,
    "wide": 2560,
}
PROFILE_NAMES = tuple(DEFAULT_WIDTHS)
MAX_TEXT_EXPANSION = 3.0
MAX_MOTION_MS = 10_000


class RubricError(ValueError):
    """A rubric contains unsupported or invalid rendered-check settings."""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RubricError(f"duplicate JSON key in rubric: {key}")
        result[key] = value
    return result


def load_rubric(path):
    """Load, validate, and hash one shared renderer rubric."""
    path = Path(path)
    try:
        raw = path.read_bytes()
        rubric = json.loads(raw, object_pairs_hook=_unique_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RubricError(f"cannot read rubric {path}: {error}") from error
    if not isinstance(rubric, dict):
        raise RubricError("rubric must be a JSON object")
    if "renderer" in rubric and rubric["renderer"] != "web":
        raise RubricError("only renderer 'web' is supported; native rendering is unavailable")

    platforms = rubric.get("target_platforms")
    if not isinstance(platforms, dict) or set(platforms) != set(PROFILE_NAMES):
        raise RubricError(
            "target_platforms must contain exactly mobile, tablet, laptop, desktop, and wide"
        )
    if any(type(value) is not bool for value in platforms.values()):
        raise RubricError("target_platforms values must be booleans")
    enabled = [name for name in PROFILE_NAMES if platforms[name]]
    if not enabled:
        raise RubricError("at least one target platform must be enabled")
    decision = rubric.get("target_platform_decision")
    if not isinstance(decision, str) or not decision.strip():
        raise RubricError("target_platform_decision must be a nonempty string")

    widths = dict(DEFAULT_WIDTHS)
    overrides = rubric.get("target_widths", {})
    if not isinstance(overrides, dict):
        raise RubricError("target_widths must be an object")
    for name, width in overrides.items():
        if name not in PROFILE_NAMES or name not in enabled:
            raise RubricError(f"target_widths may only override enabled profiles: {name}")
        if type(width) is not int or not 320 <= width <= 7680:
            raise RubricError(f"target_widths.{name} must be an integer from 320 to 7680")
        widths[name] = width

    quality = _validate_quality(rubric.get("quality_checks", {}))
    zoom = (_validate_desktop_zoom(rubric["desktop_zoom"], platforms)
            if "desktop_zoom" in rubric else None)
    digest = hashlib.sha256(raw).hexdigest()
    result = {
        "digest": digest,
        "decision": decision.strip(),
        "profiles": {name: widths[name] for name in enabled},
        "widths": list(dict.fromkeys(widths[name] for name in enabled)),
        "reflow_width": 320,
        "reflow_label": "zoom/reflow (not phone)",
        "quality_checks": quality,
    }
    if zoom is not None:
        result["desktop_zoom"] = zoom
    return result


def _validate_desktop_zoom(value, platforms):
    if not isinstance(value, dict) or set(value) - {"percentages"}:
        raise RubricError("desktop_zoom must contain only percentages")
    percentages = value.get("percentages", [])
    if not isinstance(percentages, list) or len(percentages) > 10:
        raise RubricError("desktop_zoom.percentages must be a list of at most 10 zoom values")
    if percentages and not platforms["desktop"]:
        raise RubricError("desktop_zoom requires the desktop target profile")
    if (any(type(item) is not int or not 100 <= item <= 300 for item in percentages)
            or len(set(percentages)) != len(percentages)
            or percentages != sorted(percentages)
            or (percentages and (percentages[0] != 100 or len(percentages) < 2))):
        raise RubricError(
            "desktop_zoom.percentages must contain 100 and at least one intermediate zoom, "
            "as unique ascending integers from 100 to 300"
        )
    result = {
        "percentages": percentages,
        "evidence_type": "real_browser_zoom",
        "status": "unavailable" if percentages else "not_declared",
        "reason": ("The bundled renderer does not control or verify browser zoom."
                   if percentages else "No real-browser zoom percentages were declared."),
    }
    return result


def _validate_quality(value):
    if not isinstance(value, dict):
        raise RubricError("quality_checks must be an object")
    allowed = {
        "semantic_control_parity",
        "reduced_motion_max_ms",
        "typography_scale_px",
        "spacing_scale_px",
        "text_expansion_factor",
    }
    unknown = set(value) - allowed
    if unknown:
        raise RubricError(f"unsupported quality_checks key(s): {', '.join(sorted(unknown))}")
    result = {}
    if "semantic_control_parity" in value:
        if type(value["semantic_control_parity"]) is not bool:
            raise RubricError("quality_checks.semantic_control_parity must be a boolean")
        result["semantic_control_parity"] = value["semantic_control_parity"]
    if "reduced_motion_max_ms" in value:
        amount = value["reduced_motion_max_ms"]
        if type(amount) is not int or not 0 <= amount <= MAX_MOTION_MS:
            raise RubricError(
                f"quality_checks.reduced_motion_max_ms must be an integer from 0 to {MAX_MOTION_MS}"
            )
        result["reduced_motion_max_ms"] = amount
    for key, maximum in (("typography_scale_px", 256), ("spacing_scale_px", 512)):
        if key in value:
            scale = value[key]
            minimum = 0 if key == "spacing_scale_px" else 1
            if (not isinstance(scale, list) or not scale or len(scale) > 32
                    or any(type(item) is not int or not minimum <= item <= maximum for item in scale)
                    or len(set(scale)) != len(scale)):
                raise RubricError(
                    f"quality_checks.{key} must be a nonempty list of unique bounded integers"
                )
            result[key] = sorted(scale)
    if "text_expansion_factor" in value:
        factor = value["text_expansion_factor"]
        if type(factor) not in (int, float) or not 1 < factor <= MAX_TEXT_EXPANSION:
            raise RubricError(
                f"quality_checks.text_expansion_factor must be greater than 1 and at most "
                f"{MAX_TEXT_EXPANSION}"
            )
        result["text_expansion_factor"] = float(factor)
    return result


def metadata(profiles):
    """Return stable, explicit profile fields suitable for round metadata."""
    result = {
        "decision": profiles["decision"],
        "profiles": profiles["profiles"],
        "widths": profiles["widths"],
        "reflow": {
            "width": profiles["reflow_width"],
            "label": profiles["reflow_label"],
        },
        "quality_checks": profiles["quality_checks"],
    }
    if "desktop_zoom" in profiles:
        result["desktop_zoom"] = profiles["desktop_zoom"]
    return result
