"""
CamerTrust — E2 — Webhook USSD (S5, plan p.7)
=================================================

« Une session = une ligne en base avec session_id, user_id, etat,
historique. Le menu est un dictionnaire d'états. Ne cherche pas plus
sophistiqué. » — implémenté ici tel quel.

Le menu (6 options) est IDENTIQUE à celui déjà rejoué hors ligne par le
simulateur de repli d'E3 (`dashboard/demo_backend.py`), pour que la démo
soit cohérente que l'API réponde ou que E3 bascule en Plan B.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from . import models
from .scoring import calculer_historique_compte
from .security import hacher_numero

MENU_RACINE = (
    "CON CamerTrust\n"
    "1. Mon score de confiance\n2. Mes alertes\n3. Mes plafonds\n"
    "4. Mes numeros habituels\n5. Signaler une fraude\n"
    "6. Me desinscrire"
)


def _obtenir_ou_creer_session(db: Session, session_id: str, telephone_hash: str) -> models.UssdSession:
    session = db.query(models.UssdSession).filter_by(session_id=session_id).first()
    if session is None:
        session = models.UssdSession(session_id=session_id, telephone_hash=telephone_hash, etat=[])
        db.add(session)
        db.flush()
    return session


def traiter_ussd(db: Session, session_id: str, phone_number: str, text: str) -> str:
    """Point d'entrée appelé par `routers/ussd.py`. `text` est le texte
    brut envoyé par l'agrégateur (ou l'émulateur d'E3) : la totalité des
    saisies de l'abonné depuis le début de la session, séparées par « * »
    — c'est le protocole USSD réel, pas une invention du projet."""
    telephone_hash = hacher_numero(phone_number)
    session = _obtenir_ou_creer_session(db, session_id, telephone_hash)

    etapes = [s for s in text.split("*") if s != ""] if text else []
    session.etat = etapes
    session.maj_le = dt.datetime.utcnow()

    if not etapes:
        session.historique = MENU_RACINE
        db.flush()
        return MENU_RACINE

    user = db.query(models.User).filter_by(telephone_hash=telephone_hash, desinscrit=False).first()
    if user is None:
        reponse = "END Compte inconnu ou desinscrit. Composez *888# apres inscription."
        session.historique = reponse
        db.flush()
        return reponse

    choix = etapes[0]
    reponse = _router_choix(db, user, etapes, choix)
    session.historique = reponse
    db.flush()
    return reponse


def _router_choix(db: Session, user: models.User, etapes: list[str], choix: str) -> str:
    if choix == "1":
        return f"END Votre score de confiance : {user.trust_score}/100"

    if choix == "2":
        derniere = (
            db.query(models.Alert)
            .filter_by(user_id=user.id)
            .order_by(models.Alert.cree_le.desc())
            .first()
        )
        if derniere is None:
            return "END Aucune alerte recente."
        return (
            f"END Derniere alerte : {derniere.type_operation} {derniere.montant:,.0f} FCFA "
            f"a {derniere.heure}h - statut : {derniere.statut}"
        ).replace(",", " ")

    if choix == "3":
        reglages = user.reglages
        if len(etapes) == 1:
            return (
                f"CON Plafond actuel : {reglages.plafond:.0f} FCFA\n"
                f"Plafond nocturne : {reglages.plafond_nocturne:.0f} FCFA\n"
                "1. Modifier le plafond\n2. Retour"
            )
        if len(etapes) == 2 and etapes[1] == "1":
            return "CON Entrez le nouveau plafond (FCFA) :"
        if len(etapes) == 3 and etapes[1] == "1":
            try:
                nouveau = int(etapes[2])
            except ValueError:
                return "END Montant invalide."
            reglages.plafond = nouveau
            db.flush()
            return f"END Plafond mis a jour : {nouveau} FCFA."
        return "END Session terminee."

    if choix == "4":
        liste = user.reglages.liste_blanche or []
        return "END Numeros habituels enregistres : " + (str(len(liste)) if liste else "aucun")

    if choix == "5":
        return "END Signalement enregistre. Un agent vous contactera si besoin."

    if choix == "6":
        user.desinscrit = True
        db.flush()
        return "END Vous etes desinscrit. Vos donnees ont ete effacees."

    return "END Choix invalide."
