"""
CamerTrust — E2 — Passerelle de notification
================================================

Plan p.7, point (3) : « au lieu d'émettre un vrai SMS, une seule classe
existe dans le code : `Notifier`. Le jour où un vrai opérateur existe,
seule cette classe change. » C'est exactement ce que fait ce module.

- `ConsoleNotifier` : écrit dans la table `outbox` (lue par E3 via
  `GET /outbox`) ET journalise dans les logs de l'application. C'est
  l'implémentation active pour le PFE.
- `SmsNotifier` : squelette documenté, **non activé**. Montre au jury que
  le système est prêt à être branché à un agrégateur SMS réel — ce n'est
  qu'une classe à écrire, l'architecture n'a pas besoin de changer.

Le choix d'implémentation se fait via la variable d'environnement
`NOTIFIER_BACKEND` (`console`, par défaut, ou `sms`).
"""

from __future__ import annotations

import logging
import os

from sqlalchemy.orm import Session

from . import models

logger = logging.getLogger("camertrust.notifier")

LONGUEUR_MAX_SMS = 160


class Notifier:
    """Interface commune. `envoyer` est la seule méthode que le reste du
    code appelle — jamais directement `Outbox` ou une bibliothèque SMS."""

    def envoyer(self, db: Session, user: models.User, corps: str, alert_id: str | None = None, canal: str = "sms") -> models.Outbox:
        raise NotImplementedError


class ConsoleNotifier(Notifier):
    """Implémentation active pour le PFE : écrit le message dans la table
    `outbox` (au lieu de l'émettre réellement) et le journalise."""

    def envoyer(self, db: Session, user: models.User, corps: str, alert_id: str | None = None, canal: str = "sms") -> models.Outbox:
        corps_tronque = corps[:LONGUEUR_MAX_SMS]
        message = models.Outbox(user_id=user.id, alert_id=alert_id, corps=corps_tronque, canal=canal)
        db.add(message)
        db.flush()
        logger.info("SMS simulé -> %s : %s", user.user_id, corps_tronque)
        return message


class SmsNotifier(Notifier):
    """Squelette non activé — documente ce qu'il faudrait faire pour
    brancher un vrai agrégateur (Africa's Talking, Nexah, ou l'opérateur
    MTN/Orange une fois la convention signée, voir plan p.15, section E4
    « Recommandations de déploiement »).

    Étapes réelles à implémenter ici, le jour venu :
    1. Authentification auprès de l'agrégateur (clé API).
    2. Appel HTTP à l'endpoint d'envoi de SMS de l'agrégateur.
    3. Gestion des accusés de réception (webhook de statut de livraison).
    4. Retomber sur `ConsoleNotifier.envoyer` en cas d'échec réseau, pour
       ne jamais perdre la trace d'une alerte (voir `outbox`).
    """

    def envoyer(self, db: Session, user: models.User, corps: str, alert_id: str | None = None, canal: str = "sms") -> models.Outbox:
        raise NotImplementedError(
            "SmsNotifier n'est pas activé — voir la documentation de la classe. "
            "Utilisez NOTIFIER_BACKEND=console (par défaut) pour le PFE."
        )


def obtenir_notifier() -> Notifier:
    backend = os.environ.get("NOTIFIER_BACKEND", "console")
    if backend == "sms":
        return SmsNotifier()
    return ConsoleNotifier()
