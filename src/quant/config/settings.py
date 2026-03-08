# src\quant\config\settings.py

from __future__ import annotations

from dataclasses import dataclass
import os

from dotenv import load_dotenv

# 프로젝트 루트의 .env 자동 로드
load_dotenv()


@dataclass(frozen=True)
class Settings:
    env: str = os.getenv("ENV", "dev")
    timezone: str = os.getenv("TZ", "UTC")

    # Binance (실거래)
    binance_api_key: str = os.getenv("BINANCE_API_KEY", "")
    binance_api_secret: str = os.getenv("BINANCE_API_SECRET", "")

    # Runtime
    data_dir: str = os.getenv("DATA_DIR", "data")
    results_dir: str = os.getenv("RESULTS_DIR", "result")

    # Logs
    log_dir: str = os.getenv("QUANT_LOG_DIR", os.path.join(results_dir, "logs"))


def load_settings() -> Settings:
    return Settings()
