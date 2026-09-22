"""
CamerTrust — E2 — Catalogue des messages envoyés à l'abonné
===============================================================

Reproduit **mot pour mot** le catalogue proposé par E4 (plan p.18), pour
que le texte réellement envoyé par le backend corresponde à celui projeté
en soutenance et validé par les tests d'acceptation (S11). C'est la même
version que celle utilisée par le simulateur de repli d'E3
(`dashboard/demo_backend.py`, `MESSAGES`) — les deux doivent rester
synchronisés si E4 fait évoluer une formulation ; ce fichier est la
référence côté serveur (E3 ne fait que la rejouer hors ligne).

Chaque message respecte les 4 règles absolues du plan (p.18) : 160
caractères maximum, aucun lien cliquable, aucune demande de code PIN,
action attendue énoncée en fin de message.
"""

from __future__ import annotations

CONFIRMATION_INSCRIPTION = (
    "CamerTrust est active sur votre compte. Nous vous previendrons si "
    "une operation sort de vos habitudes. Pour arreter : *888*6#. Code "
    "jamais demande."
)

REPONSE_1_CONFIRMEE = (
    "Merci. Operation validee. CamerTrust retiendra moins cette "
    "habitude pour ce type d'operation."
)

REPONSE_2_BLOQUEE = (
    "Compte protege. Vos transferts sont suspendus 30 min. Un agent "
    "est informe. Pour reactiver : *888*9#. Nous ne demandons jamais "
    "votre code."
)

ABSENCE_REPONSE = (
    "CamerTrust : sans reponse de votre part, aucune action n'a ete "
    "prise. Consultez vos alertes au *888*2#."
)

DESINSCRIPTION = (
    "CamerTrust est desactivee. Vos donnees d'analyse sont effacees. "
    "Pour revenir un jour : *888*1#. Merci."
)


def alerte_risque_eleve(type_op: str, montant: float, heure_txt: str) -> str:
    """`heure_txt` est déjà formaté (ex. "a 02h14" ou "la nuit") — c'est
    `scoring.py` qui construit ce texte à partir de l'heure brute, pour
    garder ce module indépendant de la logique de formatage."""
    montant_txt = f"{montant:,.0f}".replace(",", " ")  # espace comme séparateur de milliers, pas de virgule
    corps = (
        f"CamerTrust : {type_op} de {montant_txt} FCFA {heure_txt} vers un "
        "numero inconnu. Inhabituel pour vous. Repondez 1 = c'est moi, "
        "2 = ce n'est pas moi."
    )
    return corps[:160]
