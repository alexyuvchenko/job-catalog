from pathlib import Path


def _project_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    raise RuntimeError("Could not find pyproject.toml above the package")


ROOT = _project_root()
DATA_DIR = ROOT / "data"
OUT_DIR = ROOT / "out"
CACHE_PATH = DATA_DIR / "cache.sqlite"
CATALOG_PATH = DATA_DIR / "catalog.sqlite"
