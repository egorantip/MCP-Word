"""Create source/portable ZIPs without user documents, keys or logs."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile


SOURCE_ITEMS = ["word_mcp", "scripts", "tests", "docs", "README.md", "LICENSE", "Start.vbs",
                "Start.bat", "portable.json", "requirements.lock.txt", "pyproject.toml", ".gitignore", ".gitattributes"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--split-mib", type=int, default=0)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    destination = root / "dist"
    destination.mkdir(exist_ok=True)
    filename = "MCP-Word-offline.zip" if args.offline else "MCP-Word-setup.zip"
    archive = destination / filename
    items = SOURCE_ITEMS + (["runtime", "models"] if args.offline else [])
    if args.offline and not (root / "runtime" / "prepared.json").exists():
        raise ValueError("Prepare the portable runtime and models before making an offline archive")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as output:
        for item in items:
            path = root / item
            if not path.exists():
                continue
            paths = path.rglob("*") if path.is_dir() else [path]
            for file in paths:
                if not file.is_file():
                    continue
                relative = file.relative_to(root)
                if any(part in {"__pycache__", ".pytest_cache", "user", "tmp", "pip-cache"} for part in relative.parts):
                    continue
                if file.suffix in {".pyc", ".partial", ".log"}:
                    continue
                if str(relative).replace("\\", "/") in {"runtime/python.zip", "runtime/ollama.zip", "runtime/get-pip.py"}:
                    continue
                output.write(file, "MCP Word/" + relative.as_posix())
    if args.split_mib:
        if args.split_mib < 1:
            raise ValueError("Split size must be positive")
        parts = []
        with archive.open("rb") as source:
            index = 1
            while True:
                first = source.read(1024 * 1024)
                if not first:
                    break
                name = f"{filename}.part{index:03d}"
                remaining = args.split_mib * 1024 * 1024
                digest = hashlib.sha256()
                length = 0
                with (destination / name).open("wb") as part:
                    data = first
                    while data:
                        part.write(data)
                        digest.update(data)
                        length += len(data)
                        remaining -= len(data)
                        if not remaining:
                            break
                        data = source.read(min(1024 * 1024, remaining))
                parts.append({"name": name, "bytes": length, "sha256": digest.hexdigest()})
                index += 1
        (destination / f"{filename}.parts.json").write_text(json.dumps(parts, indent=2), encoding="utf-8")
    with archive.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    (destination / f"{filename}.sha256").write_text(digest + "  " + filename + "\n", encoding="ascii")
    print(archive)


if __name__ == "__main__":
    main()
