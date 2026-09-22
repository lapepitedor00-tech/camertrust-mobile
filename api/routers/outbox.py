"""CamerTrust — E2 — Messages sortants simulés (lus par E3 : émulateur de terminal et console de supervision)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import obtenir_session
from ..security import hacher_numero

router = APIRouter(tags=["outbox"])


@router.get("/outbox", response_model=list[schemas.OutboxMessageOut])
def lire_outbox(phone_number: str | None = Query(None), db: Session = Depends(obtenir_session)):
    query = db.query(models.Outbox)
    if phone_number:
        telephone_hash = hacher_numero(phone_number)
        user = db.query(models.User).filter_by(telephone_hash=telephone_hash).first()
        if user is None:
            return []
        query = query.filter(models.Outbox.user_id == user.id)

    messages_sortants = query.order_by(models.Outbox.cree_le.asc()).all()
    resultat = []
    for m in messages_sortants:
        user = db.query(models.User).get(m.user_id)
        resultat.append(schemas.OutboxMessageOut(
            id=str(m.id), user_id=user.user_id if user else "?",
            phone_number=phone_number, body=m.corps, alert_id=m.alert_id, horodatage=m.cree_le,
        ))
    return resultat
