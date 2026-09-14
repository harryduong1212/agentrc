#!/usr/bin/env python3
"""Add OmniRoute combo ids to Codex's current model catalog."""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path


POOLS = (
    ("codex-pool-sol", "gpt-5.6-sol", "Codex Pool Sol"),
    ("codex-pool-luna", "gpt-5.6-luna", "Codex Pool Luna"),
    ("codex-pool-terra", "gpt-5.6-terra", "Codex Pool Terra"),
)


def _load_codex_catalog(codex: str) -> dict[str, object]:
    result = subprocess.run(
        [codex, "debug", "models", "--bundled"],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    catalog = json.loads(result.stdout)
    if not isinstance(catalog.get("models"), list):
        raise ValueError("codex debug models returned no models array")
    return catalog


def build(catalog: dict[str, object]) -> dict[str, object]:
    models = catalog["models"]
    assert isinstance(models, list)
    by_slug = {model["slug"]: model for model in models}
    custom = []
    for priority, (pool, source, display_name) in enumerate(POOLS, start=1):
        if source not in by_slug:
            raise ValueError(f"Codex catalog does not contain {source}")
        model = copy.deepcopy(by_slug[source])
        model.update(
            slug=pool,
            display_name=display_name,
            description=f"OmniRoute pool backed by {source}.",
            priority=priority,
            visibility="list",
        )
        custom.append(model)

    custom_slugs = {pool for pool, _, _ in POOLS}
    return {**catalog, "models": custom + [m for m in models if m["slug"] not in custom_slugs]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codex", default="codex")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    temporary: Path | None = None
    try:
        catalog = build(_load_codex_catalog(args.codex))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        rendered = json.dumps(catalog, indent=2) + "\n"
        with tempfile.NamedTemporaryFile(
            "w", dir=args.output.parent, prefix=f".{args.output.name}.", delete=False
        ) as handle:
            handle.write(rendered)
            temporary = Path(handle.name)
        temporary.replace(args.output)
    except (OSError, subprocess.CalledProcessError, ValueError, json.JSONDecodeError) as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
