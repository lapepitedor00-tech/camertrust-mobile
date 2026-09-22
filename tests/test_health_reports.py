"""Tests des routes utilitaires : supervision technique (/health, /info)
et signalement de fraude par l'abonné (menu USSD option 5)."""


def test_health_renvoie_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_info_renvoie_l_etat_du_modele(client):
    r = client.get("/info")
    assert r.status_code == 200
    corps = r.json()
    assert "modele_charge" in corps


def test_signalement_par_un_abonne_connu(abonne, client):
    r = client.post("/reports", json={"user_id": abonne, "description": "Numero suspect m'a appele."})
    assert r.status_code == 200
    corps = r.json()
    assert corps["received"] is True
    assert len(corps["reference"]) == 8


def test_signalement_par_un_compte_inconnu_404(client):
    r = client.post("/reports", json={"user_id": "INEXISTANT"})
    assert r.status_code == 404
