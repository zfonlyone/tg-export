"""
Simple .env persistence helpers.
"""
from pathlib import Path
from typing import Dict

from ..config import settings


RUNTIME_ENV_FILE = settings.RUNTIME_ENV_FILE


def upsert_env_values(values: Dict[str, str]) -> None:
    """Upsert key/value pairs into the writable runtime env file."""
    RUNTIME_ENV_FILE.parent.mkdir(parents=True, exist_ok=True)

    existing: Dict[str, str] = {}
    if RUNTIME_ENV_FILE.exists():
        for raw in RUNTIME_ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            existing[k.strip()] = v

    for k, v in values.items():
        if v is None:
            continue
        existing[k] = str(v)

    lines = [f"{k}={v}" for k, v in existing.items()]
    RUNTIME_ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
