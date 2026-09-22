"""
CamerTrust — E2 — Réponse par SMS direct (canal alternatif à l'USSD)
========================================================================

Le tableau de référence du plan (p.9) note que `POST /alerts/{id}/respond`
est appelable « par SMS retour, USSD, mini-app ». Ce endpoint est le point
d'entrée pour le cas SMS : l'abonné répond directement « 1 » ou « 2 » au
SMS d'alerte reçu, sans repasser par le menu USSD ni connaître l'identifiant
technique de l'alerte. On retrouve sa dernière alerte en attente et on lui
applique exactement la même logique que `alerts.repondre_alerte`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import obtenir_session
from ..security import hacher_numero
from .alerts import repondre_alerte

router = APIRouter(tags=["sms"])


@router.post("/sms/inbound")
def sms_entrant(payload: schemas.SmsInboundRequest, db: Session = Depends(obtenir_session)):
    texte = payload.text.strip()
    if texte not in ("1", "2"):
        return {"traite": False, "raison": "réponse attendue : 1 ou 2"}

    telephone_hash = hacher_numero(payload.phone_number)
    user = db.query(models.User).filter_by(telephone_hash=telephone_hash, desinscrit=False).first()
    if user is None:
        return {"traite": False, "raison": "compte inconnu"}

    alerte = (
        db.query(models.Alert)
        .filter_by(user_id=user.id, statut="en_attente")
        .order_by(models.Alert.cree_le.desc())
        .first()
    )
    if alerte is None:
        return {"traite": False, "raison": "aucune alerte en attente"}

    resultat = repondre_alerte(alerte.alert_id, schemas.RespondRequest(response=int(texte)), db)
    return {"traite": True, **resultat.model_dump()}
