"""Configuration pytest partagée : base de données de test isolée, remise
à zéro avant chaque test pour ne jamais dépendre de l'ordre d'exécution."""

from __future__ import annotations

import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

CHEMIN_DB_TEST = RACINE / "test_camertrust.db"
os.environ["DATABASE_URL"] = f"sqlite:///{CHEMIN_DB_TEST}"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from api.database import Base, engine  # noqa: E402
from api.main import app  # noqa: E402


@pytest.fixture()
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def abonne(client):
    """Un abonné déjà inscrit, avec des réglages par défaut — pratique
    pour les tests qui n'ont pas besoin de re-tester l'inscription elle-même."""
    r = client.post("/users/register", json={"phone_number": "+237690000001"})
    assert r.status_code == 201
    return r.json()["user_id"]
