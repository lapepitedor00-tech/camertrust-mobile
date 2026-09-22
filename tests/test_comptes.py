"""Tests des comptes abonnés : inscription, désinscription, réglages, score de confiance."""


def test_inscription_cree_un_compte(client):
    r = client.post("/users/register", json={"phone_number": "+237690000010"})
    assert r.status_code == 201
    corps = r.json()
    assert corps["user_id"].startswith("C")
    assert corps["phone_number"] == "+237690000010"


def test_inscription_en_double_est_refusee(client):
    client.post("/users/register", json={"phone_number": "+237690000011"})
    r = client.post("/users/register", json={"phone_number": "+237690000011"})
    assert r.status_code == 409


def test_inscription_envoie_un_sms_de_confirmation(client):
    r = client.post("/users/register", json={"phone_number": "+237690000012"})
    uid = r.json()["user_id"]
    outbox = client.get("/outbox", params={"phone_number": "+237690000012"}).json()
    assert len(outbox) == 1
    assert "CamerTrust" in outbox[0]["body"]
    assert len(outbox[0]["body"]) <= 160


def test_reglages_par_defaut(abonne, client):
    r = client.get(f"/users/{abonne}/settings")
    assert r.status_code == 200
    reglages = r.json()
    assert reglages["plafond"] > 0
    assert reglages["canal_prefere"] == "ussd"


def test_modification_reglages(abonne, client):
    r = client.put(f"/users/{abonne}/settings", json={"plafond": 1_000_000, "langue": "en"})
    assert r.status_code == 200
    assert r.json()["plafond"] == 1_000_000
    assert r.json()["langue"] == "en"

    relu = client.get(f"/users/{abonne}/settings").json()
    assert relu["plafond"] == 1_000_000


def test_trustscore_par_defaut(abonne, client):
    r = client.get(f"/users/{abonne}/trustscore")
    assert r.status_code == 200
    assert 0 <= r.json()["score"] <= 100


def test_desinscription_efface_les_reglages_et_coupe_les_notifications(abonne, client):
    r = client.delete(f"/users/{abonne}")
    assert r.status_code == 200
    assert r.json()["deleted"] is True

    # Le compte n'est plus utilisable pour scorer une transaction
    r = client.post("/transactions/score", json={"user_id": abonne, "amount": 1000, "type": "PAYMENT", "hour": 10})
    assert r.status_code == 404

    # Les réglages ont bien été supprimés
    r = client.get(f"/users/{abonne}/settings")
    assert r.status_code == 404


def test_compte_inconnu_renvoie_404(client):
    r = client.get("/users/INEXISTANT/settings")
    assert r.status_code == 404
