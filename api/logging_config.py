"""CamerTrust — E2 — Journalisation (plan p.8, S8 : `api/logs/app.log`)."""

from __future__ import annotations

import logging
import os
from pathlib import Path

DOSSIER_LOGS = Path(__file__).resolve().parent / "logs"


def configurer_logging() -> None:
    DOSSIER_LOGS.mkdir(exist_ok=True)
    niveau = os.environ.get("LOG_LEVEL", "INFO")
    logging.basicConfig(
        level=niveau,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(DOSSIER_LOGS / "app.log"),
            logging.StreamHandler(),
        ],
    )
