"""Collision-safe names for workshop resources.

The deployment emits ``WORKSHOP_RESOURCE_NAMESPACE`` for every team. Explicit
environment variables always win so production-style deployments can keep
their established names.
"""
from __future__ import annotations

import os
import re
from hashlib import sha256

from utils.environment import load_workshop_environment

load_workshop_environment()


def workshop_namespace() -> str:
    """Return a lowercase Azure-resource-safe workshop namespace."""
    raw = os.getenv("WORKSHOP_RESOURCE_NAMESPACE", "")
    normalized = re.sub(r"[^a-z0-9-]+", "-", raw.strip().lower()).strip("-")
    if raw.strip() and not normalized:
        raise ValueError(
            "WORKSHOP_RESOURCE_NAMESPACE must contain a letter or digit"
        )
    if len(normalized) <= 24:
        return normalized
    digest = sha256(raw.strip().encode("utf-8")).hexdigest()[:6]
    prefix = normalized[:17].rstrip("-")
    return f"{prefix}-{digest}"


def scoped_name(base: str, env_var: str) -> str:
    """Resolve an explicit name or append the current workshop namespace."""
    explicit = os.getenv(env_var)
    if explicit:
        return explicit
    namespace = workshop_namespace()
    return f"{base}-{namespace}" if namespace else base
