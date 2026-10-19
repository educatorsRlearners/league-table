#!/usr/bin/env python3
"""Fail if a test compose override publishes a host port the dev stack publishes.

Uses only `docker compose config` output (no containers, no free host ports
needed). Usage: check-compose-ports.py [override.yml ...]
Defaults to the integration and e2e overrides.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "docker-compose.yml"
DEFAULT_OVERRIDES = [
    ROOT / "docker-compose.integration.yml",
    ROOT / "docker-compose.e2e.yml",
]


def published(*files: Path) -> set[str]:
    cmd = ["docker", "compose"]
    for f in files:
        cmd += ["-f", str(f)]
    cmd += ["config", "--format", "json"]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    services = json.loads(out).get("services", {})
    return {
        str(p["published"])
        for svc in services.values()
        for p in svc.get("ports", [])
        if p.get("published")
    }


def main(argv: list[str]) -> int:
    overrides = [Path(a) for a in argv] or DEFAULT_OVERRIDES
    base_ports = published(BASE)
    failed = False
    for override in overrides:
        clash = sorted(published(BASE, override) & base_ports)
        if clash:
            failed = True
            print(
                f"FAIL {override.name} still publishes dev-stack host "
                f"port(s): {', '.join(clash)}",
                file=sys.stderr,
            )
        else:
            print(f"ok   {override.name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
