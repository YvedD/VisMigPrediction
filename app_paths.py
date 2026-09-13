from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def project_root() -> Path:
    return Path(__file__).resolve().parent


def project_path(*parts: str) -> Path:
    return project_root().joinpath(*parts)
