"""
CamerTrust — E2 — Sécurité
============================

Deux responsabilités bien séparées :

1. **Hachage des identifiants** (numéro de téléphone, destinataire) —
   jamais stocké en clair (plan p.7). SHA-256 est suffisant ici : on ne
   cherche pas à "retrouver" le numéro à partir du hash pour un tiers, on
   veut seulement pouvoir reconnaître un numéro déjà vu sans le conserver
   en clair en base.
2. **Authentification de la console de supervision** — un jeton simple
   (JWT), pas un vrai système multi-utilisateurs (plan p.7, S8 : "jeton
   simple pour la console de supervision").
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os

from jose import JWTError, jwt

SECRET_KEY = os.environ.get("CAMERTRUST_SECRET_KEY", "cle-de-developpement-a-changer-en-production")
ALGORITHME = "HS256"
DUREE_TOKEN_MINUTES = 60


def hacher_numero(numero: str) -> str:
    """Identifiant stable et non réversible pour un numéro de téléphone.
    Utilisé aussi bien pour l'abonné émetteur que pour un destinataire
    (E1 a besoin de savoir si un destinataire a « déjà été vu », pas de
    connaître son numéro)."""
    return hashlib.sha256(numero.strip().encode("utf-8")).hexdigest()


def creer_token(sujet: str, duree_minutes: int = DUREE_TOKEN_MINUTES) -> str:
    expiration = dt.datetime.utcnow() + dt.timedelta(minutes=duree_minutes)
    return jwt.encode({"sub": sujet, "exp": expiration}, SECRET_KEY, algorithm=ALGORITHME)


def verifier_token(token: str) -> str | None:
    """Renvoie le sujet du jeton s'il est valide, sinon `None` (jamais
    d'exception qui remonterait telle quelle à l'appelant HTTP)."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHME])
        return payload.get("sub")
    except JWTError:
        return None
