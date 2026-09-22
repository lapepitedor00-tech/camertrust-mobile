"""Tests du canal SMS entrant (réponse directe « 1 »/« 2 » à l'alerte,
sans passer par le menu USSD — plan p.9 : `/alerts/{id}/respond`
« appelable par SMS retour, USSD, mini-app »)."""


def _inscrire_et_alerter(client, phone_number: str) -> str:
    inscription = client.post("/users/register", json={"phone_number": phone_number})
    user_id = inscription.json()["user_id"]
    client.put(f"/users/{user_id}/settings", json={"plafond": 10_000, "plafond_nocturne": 10_000})
    r = client.post("/transactions/score", json={
        "user_id": user_id, "amount": 500_000, "type": "TRANSFER", "hour": 14, "step": 14,
    })
    assert r.json()["alert_id"] is not None
    return user_id


def test_reponse_sms_1_confirme_l_alerte(client):
    _inscrire_et_alerter(client, "+237690000030")
    r = client.post("/sms/inbound", json={"phone_number": "+237690000030", "text": "1"})
    assert r.status_code == 200
    corps = r.json()
    assert corps["traite"] is True
    assert corps["statut"] == "confirmee"


def test_reponse_sms_2_bloque_le_compte(client):
    _inscrire_et_alerter(client, "+237690000031")
    r = client.post("/sms/inbound", json={"phone_number": "+237690000031", "text": "2"})
    assert r.status_code == 200
    assert r.json()["statut"] == "bloquee"


def test_reponse_sms_texte_invalide_est_ignoree(client):
    _inscrire_et_alerter(client, "+237690000032")
    r = client.post("/sms/inbound", json={"phone_number": "+237690000032", "text": "bonjour"})
    assert r.status_code == 200
    corps = r.json()
    assert corps["traite"] is False
    assert "1 ou 2" in corps["raison"]


def test_reponse_sms_compte_inconnu(client):
    r = client.post("/sms/inbound", json={"phone_number": "+237699999999", "text": "1"})
    assert r.status_code == 200
    corps = r.json()
    assert corps["traite"] is False
    assert "inconnu" in corps["raison"]


def test_reponse_sms_sans_alerte_en_attente(client):
    client.post("/users/register", json={"phone_number": "+237690000033"})
    r = client.post("/sms/inbound", json={"phone_number": "+237690000033", "text": "1"})
    assert r.status_code == 200
    corps = r.json()
    assert corps["traite"] is False
    assert "attente" in corps["raison"]
