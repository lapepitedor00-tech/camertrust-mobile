"""Test de confidentialité (plan p.7, « Difficultés identifiées ») :
« Aucun numéro de téléphone stocké en clair — hachage vérifié en base ».

On n'a pas confiance en une relecture du code : on inspecte réellement
chaque colonne texte de chaque table, pour toutes les tables du schéma,
et on vérifie qu'aucune ne contient le numéro (ni le destinataire) en
clair, où qu'il aurait pu être oublié par erreur."""

from sqlalchemy import inspect, text

from api import models
from api.security import hacher_numero

NUMERO_ABONNE = "+237690001234"
NUMERO_DESTINATAIRE = "+237677005566"


def _toutes_les_valeurs_textuelles(db) -> list[str]:
    """Parcourt chaque table du schéma, chaque colonne de type texte, et
    renvoie toutes les valeurs trouvées — pour une vérification exhaustive
    plutôt qu'une vérification limitée aux colonnes qu'on pense connaître."""
    moteur = db.get_bind()
    inspecteur = inspect(moteur)
    valeurs: list[str] = []
    for nom_table in inspecteur.get_table_names():
        colonnes = [c["name"] for c in inspecteur.get_columns(nom_table)]
        for ligne in db.execute(text(f"SELECT * FROM {nom_table}")).fetchall():
            for nom_colonne, valeur in zip(colonnes, ligne):
                if isinstance(valeur, str):
                    valeurs.append(valeur)
    return valeurs


def test_le_numero_de_l_abonne_n_apparait_jamais_en_clair(client):
    from api.database import SessionLocal

    inscription = client.post("/users/register", json={"phone_number": NUMERO_ABONNE})
    user_id = inscription.json()["user_id"]

    # Une transaction et une alerte, pour peupler un maximum de tables.
    client.put(f"/users/{user_id}/settings", json={"plafond": 1000})
    client.post("/transactions/score", json={
        "user_id": user_id, "amount": 500_000, "type": "TRANSFER", "hour": 14,
        "step": 14, "name_dest": NUMERO_DESTINATAIRE,
    })
    client.post("/ussd", data={"sessionId": "conf-1", "phoneNumber": NUMERO_ABONNE, "text": "1"})

    db = SessionLocal()
    try:
        toutes_valeurs = _toutes_les_valeurs_textuelles(db)
    finally:
        db.close()

    for valeur in toutes_valeurs:
        assert NUMERO_ABONNE not in valeur
        assert NUMERO_DESTINATAIRE not in valeur


def test_le_hash_stocke_correspond_bien_a_la_fonction_de_hachage_officielle(client):
    from api.database import SessionLocal

    client.post("/users/register", json={"phone_number": NUMERO_ABONNE})

    db = SessionLocal()
    try:
        user = db.query(models.User).filter_by(telephone_hash=hacher_numero(NUMERO_ABONNE)).first()
        assert user is not None
        assert len(user.telephone_hash) == 64  # sha256 hexdigest
        assert user.telephone_hash != NUMERO_ABONNE
    finally:
        db.close()


def test_le_destinataire_d_une_transaction_est_hache(abonne, client):
    from api.database import SessionLocal

    client.post("/transactions/score", json={
        "user_id": abonne, "amount": 1000, "type": "PAYMENT", "hour": 10,
        "step": 10, "name_dest": NUMERO_DESTINATAIRE,
    })

    db = SessionLocal()
    try:
        transaction = db.query(models.Transaction).order_by(models.Transaction.id.desc()).first()
        assert transaction is not None
        assert transaction.destinataire_hash == hacher_numero(NUMERO_DESTINATAIRE)
        assert NUMERO_DESTINATAIRE not in transaction.destinataire_hash
    finally:
        db.close()
