import os


def get_env_float(key: str, default: float = 0.0) -> float:
    """환경변수를 float로 변환."""
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def get_env_int(key: str, default: int = 0) -> int:
    """환경변수를 int로 변환."""
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default
