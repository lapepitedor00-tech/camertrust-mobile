"""CamerTrust — E2 — Webhook USSD (plan p.7, S5)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from ..database import obtenir_session
from ..ussd_menu import traiter_ussd

router = APIRouter(tags=["ussd"])


@router.post("/ussd", response_class=PlainTextResponse)
def webhook_ussd(
    sessionId: str = Form(...),
    phoneNumber: str = Form(...),
    text: str = Form(""),
    db: Session = Depends(obtenir_session),
):
    """Reçoit `sessionId`, `phoneNumber`, `text` en `application/x-www-form-urlencoded`
    — exactement le format d'un agrégateur USSD réel (Africa's Talking,
    Nexah...). Répond en texte brut préfixé `CON` (le menu continue) ou
    `END` (fin de session), jamais en JSON : c'est le protocole USSD, pas
    une invention du projet."""
    reponse = traiter_ussd(db, sessionId, phoneNumber, text)
    db.commit()
    return PlainTextResponse(reponse)
