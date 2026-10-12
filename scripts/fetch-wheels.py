"""Download a fully pinned wheel set using Windows curl and verify PyPI SHA256."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from pip._vendor.packaging.requirements import Requirement
from pip._vendor.packaging.tags import sys_tags
from pip._vendor.packaging.utils import parse_wheel_filename


def curl(url: str, destination: Path):
    subprocess.run(["curl.exe", "--fail", "--location", "--retry", "3", "--connect-timeout", "30",
                    "--ssl-revoke-best-effort", "--silent", "--show-error", "--output", str(destination), url], check=True)


def main():
    root = Path(__file__).resolve().parent.parent
    wheelhouse = root / "runtime" / "wheels"
    wheelhouse.mkdir(parents=True, exist_ok=True)
    tags = list(sys_tags())
    rankings = {tag: i for i, tag in enumerate(tags)}
    for line in (root / "requirements.lock.txt").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        requirement = Requirement(line)
        if requirement.marker and not requirement.marker.evaluate():
            continue
        version = str(requirement.specifier).removeprefix("==")
        metadata = root / "runtime" / "tmp" / f"{requirement.name}-{version}.json"
        curl(f"https://pypi.org/pypi/{requirement.name}/{version}/json", metadata)
        info = json.loads(metadata.read_text(encoding="utf-8"))
        candidates = []
        for entry in info["urls"]:
            if entry["packagetype"] != "bdist_wheel" or entry.get("yanked"):
                continue
            _, _, _, wheel_tags = parse_wheel_filename(entry["filename"])
            matches = [rankings[tag] for tag in wheel_tags if tag in rankings]
            if matches:
                candidates.append((min(matches), entry))
        if not candidates:
            raise RuntimeError(f"No compatible Windows wheel for {requirement}")
        entry = min(candidates, key=lambda value: value[0])[1]
        if Path(entry["filename"]).name != entry["filename"]:
            raise RuntimeError("Invalid wheel filename")
        destination = wheelhouse / entry["filename"]
        expected = entry["digests"]["sha256"]
        if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() == expected:
            print("Cached:", destination.name, flush=True)
            continue
        temporary = destination.with_suffix(".partial")
        print("Downloading:", destination.name, flush=True)
        curl(entry["url"], temporary)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != expected:
            raise RuntimeError("Wheel checksum mismatch: " + entry["filename"])
        temporary.replace(destination)


if __name__ == "__main__":
    main()
