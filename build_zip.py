"""
Build a clean install ZIP for the BeMatrix Blender add-on.

The ZIP contains the top-level bematrix_addon/ package folder, not the whole
repository. Run from the repo root:

    python build_zip.py
"""

from __future__ import annotations

import ast
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ADDON_DIR = ROOT / "bematrix_addon"
DIST_DIR = ROOT / "dist"
ZIP_BASENAME = "bematrix_blender_tools"

EXCLUDED_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".vscode",
    "dist",
}

EXCLUDED_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".bak",
    ".swp",
    ".swo",
    ".tmp",
}


def read_bl_info_version() -> str:
    init_path = ADDON_DIR / "__init__.py"
    try:
        module = ast.parse(init_path.read_text(encoding="utf-8"))
    except OSError:
        return "0.0.0"

    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "bl_info":
                    try:
                        bl_info = ast.literal_eval(node.value)
                    except (ValueError, SyntaxError):
                        return "0.0.0"
                    version = bl_info.get("version", (0, 0, 0))
                    return ".".join(str(part) for part in version)

    return "0.0.0"


def should_exclude(path: Path) -> bool:
    parts = set(path.parts)
    if parts.intersection(EXCLUDED_DIRS):
        return True

    name = path.name
    if name.endswith("~") or name.startswith(".#"):
        return True
    if ".tmp." in name:
        return True
    if path.suffix.lower() in EXCLUDED_SUFFIXES:
        return True

    return False


def build_zip() -> Path:
    if not ADDON_DIR.is_dir():
        raise FileNotFoundError(f"Add-on folder not found: {ADDON_DIR}")
    if not (ADDON_DIR / "__init__.py").is_file():
        raise FileNotFoundError(f"Add-on __init__.py not found: {ADDON_DIR / '__init__.py'}")

    version = read_bl_info_version()
    DIST_DIR.mkdir(exist_ok=True)

    zip_path = DIST_DIR / f"{ZIP_BASENAME}_v{version}.zip"
    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(ADDON_DIR.rglob("*")):
            relative_to_root = path.relative_to(ROOT)
            if should_exclude(relative_to_root):
                continue
            if path.is_dir():
                continue
            archive.write(path, relative_to_root.as_posix())

    return zip_path


def main() -> None:
    zip_path = build_zip()
    print(f"Created {zip_path}")


if __name__ == "__main__":
    main()
