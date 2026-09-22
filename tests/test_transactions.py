"""Tests du scoring des transactions — ordre d'évaluation, intégration du modèle d'E1, mode dégradé."""

from api import scoring


def test_transaction_normale_ne_declenche_pas_d_alerte(abonne, client):
    r = client.post("/transactions/score", json={
        "user_id": abonne, "amount": 3000, "type": "PAYMENT", "hour": 14, "step": 14,
    })
    assert r.status_code == 200
    corps = r.json()
    assert corps["is_fraud"] is False
    assert corps["alert_id"] is None
    assert corps["latence_ms"] < 2000  # checklist : réponse en moins de 2 s


def test_reponse_en_moins_de_2_secondes(abonne, client):
    r = client.post("/transactions/score", json={
        "user_id": abonne, "amount": 3000, "type": "PAYMENT", "hour": 14, "step": 14,
    })
    assert r.json()["latence_ms"] < 2000


def test_transaction_au_dessus_du_plafond_declenche_une_alerte_sans_modele(abonne, client):
    """Ordre d'évaluation (plan p.8) : le plafond court-circuite le modèle ML."""
    client.put(f"/users/{abonne}/settings", json={"plafond": 50_000, "plafond_nocturne": 20_000})
    r = client.post("/transactions/score", json={
        "user_id": abonne, "amount": 100_000, "type": "TRANSFER", "hour": 14, "step": 14,
    })
    corps = r.json()
    assert corps["is_fraud"] is True
    assert corps["alert_id"] is not None
    assert "plafond" in corps["motif"]


def test_destinataire_en_liste_blanche_jamais_alerte(abonne, client):
    client.put(f"/users/{abonne}/settings", json={"plafond": 1000, "liste_blanche": []})
    # On récupère le hash tel que E2 le calculerait pour whitelister le bon destinataire
    from api.security import hacher_numero
    dest_hash = hacher_numero("M_CONNU")
    client.put(f"/users/{abonne}/settings", json={"liste_blanche": [dest_hash]})

    r = client.post("/transactions/score", json={
        "user_id": abonne, "amount": 999_999, "type": "TRANSFER", "hour": 2, "step": 2, "name_dest": "M_CONNU",
    })
    corps = r.json()
    assert corps["is_fraud"] is False
    assert corps["alert_id"] is None


def test_modele_ml_detecte_une_transaction_hors_profil(abonne, client):
    """Construit un historique de jour avec un destinataire habituel, puis
    envoie une transaction nettement hors profil (montant x40, nuit,
    nouveau destinataire) SOUS le plafond — seul le modèle d'E1 peut la
    détecter."""
    client.put(f"/users/{abonne}/settings", json={"plafond": 5_000_000, "plafond_nocturne": 5_000_000})
    for i in range(10):
        client.post("/transactions/score", json={
            "user_id": abonne, "amount": 5000, "type": "PAYMENT", "hour": 14,
            "step": i * 24 + 14, "name_dest": "M1",
        })
    r = client.post("/transactions/score", json={
        "user_id": abonne, "amount": 300_000, "type": "TRANSFER", "hour": 2,
        "step": 11 * 24 + 2, "name_dest": "M_JAMAIS_VU",
    })
    corps = r.json()
    assert corps["is_fraud"] is True
    assert corps["degraded_mode"] is False
    assert len(corps["motif"]) <= 120  # contrainte SMS d'E1, propagée jusqu'ici
    assert corps["alert_id"] is not None


def test_mode_degrade_repond_meme_sans_modele(abonne, client):
    """Checklist E2 : « le service répond même sans modèle chargé ».
    Plafonds volontairement larges pour que ce soit bien la RÈGLE DÉGRADÉE
    (montant élevé la nuit, seuil fixe) qui détecte la fraude — et non le
    plafond personnel, déjà couvert par un autre test."""
    pipeline_sauvegarde, info_sauvegarde = scoring.PIPELINE, scoring.MODEL_INFO
    try:
        scoring.PIPELINE, scoring.MODEL_INFO = None, None
        client.put(f"/users/{abonne}/settings", json={"plafond": 5_000_000, "plafond_nocturne": 5_000_000})
        r = client.post("/transactions/score", json={
            "user_id": abonne, "amount": 1_000_000, "type": "TRANSFER", "hour": 2, "step": 2,
        })
        assert r.status_code == 200
        corps = r.json()
        assert corps["degraded_mode"] is True
        assert corps["is_fraud"] is True  # 1M > seuil dégradé fixe (200k), la nuit, sous le plafond

        # Sous le seuil dégradé : pas de fraude, mais toujours en mode dégradé.
        r2 = client.post("/transactions/score", json={
            "user_id": abonne, "amount": 5_000, "type": "PAYMENT", "hour": 2, "step": 3,
        })
        assert r2.json()["degraded_mode"] is True
        assert r2.json()["is_fraud"] is False
    finally:
        scoring.PIPELINE, scoring.MODEL_INFO = pipeline_sauvegarde, info_sauvegarde


def test_transaction_sur_compte_inconnu_404(client):
    r = client.post("/transactions/score", json={"user_id": "INEXISTANT", "amount": 100, "type": "PAYMENT", "hour": 10})
    assert r.status_code == 404
