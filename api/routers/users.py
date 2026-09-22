"""CamerTrust — E2 — Comptes abonnés : inscription, désinscription, réglages, score de confiance (plan p.7-8, S4 et S7)."""

from __future__ import annotations

import random
import string

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import obtenir_session
from ..notifier import obtenir_notifier
from ..security import hacher_numero
from .. import messages

router = APIRouter(tags=["comptes"])


def _generer_user_id() -> str:
    return "C" + "".join(random.choices(string.digits, k=3))


def _get_user_ou_404(db: Session, user_id: str) -> models.User:
    user = db.query(models.User).filter_by(user_id=user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="Compte inconnu")
    return user


@router.post("/users/register", response_model=schemas.InscriptionResponse, status_code=201)
def inscrire(payload: schemas.InscriptionRequest, db: Session = Depends(obtenir_session)):
    """Inscription + enregistrement du consentement (plan p.7, S4). Le
    numéro n'est JAMAIS stocké en clair — seul `telephone_hash` l'est."""
    telephone_hash = hacher_numero(payload.phone_number)
    existant = db.query(models.User).filter_by(telephone_hash=telephone_hash).first()
    if existant is not None and not existant.desinscrit:
        raise HTTPException(status_code=409, detail="Ce numéro est déjà inscrit")

    identifiant = _generer_user_id()
    while db.query(models.User).filter_by(user_id=identifiant).first() is not None:
        identifiant = _generer_user_id()

    user = models.User(user_id=identifiant, telephone_hash=telephone_hash)
    db.add(user)
    db.flush()

    db.add(models.Consent(user_id=user.id, consenti=True))
    db.add(models.Settings(user_id=user.id))
    db.flush()

    notifier = obtenir_notifier()
    notifier.envoyer(db, user, messages.CONFIRMATION_INSCRIPTION)
    db.commit()

    return schemas.InscriptionResponse(user_id=identifiant, phone_number=payload.phone_number)


@router.delete("/users/{user_id}", status_code=200)
def desinscrire(user_id: str, db: Session = Depends(obtenir_session)):
    """Désinscription effective (plan p.7) : coupe les notifications ET
    efface les données de profil (réglages, historique de scoring). Les
    lignes `transactions`/`alerts` sont conservées à des fins d'audit mais
    ne référencent plus qu'un identifiant sans lien possible avec le
    numéro d'origine (le hash n'est jamais recalculable en sens inverse)."""
    user = _get_user_ou_404(db, user_id)
    user.desinscrit = True
    if user.reglages is not None:
        db.delete(user.reglages)
    db.commit()
    return {"deleted": True}


@router.get("/users/{user_id}/settings", response_model=schemas.SettingsOut)
def lire_reglages(user_id: str, db: Session = Depends(obtenir_session)):
    user = _get_user_ou_404(db, user_id)
    if user.reglages is None:
        raise HTTPException(status_code=404, detail="Réglages indisponibles (compte désinscrit ?)")
    return user.reglages


@router.put("/users/{user_id}/settings", response_model=schemas.SettingsOut)
def modifier_reglages(user_id: str, payload: schemas.SettingsIn, db: Session = Depends(obtenir_session)):
    """Plan p.8, S7 : les réglages de l'utilisateur sont évalués AVANT le
    modèle (liste blanche, plafonds) — voir `scoring.scorer_transaction`."""
    user = _get_user_ou_404(db, user_id)
    reglages = user.reglages
    if reglages is None:
        raise HTTPException(status_code=404, detail="Réglages indisponibles (compte désinscrit ?)")

    for champ, valeur in payload.model_dump(exclude_unset=True).items():
        setattr(reglages, champ, valeur)
    db.commit()
    db.refresh(reglages)
    return reglages


@router.get("/users/{user_id}/trustscore", response_model=schemas.TrustScoreOut)
def lire_score_confiance(user_id: str, db: Session = Depends(obtenir_session)):
    user = _get_user_ou_404(db, user_id)
    return schemas.TrustScoreOut(user_id=user.user_id, score=user.trust_score)
