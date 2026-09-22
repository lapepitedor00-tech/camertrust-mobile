"""CamerTrust — E2 — Alertes et traitement des réponses (plan p.7, S6)."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import messages, models, schemas
from ..database import obtenir_session
from ..notifier import obtenir_notifier

router = APIRouter(tags=["alertes"])

DUREE_BLOCAGE_MINUTES = 30


@router.get("/alerts/{user_id}", response_model=list[schemas.AlertOut])
def lister_alertes(user_id: str, db: Session = Depends(obtenir_session)):
    user = db.query(models.User).filter_by(user_id=user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="Compte inconnu")
    alertes = db.query(models.Alert).filter_by(user_id=user.id).order_by(models.Alert.cree_le.desc()).all()
    return [
        schemas.AlertOut(
            alert_id=a.alert_id, montant=a.montant, type_op=a.type_operation,
            heure=a.heure, motif=a.motif, statut=a.statut, horodatage=a.cree_le,
        )
        for a in alertes
    ]


@router.post("/alerts/{alert_id}/respond", response_model=schemas.RespondResponse)
def repondre_alerte(alert_id: str, payload: schemas.RespondRequest, db: Session = Depends(obtenir_session)):
    """Réponse « 2 » (ce n'est pas moi) déclenche un blocage temporaire
    RÉEL et RÉVERSIBLE (30 min, plan p.7) ; réponse « 1 » (c'est moi)
    confirme l'opération. Dans les deux cas, la réponse est stockée comme
    étiquette d'apprentissage pour E1 (`alert_responses`, boucle de
    retour du notebook 09)."""
    alerte = db.query(models.Alert).filter_by(alert_id=alert_id).first()
    if alerte is None:
        raise HTTPException(status_code=404, detail="Alerte inconnue")
    if alerte.statut != "en_attente":
        raise HTTPException(status_code=409, detail=f"Alerte déjà traitée (statut actuel : {alerte.statut})")

    user = db.query(models.User).get(alerte.user_id)

    db.add(models.AlertResponse(alert_id=alerte.id, reponse=payload.response))

    notifier = obtenir_notifier()
    if payload.response == 2:
        alerte.statut = "bloquee"
        user.bloque_jusqu_a = dt.datetime.utcnow() + dt.timedelta(minutes=DUREE_BLOCAGE_MINUTES)
        notifier.envoyer(db, user, messages.REPONSE_2_BLOQUEE, alert_id=alert_id)
    else:
        alerte.statut = "confirmee"
        notifier.envoyer(db, user, messages.REPONSE_1_CONFIRMEE, alert_id=alert_id)

    db.commit()
    return schemas.RespondResponse(alert_id=alert_id, statut=alerte.statut)
