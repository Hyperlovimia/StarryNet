import os
from functools import lru_cache
from pathlib import Path

from fastapi import Header, HTTPException, status

from .runtime import RuntimeManager
from .store import MetadataStore


ROOT = Path(__file__).resolve().parents[4]
DATA_DIR = ROOT / "web" / "backend" / "data"
ARTIFACTS_DIR = DATA_DIR / "artifacts"
METADATA_PATH = DATA_DIR / "metadata.json"


def get_current_user_id(x_user_id: str = Header(default=None)):
    if not x_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-User-Id header is required",
        )
    return x_user_id


@lru_cache(maxsize=1)
def get_store():
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)
    return MetadataStore(str(METADATA_PATH))


@lru_cache(maxsize=1)
def get_runtime_manager():
    return RuntimeManager(get_store())
