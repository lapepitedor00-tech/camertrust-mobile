"""Tests de la boîte de sortie simulée (messages lus par E3 : émulateur de
terminal et console de supervision — plan p.7, point (3))."""


def test_message_de_confirmation_respecte_la_limite_sms(client):
    client.post("/users/register", json={"phone_number": "+237690000040"})
    outbox = client.get("/outbox", params={"phone_number": "+237690000040"}).json()
    assert len(outbox) == 1
    assert len(outbox[0]["body"]) <= 160


def test_alerte_genere_un_message_sortant_avec_lien_vers_l_alerte(abonne, client):
    client.put(f"/users/{abonne}/settings", json={"plafond": 1000})
    r = client.post("/transactions/score", json={
        "user_id": abonne, "amount": 500_000, "type": "TRANSFER", "hour": 14, "step": 14,
    })
    alert_id = r.json()["alert_id"]

    outbox = client.get("/outbox", params={"phone_number": "+237690000001"}).json()
    messages_alerte = [m for m in outbox if m["alert_id"] == alert_id]
    assert len(messages_alerte) == 1
    assert len(messages_alerte[0]["body"]) <= 160


def test_outbox_filtre_par_numero_ne_renvoie_que_les_messages_de_cet_abonne(client):
    client.post("/users/register", json={"phone_number": "+237690000041"})
    client.post("/users/register", json={"phone_number": "+237690000042"})

    outbox_1 = client.get("/outbox", params={"phone_number": "+237690000041"}).json()
    outbox_2 = client.get("/outbox", params={"phone_number": "+237690000042"}).json()
    assert len(outbox_1) == 1
    assert len(outbox_2) == 1
    assert outbox_1[0]["id"] != outbox_2[0]["id"]


def test_outbox_numero_inconnu_renvoie_une_liste_vide(client):
    r = client.get("/outbox", params={"phone_number": "+237698888888"})
    assert r.status_code == 200
    assert r.json() == []


def test_outbox_sans_filtre_renvoie_tous_les_messages(client):
    client.post("/users/register", json={"phone_number": "+237690000043"})
    client.post("/users/register", json={"phone_number": "+237690000044"})
    r = client.get("/outbox")
    assert r.status_code == 200
    assert len(r.json()) >= 2
