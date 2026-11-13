"""Build a review-installable ZIP containing only the custom integration."""

from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def main() -> None:
    """Package source/resources, excluding bytecode and local configuration."""
    root = Path(__file__).resolve().parents[1]
    component = root / "custom_components" / "samvev"
    manifest = json.loads((component / "manifest.json").read_text())
    if manifest["domain"] != "samvev":
        raise ValueError("Unexpected integration domain")
    target = root / "dist" / f"samvev-homeassistant-{manifest['version']}.zip"
    target.parent.mkdir(exist_ok=True)
    with ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(component.rglob("*")):
            if (
                path.is_file()
                and "__pycache__" not in path.parts
                and path.suffix in {".py", ".json", ".yaml"}
            ):
                archive.write(path, path.relative_to(root))
    print(target.name)  # noqa: T201 -- CLI output contains only the artifact name.


if __name__ == "__main__":
    main()
