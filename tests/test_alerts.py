"""Tests des alertes et du traitement des réponses (blocage réel et réversible)."""

import datetime as dt


def _creer_alerte(client, abonne: str) -> str:
    client.put(f"/users/{abonne}/settings", json={"plafond": 10_000, "plafond_nocturne": 10_000})
    r = client.post("/transactions/score", json={
        "user_id": abonne, "amount": 500_000, "type": "TRANSFER", "hour": 14, "step": 14,
    })
    alert_id = r.json()["alert_id"]
    assert alert_id is not None
    return alert_id


def test_reponse_1_confirme_l_alerte(abonne, client):
    alert_id = _creer_alerte(client, abonne)
    r = client.post(f"/alerts/{alert_id}/respond", json={"response": 1})
    assert r.status_code == 200
    assert r.json()["statut"] == "confirmee"


def test_reponse_2_bloque_effectivement_le_compte(abonne, client):
    from api import models
    from api.database import SessionLocal

    alert_id = _creer_alerte(client, abonne)
    r = client.post(f"/alerts/{alert_id}/respond", json={"response": 2})
    assert r.status_code == 200
    assert r.json()["statut"] == "bloquee"

    db = SessionLocal()
    try:
        user = db.query(models.User).filter_by(user_id=abonne).first()
        assert user.bloque_jusqu_a is not None
        assert user.bloque_jusqu_a > dt.datetime.utcnow()
    finally:
        db.close()


def test_reponse_est_stockee_comme_etiquette(abonne, client):
    """La réponse doit être persistée (`alert_responses`) pour la boucle
    de retour d'E1 (notebook 09)."""
    from api import models
    from api.database import SessionLocal

    alert_id = _creer_alerte(client, abonne)
    client.post(f"/alerts/{alert_id}/respond", json={"response": 2})

    db = SessionLocal()
    try:
        alerte = db.query(models.Alert).filter_by(alert_id=alert_id).first()
        reponses = db.query(models.AlertResponse).filter_by(alert_id=alerte.id).all()
        assert len(reponses) == 1
        assert reponses[0].reponse == 2
    finally:
        db.close()


def test_alerte_deja_traitee_refuse_une_seconde_reponse(abonne, client):
    alert_id = _creer_alerte(client, abonne)
    client.post(f"/alerts/{alert_id}/respond", json={"response": 1})
    r = client.post(f"/alerts/{alert_id}/respond", json={"response": 2})
    assert r.status_code == 409


def test_alerte_inconnue_404(client):
    r = client.post("/alerts/inexistante/respond", json={"response": 1})
    assert r.status_code == 404


def test_liste_des_alertes_d_un_abonne(abonne, client):
    _creer_alerte(client, abonne)
    r = client.get(f"/alerts/{abonne}")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_compte_bloque_refuse_reellement_les_transactions(abonne, client):
    """Le blocage doit être RÉEL (plan p.7) : une fois la réponse « 2 »
    envoyée, une nouvelle transaction est refusée — pas seulement
    enregistrée en base sans effet."""
    alert_id = _creer_alerte(client, abonne)
    client.post(f"/alerts/{alert_id}/respond", json={"response": 2})

    r = client.post("/transactions/score", json={
        "user_id": abonne, "amount": 100, "type": "PAYMENT", "hour": 10, "step": 20,
    })
    assert r.status_code == 403


def test_compte_debloque_automatiquement_apres_expiration(abonne, client):
    """Le blocage doit aussi être RÉVERSIBLE (plan p.7) : une fois le délai
    de 30 minutes écoulé, le compte redevient utilisable sans action
    manuelle de l'abonné."""
    import datetime as dt

    from api import models
    from api.database import SessionLocal

    alert_id = _creer_alerte(client, abonne)
    client.post(f"/alerts/{alert_id}/respond", json={"response": 2})

    # On simule l'écoulement du délai de blocage directement en base.
    db = SessionLocal()
    try:
        user = db.query(models.User).filter_by(user_id=abonne).first()
        user.bloque_jusqu_a = dt.datetime.utcnow() - dt.timedelta(minutes=1)
        db.commit()
    finally:
        db.close()

    r = client.post("/transactions/score", json={
        "user_id": abonne, "amount": 100, "type": "PAYMENT", "hour": 10, "step": 20,
    })
    assert r.status_code == 200
