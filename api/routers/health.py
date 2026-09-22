"""CamerTrust — E2 — Santé du service (plan p.7, S2)."""

from __future__ import annotations

from fastapi import APIRouter

from .. import scoring

router = APIRouter(tags=["santé"])


@router.get("/health")
def sante():
    return {"status": "ok"}


@router.get("/info")
def info():
    return {
        "service": "CamerTrust API",
        "modele_charge": scoring.modele_disponible(),
        "seuil": scoring.MODEL_INFO.get("threshold") if scoring.MODEL_INFO else None,
    }
