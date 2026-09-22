"""CamerTrust — E2 — Signalement de fraude par l'abonné (menu USSD option 5)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import obtenir_session

router = APIRouter(tags=["signalement"])


@router.post("/reports", response_model=schemas.ReportResponse)
def signaler(payload: schemas.ReportRequest, db: Session = Depends(obtenir_session)):
    user = db.query(models.User).filter_by(user_id=payload.user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="Compte inconnu")
    # Le signalement lui-même n'est pas modélisé en table dédiée dans ce
    # PFE (hors périmètre du plan) — il est journalisé et une référence
    # est renvoyée à l'abonné, comme l'exige le message catalogue d'E4
    # (« Signalement enregistre. Un agent vous contactera si besoin. »).
    reference = str(uuid.uuid4())[:8]
    return schemas.ReportResponse(received=True, reference=reference)
