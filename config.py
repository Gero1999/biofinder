"""Load optional local dotenv configuration without evaluating shell expressions."""

import os
from pathlib import Path
import re
import shlex

ALLOWED = {
    "OPENAI_API_KEY",
    "BIOFINDER_MODEL",
    "BRAVE_SEARCH_API_KEY",
    "BIOFINDER_ALLOWED_HOSTS",
    "BIOFINDER_PUBLIC_TERMS",
    "BIOFINDER_REQUEST_LIMIT",
    "BIOFINDER_MODEL_CALL_LIMIT",
}


def load_env(path=Path(".env")):
    path = Path(path)
    if not path.exists():
        return
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"(?:export\s+)?([A-Z_][A-Z0-9_]*)\s*=\s*(.*)", line)
        if not match or match[1] not in ALLOWED:
            raise ValueError(f"Unsupported configuration at line {number}")
        try:
            parts = shlex.split(match[2], comments=True, posix=True)
        except ValueError:
            raise ValueError(f"Invalid quoted configuration at line {number}") from None
        if len(parts) > 1:
            raise ValueError(f"Quote configuration containing spaces at line {number}")
        # Existing injected environment wins; values are never printed or executed.
        os.environ.setdefault(match[1], parts[0] if parts else "")


def csv_setting(name):
    return [
        value.strip() for value in os.environ.get(name, "").split(",") if value.strip()
    ]
