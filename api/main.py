"""
CamerTrust — E2 — Application FastAPI (point d'entrée)
==========================================================

Assemble toutes les routes du service — voir le tableau « Référence
rapide » du plan (p.9) et le README à la racine du projet pour le détail
de chaque endpoint et la façon dont E1 et E3 s'y raccrochent.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .database import creer_tables
from .logging_config import configurer_logging
from .routers import admin, alerts, health, outbox, reports, sms, transactions, ussd, users

configurer_logging()
logger = logging.getLogger("camertrust.api")

app = FastAPI(
    title="CamerTrust API",
    description="Service anti-fraude exploitable depuis le terminal de l'abonné — projet SUP'PTIC 2023-2026.",
    version="1.0.0",
)

for routeur in (health, users, transactions, alerts, ussd, sms, reports, outbox, admin):
    app.include_router(routeur.router)


@app.on_event("startup")
def au_demarrage() -> None:
    creer_tables()
    logger.info("CamerTrust API démarrée.")


@app.exception_handler(Exception)
async def gestionnaire_erreurs_global(request: Request, exc: Exception):
    """Mode dégradé (plan p.8, S8) : une erreur inattendue ne doit jamais
    faire planter tout le service — elle est journalisée et renvoyée
    comme une 500 propre, jamais comme une trace Python brute."""
    logger.exception("Erreur non gérée sur %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Erreur interne — voir api/logs/app.log"})
