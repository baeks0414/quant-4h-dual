from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class JsonLineFileHandler(logging.Handler):
    """
    메시지를 한 줄 JSON으로 파일에 기록합니다.
    - 운영에서 "주문 실패 원인 100% 로그화"에 사용.
    """
    def __init__(self, path: str):
        super().__init__(level=logging.INFO)
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.msg
            if isinstance(msg, dict):
                payload = msg
            else:
                payload = {"message": str(msg)}
            payload.setdefault("ts", _utc_iso())
            payload.setdefault("level", record.levelname)
            line = json.dumps(payload, ensure_ascii=False)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            # 로깅 실패는 프로그램을 죽이지 않음
            pass


def get_logger(name: str, log_dir: str, file_stem: str) -> logging.Logger:
    """
    콘솔(가독) + 파일(JSONL) 동시 로깅.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False

    # Console handler (human-friendly)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("[%(asctime)s][%(levelname)s] %(message)s"))
    logger.addHandler(ch)

    # File handler (jsonl)
    path = os.path.join(log_dir, f"{file_stem}.jsonl")
    fh = JsonLineFileHandler(path)
    logger.addHandler(fh)

    return logger


def jlog(
    logger: logging.Logger,
    event: str,
    payload: Optional[Dict[str, Any]] = None,
    level: str = "info",
) -> None:
    d: Dict[str, Any] = {"event": event}
    if payload:
        d.update(payload)

    if level.lower() == "error":
        logger.error(d)
    elif level.lower() == "warning":
        logger.warning(d)
    else:
        logger.info(d)
