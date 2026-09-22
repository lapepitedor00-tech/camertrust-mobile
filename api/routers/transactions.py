"""CamerTrust — E2 — Scoring des transactions (plan p.7-8, S4)."""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import messages, models, schemas
from ..database import obtenir_session
from ..notifier import obtenir_notifier
from ..scoring import _formater_heure_texte, scorer_transaction
from ..security import hacher_numero

router = APIRouter(tags=["transactions"])


@router.post("/transactions/score", response_model=schemas.TransactionResponse)
def scorer(payload: schemas.TransactionRequest, db: Session = Depends(obtenir_session)):
    """Doit répondre en moins de 2 secondes (checklist E2) — le scoring en
    lui-même prend quelques millisecondes (voir `latence_ms` dans la
    réponse) ; c'est mesuré, pas seulement supposé."""
    user = db.query(models.User).filter_by(user_id=payload.user_id, desinscrit=False).first()
    if user is None:
        raise HTTPException(status_code=404, detail="Compte inconnu ou désinscrit")

    if user.bloque_jusqu_a is not None:
        if user.bloque_jusqu_a > dt.datetime.utcnow():
            # Blocage réel (plan p.7) : une réponse « 2 » à une alerte
            # bloque effectivement le compte, pas seulement en apparence.
            raise HTTPException(
                status_code=403,
                detail=f"Compte temporairement bloqué jusqu'à {user.bloque_jusqu_a.isoformat()}Z "
                        "suite à une alerte non confirmée.",
            )
        # Le blocage est expiré (réversible, plan p.7) : on le lève
        # silencieusement, pas besoin d'une action explicite de l'abonné.
        user.bloque_jusqu_a = None

    reglages = user.reglages
    if reglages is None:
        raise HTTPException(status_code=422, detail="Compte sans réglages associés")

    step = payload.step if payload.step is not None else payload.hour
    destinataire_hash = hacher_numero(payload.name_dest) if payload.name_dest else None

    resultat = scorer_transaction(
        db=db, user=user, reglages=reglages,
        montant=payload.amount, type_operation=payload.type,
        heure=payload.hour, step=step, destinataire_hash=destinataire_hash,
    )

    transaction = models.Transaction(
        user_id=user.id, step=step, type_operation=payload.type, montant=payload.amount,
        destinataire_hash=destinataire_hash or "INCONNU",
        is_fraud=resultat.is_fraud, score=resultat.score, motif=resultat.motif,
        latence_ms=resultat.latence_ms,
    )
    db.add(transaction)
    db.flush()

    alert_id = None
    if resultat.is_fraud:
        alert_id = str(uuid.uuid4())
        alerte = models.Alert(
            alert_id=alert_id, user_id=user.id, transaction_id=transaction.id,
            montant=payload.amount, type_operation=payload.type, heure=payload.hour,
            motif=resultat.motif, statut="en_attente",
        )
        db.add(alerte)
        db.flush()

        corps = messages.alerte_risque_eleve(payload.type, payload.amount, _formater_heure_texte(payload.hour))
        notifier = obtenir_notifier()
        notifier.envoyer(db, user, corps, alert_id=alert_id, canal=reglages.canal_prefere)

    db.commit()

    return schemas.TransactionResponse(
        is_fraud=resultat.is_fraud, score=resultat.score, motif=resultat.motif,
        latence_ms=resultat.latence_ms, alert_id=alert_id, degraded_mode=resultat.degraded_mode,
    )
