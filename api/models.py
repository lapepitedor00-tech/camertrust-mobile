"""
CamerTrust — E2 — Schéma de base de données (8 tables, plan p.7)
====================================================================

`users`, `consents`, `settings`, `transactions`, `alerts`,
`alert_responses`, `outbox`, `ussd_sessions`.

Règle absolue (plan p.7, « Difficultés identifiées ») : **aucun numéro de
téléphone n'est stocké en clair** — seul un identifiant haché
(`security.hacher_numero`) est conservé. C'est vérifié explicitement dans
les tests (`tests/test_confidentialite.py`).
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _maintenant() -> dt.datetime:
    return dt.datetime.utcnow()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)  # identifiant public, ex. "C123"
    telephone_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # sha256, JAMAIS le numéro en clair
    trust_score: Mapped[int] = mapped_column(Integer, default=70)
    desinscrit: Mapped[bool] = mapped_column(Boolean, default=False)
    bloque_jusqu_a: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    cree_le: Mapped[dt.datetime] = mapped_column(DateTime, default=_maintenant)

    consentement = relationship("Consent", back_populates="utilisateur", uselist=False, cascade="all, delete-orphan")
    reglages = relationship("Settings", back_populates="utilisateur", uselist=False, cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="utilisateur", cascade="all, delete-orphan")
    alertes = relationship("Alert", back_populates="utilisateur", cascade="all, delete-orphan")


class Consent(Base):
    __tablename__ = "consents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    consenti: Mapped[bool] = mapped_column(Boolean, default=True)
    version_texte: Mapped[str] = mapped_column(String(16), default="v1")  # version des CGU acceptées (texte rédigé par E4)
    horodatage: Mapped[dt.datetime] = mapped_column(DateTime, default=_maintenant)

    utilisateur = relationship("User", back_populates="consentement")


class Settings(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    plafond: Mapped[int] = mapped_column(Integer, default=500_000)
    plafond_nocturne: Mapped[int] = mapped_column(Integer, default=100_000)
    liste_blanche: Mapped[list] = mapped_column(JSON, default=list)  # destinataires jamais alertés
    canal_prefere: Mapped[str] = mapped_column(String(8), default="ussd")  # ussd | sms | app
    langue: Mapped[str] = mapped_column(String(4), default="fr")

    utilisateur = relationship("User", back_populates="reglages")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    step: Mapped[int] = mapped_column(Integer)  # heures écoulées, convention PaySim (voir E1)
    type_operation: Mapped[str] = mapped_column(String(16))
    montant: Mapped[float] = mapped_column(Float)
    destinataire_hash: Mapped[str] = mapped_column(String(64))  # même logique que le numéro : jamais en clair
    is_fraud: Mapped[bool] = mapped_column(Boolean, default=False)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    motif: Mapped[str] = mapped_column(String(160), default="")
    latence_ms: Mapped[float] = mapped_column(Float, default=0.0)
    cree_le: Mapped[dt.datetime] = mapped_column(DateTime, default=_maintenant)

    utilisateur = relationship("User", back_populates="transactions")


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"), nullable=True)
    montant: Mapped[float] = mapped_column(Float)
    type_operation: Mapped[str] = mapped_column(String(16))
    heure: Mapped[int] = mapped_column(Integer)
    motif: Mapped[str] = mapped_column(String(160))
    statut: Mapped[str] = mapped_column(String(16), default="en_attente")  # en_attente | confirmee | bloquee
    cree_le: Mapped[dt.datetime] = mapped_column(DateTime, default=_maintenant)

    utilisateur = relationship("User", back_populates="alertes")
    reponses = relationship("AlertResponse", back_populates="alerte", cascade="all, delete-orphan")


class AlertResponse(Base):
    __tablename__ = "alert_responses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id"))
    reponse: Mapped[int] = mapped_column(Integer)  # 1 = c'est moi, 2 = ce n'est pas moi
    horodatage: Mapped[dt.datetime] = mapped_column(DateTime, default=_maintenant)

    alerte = relationship("Alert", back_populates="reponses")


class Outbox(Base):
    """Passerelle de notification simulée (plan p.7, point (3)) : tant
    qu'aucun opérateur réel n'est branché, chaque « envoi » de message se
    résume à une ligne ici — voir `notifier.py`."""

    __tablename__ = "outbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    alert_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    corps: Mapped[str] = mapped_column(String(160))
    canal: Mapped[str] = mapped_column(String(8), default="sms")
    cree_le: Mapped[dt.datetime] = mapped_column(DateTime, default=_maintenant)


class UssdSession(Base):
    """Une session USSD = une ligne (plan p.7 : « ne cherche pas plus
    sophistiqué »). `etat` contient la liste des saisies déjà envoyées par
    l'abonné pour cette session (protocole CON/END : `text` cumule tout
    depuis le début)."""

    __tablename__ = "ussd_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    telephone_hash: Mapped[str] = mapped_column(String(64), index=True)
    etat: Mapped[list] = mapped_column(JSON, default=list)
    historique: Mapped[str] = mapped_column(Text, default="")  # dernier écran affiché (débogage / support)
    cree_le: Mapped[dt.datetime] = mapped_column(DateTime, default=_maintenant)
    maj_le: Mapped[dt.datetime] = mapped_column(DateTime, default=_maintenant, onupdate=_maintenant)
