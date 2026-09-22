"""CamerTrust — E2 — Schémas Pydantic (requêtes / réponses)."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field


class InscriptionRequest(BaseModel):
    phone_number: str = Field(..., description="Numéro de l'abonné — jamais stocké en clair")


class InscriptionResponse(BaseModel):
    user_id: str
    phone_number: str  # renvoyé une seule fois, à l'inscription, jamais relu ensuite


class TransactionRequest(BaseModel):
    user_id: str
    amount: float
    type: str = Field(..., description="CASH_IN | CASH_OUT | DEBIT | PAYMENT | TRANSFER")
    hour: int = Field(..., ge=0, le=23)
    step: int | None = Field(None, description="Optionnel : step PaySim complet (sinon dérivé de `hour`)")
    name_dest: str | None = Field(None, description="Identifiant du destinataire (haché avant stockage)")


class TransactionResponse(BaseModel):
    is_fraud: bool
    score: float
    motif: str
    latence_ms: float
    alert_id: str | None = None
    degraded_mode: bool = False


class AlertOut(BaseModel):
    alert_id: str
    montant: float
    type_op: str
    heure: int
    motif: str
    statut: str
    horodatage: dt.datetime

    model_config = {"from_attributes": True}


class RespondRequest(BaseModel):
    response: int = Field(..., ge=1, le=2, description="1 = c'est moi, 2 = ce n'est pas moi")


class RespondResponse(BaseModel):
    alert_id: str
    statut: str


class SettingsIn(BaseModel):
    plafond: int | None = None
    plafond_nocturne: int | None = None
    liste_blanche: list[str] | None = None
    canal_prefere: str | None = None
    langue: str | None = None


class SettingsOut(BaseModel):
    plafond: int
    plafond_nocturne: int
    liste_blanche: list[str]
    canal_prefere: str
    langue: str

    model_config = {"from_attributes": True}


class TrustScoreOut(BaseModel):
    user_id: str
    score: int


class ReportRequest(BaseModel):
    user_id: str
    description: str = ""


class ReportResponse(BaseModel):
    received: bool
    reference: str


class OutboxMessageOut(BaseModel):
    id: str
    user_id: str
    phone_number: str | None = None
    body: str
    alert_id: str | None = None
    horodatage: dt.datetime


class SmsInboundRequest(BaseModel):
    phone_number: str
    text: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
