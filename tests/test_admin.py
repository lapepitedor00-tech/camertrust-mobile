"""Tests de l'authentification et de la console de supervision (plan p.8, S8)."""

import os


def test_jeton_avec_identifiants_valides(client):
    r = client.post("/auth/token", params={
        "username": os.environ.get("ADMIN_USER", "admin"),
        "password": os.environ.get("ADMIN_PASSWORD", "changeme"),
    })
    assert r.status_code == 200
    corps = r.json()
    assert corps["token_type"] == "bearer"
    assert len(corps["access_token"]) > 10


def test_jeton_avec_identifiants_invalides_est_refuse(client):
    r = client.post("/auth/token", params={"username": "admin", "password": "mauvais-mot-de-passe"})
    assert r.status_code == 401


def test_liste_des_alertes_de_supervision(abonne, client):
    client.put(f"/users/{abonne}/settings", json={"plafond": 1000})
    client.post("/transactions/score", json={
        "user_id": abonne, "amount": 500_000, "type": "TRANSFER", "hour": 14, "step": 14,
    })
    r = client.get("/admin/alerts")
    assert r.status_code == 200
    alertes = r.json()
    assert len(alertes) == 1
    assert alertes[0]["user_id"] == abonne
    assert alertes[0]["statut"] == "en_attente"


def test_statistiques_agregees_de_supervision(abonne, client):
    client.put(f"/users/{abonne}/settings", json={"plafond": 1000})
    client.post("/transactions/score", json={
        "user_id": abonne, "amount": 500, "type": "PAYMENT", "hour": 10, "step": 10,
    })
    client.post("/transactions/score", json={
        "user_id": abonne, "amount": 500_000, "type": "TRANSFER", "hour": 14, "step": 14,
    })
    r = client.get("/admin/alerts", params={"stats": 1})
    assert r.status_code == 200
    stats = r.json()
    assert stats["transactions_jour"] == 2
    assert stats["alertes_jour"] == 1
    assert stats["taux_reponse_pct"] == 0.0


def test_console_accessible_sans_jeton(client):
    """Décision documentée (api/routers/admin.py) : la console d'E3 lit
    `/admin/alerts` sans authentification — pas d'écran de connexion côté
    émulateur de terminal."""
    r = client.get("/admin/alerts")
    assert r.status_code == 200
