"""Sample dataset locations. Works natively (cwd=apps/api), in Docker
(/srv with ./samples mounted), and in tests (cwd=repo root).

Resolution order: $SAMPLES_DIR, ./samples, /srv/samples, repo-root/samples.
"""
from __future__ import annotations
import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]  # app/services/samples.py -> services -> app -> api -> apps -> root
_CANDIDATES = [
    os.environ.get("SAMPLES_DIR", ""),
    "samples",
    "/srv/samples",
    str(_REPO_ROOT / "samples"),
]


def sample_root() -> Path:
    for c in _CANDIDATES:
        if c and Path(c).is_dir():
            return Path(c)
    raise FileNotFoundError(
        "samples directory not found (checked $SAMPLES_DIR, ./samples, "
        "/srv/samples, repo-root/samples)")


def sample_files(business: str) -> list[str]:
    """CSV filenames for a catalog business (empty when seed-only)."""
    from . import seed as seedsvc
    key = (business or "").lower()
    spec = seedsvc.BUSINESS_SEEDS.get(key)
    if not spec:
        raise ValueError(f"unknown business '{business}'")
    try:
        root = sample_root()
    except FileNotFoundError:
        return []
    sdir = spec.get("sample_dir")
    if sdir:
        d = root / sdir
        if not d.is_dir():
            return []
        return sorted([f.name for f in d.iterdir() if f.suffix == ".csv"])
    if key == "manufacturing":
        return sorted([f.name for f in root.iterdir()
                       if f.is_file() and f.suffix in (".csv", ".json")])
    return []


def sample_paths(business: str) -> list[str]:
    """Absolute CSV paths for load-sample. Raises 404-style FileNotFoundError."""
    from . import seed as seedsvc
    key = (business or "").lower()
    spec = seedsvc.BUSINESS_SEEDS.get(key)
    if not spec:
        raise ValueError(f"unknown business '{business}'")
    root = sample_root()
    sdir = spec.get("sample_dir")
    if sdir:
        d = root / sdir
        if not d.is_dir():
            raise FileNotFoundError(f"sample dir missing: {d}")
        paths = sorted([str(f) for f in d.iterdir() if f.suffix == ".csv"])
    elif key == "manufacturing":
        paths = sorted([str(f) for f in root.iterdir()
                        if f.is_file() and f.suffix == ".csv"])
    else:
        raise ValueError(f"no sample files for '{business}'")
    if not paths:
        raise FileNotFoundError(f"no sample CSVs for '{business}' in {root}")
    return paths
