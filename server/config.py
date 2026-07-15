"""Server configuration, loaded once from the environment. Fails fast."""
import os
import sys
from dataclasses import dataclass


def _as_bool(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    token: str
    db_path: str
    host: str
    port: int
    protect_reads: bool
    on_unknown_target: str  # "reject" | "ignore"


def load() -> Settings:
    token = os.environ.get("IDEAL_TOKEN", "").strip()
    if not token:
        print(
            "FATAL: IDEAL_TOKEN is required (set it in .env). Refusing to start "
            "with no access control.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    on_unknown = os.environ.get("IDEAL_ON_UNKNOWN_TARGET", "reject").strip().lower()
    if on_unknown not in ("reject", "ignore"):
        on_unknown = "reject"

    return Settings(
        token=token,
        db_path=os.environ.get("IDEAL_DB_PATH", "/data/ideal.sqlite"),
        host=os.environ.get("IDEAL_HOST", "0.0.0.0"),
        port=int(os.environ.get("IDEAL_PORT", "8000")),
        protect_reads=_as_bool(os.environ.get("IDEAL_PROTECT_READS", "true")),
        on_unknown_target=on_unknown,
    )


settings = load()
