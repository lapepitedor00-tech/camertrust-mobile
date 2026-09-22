"""Tests de navigation du webhook USSD (plan p.7 : « 4 tests de navigation »)."""


def _composer(client, session_id, phone, text=""):
    return client.post("/ussd", data={"sessionId": session_id, "phoneNumber": phone, "text": text})


def test_menu_racine_liste_les_6_options(client):
    r = _composer(client, "s1", "+237690000020")
    assert r.status_code == 200
    corps = r.text
    assert corps.startswith("CON")
    for option in ["1.", "2.", "3.", "4.", "5.", "6."]:
        assert option in corps


def test_numero_inconnu_est_refuse(client):
    r = _composer(client, "s2", "+237699999999", text="1")
    assert r.text.startswith("END")
    assert "inconnu" in r.text


def test_option_1_affiche_le_score_de_confiance(client):
    inscription = client.post("/users/register", json={"phone_number": "+237690000021"})
    r = _composer(client, "s3", "+237690000021", text="1")
    assert r.text.startswith("END")
    assert "/100" in r.text


def test_modification_du_plafond_en_trois_etapes(client):
    inscription = client.post("/users/register", json={"phone_number": "+237690000022"})
    user_id = inscription.json()["user_id"]

    r1 = _composer(client, "s4", "+237690000022", text="3")
    assert r1.text.startswith("CON")
    r2 = _composer(client, "s4", "+237690000022", text="3*1")
    assert r2.text.startswith("CON")
    r3 = _composer(client, "s4", "+237690000022", text="3*1*750000")
    assert r3.text.startswith("END")
    assert "750000" in r3.text

    # Vérifie que le plafond est réellement mis à jour en base
    reglages = client.get(f"/users/{user_id}/settings").json()
    assert reglages["plafond"] == 750000


def test_desinscription_via_ussd_option_6(client):
    r = client.post("/users/register", json={"phone_number": "+237690000023"})
    uid = r.json()["user_id"]
    r = _composer(client, "s5", "+237690000023", text="6")
    assert r.text.startswith("END")
    assert "desinscrit" in r.text

    # Le compte ne doit plus être utilisable
    r2 = client.post("/transactions/score", json={"user_id": uid, "amount": 100, "type": "PAYMENT", "hour": 10})
    assert r2.status_code == 404


def test_session_ussd_est_persistee(client):
    from api import models
    from api.database import SessionLocal

    client.post("/users/register", json={"phone_number": "+237690000024"})
    _composer(client, "session-persistee", "+237690000024", text="1")

    db = SessionLocal()
    try:
        session = db.query(models.UssdSession).filter_by(session_id="session-persistee").first()
        assert session is not None
        assert session.etat == ["1"]
    finally:
        db.close()
