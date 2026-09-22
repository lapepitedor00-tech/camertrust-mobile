"""
CamerTrust — E2 — Authentification et console de supervision (plan p.8, S8)
================================================================================

`POST /auth/token` délivre un jeton simple (JWT) — le plan (p.8) ne demande
qu'« un jeton simple pour la console de supervision », pas un vrai système
multi-utilisateurs. Identifiants pour le PFE : variables d'environnement
`ADMIN_USER` / `ADMIN_PASSWORD` (valeurs de développement par défaut,
**à changer avant la soutenance**, voir DEPLOYMENT.md).

`GET /admin/alerts` reste volontairement accessible SANS jeton : c'est la
vue lue par la console de supervision d'E3, qui n'implémente pas d'écran
de connexion (le plan ne l'exige pas non plus dans la référence des
endpoints, p.9). Le jeton est prêt à protéger cette route (ou toute autre
route d'écriture ajoutée plus tard) via la dépendance `exiger_token` —
il suffit de l'ajouter en paramètre de la route à protéger.
"""

from __future__ import annotations

import datetime as dt
import os

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import obtenir_session
from ..security import creer_token, verifier_token

router = APIRouter(tags=["administration"])

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")


def exiger_token(authorization: str | None = Header(None)) -> str:
    """Dépendance réutilisable pour protéger une route par jeton — voir
    docstring du module. Non utilisée par `/admin/alerts` aujourd'hui,
    prête pour toute route future qui en aurait besoin."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Jeton manquant")
    sujet = verifier_token(authorization.removeprefix("Bearer "))
    if sujet is None:
        raise HTTPException(status_code=401, detail="Jeton invalide ou expiré")
    return sujet


@router.post("/auth/token", response_model=schemas.TokenResponse)
def obtenir_token(username: str, password: str):
    if username != ADMIN_USER or password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Identifiants invalides")
    return schemas.TokenResponse(access_token=creer_token(sujet=username))


@router.get("/admin/alerts")
def vue_supervision(
    stats: int = Query(0),
    date: str | None = Query(None, description="Filtre AAAA-MM-JJ"),
    montant_min: float | None = Query(None),
    db: Session = Depends(obtenir_session),
):
    query = db.query(models.Alert)
    if date:
        try:
            jour = dt.datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=422, detail="Format de date attendu : AAAA-MM-JJ")
        query = query.filter(
            models.Alert.cree_le >= dt.datetime.combine(jour, dt.time.min),
            models.Alert.cree_le <= dt.datetime.combine(jour, dt.time.max),
        )
    if montant_min is not None:
        query = query.filter(models.Alert.montant >= montant_min)

    alertes = query.order_by(models.Alert.cree_le.desc()).all()

    if stats:
        total_transactions = db.query(models.Transaction).count()
        nb_alertes = len(alertes)
        nb_repondues = sum(1 for a in alertes if a.statut != "en_attente")
        nb_bloquees = sum(1 for a in alertes if a.statut == "bloquee")
        taux_reponse = round(100 * nb_repondues / nb_alertes, 1) if nb_alertes else 0.0
        return {
            "transactions_jour": total_transactions,
            "alertes_jour": nb_alertes,
            "taux_reponse_pct": taux_reponse,
            "alertes_bloquees": nb_bloquees,
        }

    return [
        {
            "alert_id": a.alert_id,
            "user_id": db.query(models.User).get(a.user_id).user_id,
            "montant": a.montant,
            "type_op": a.type_operation,
            "heure": a.heure,
            "statut": a.statut,
            "horodatage": a.cree_le.isoformat(),
        }
        for a in alertes
    ]
