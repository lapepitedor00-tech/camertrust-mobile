"""
CamerTrust — E2 — Connexion base de données
==============================================

SQLite par défaut (aucune dépendance externe, pratique pour développer et
pour les tests), PostgreSQL en production via la variable d'environnement
`DATABASE_URL` (voir plan p.7 : « commence avec SQLite, migre vers
PostgreSQL ensuite » et `docker-compose.yml` à la racine du projet).
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./camertrust.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def obtenir_session():
    """Dépendance FastAPI : une session DB par requête, toujours fermée."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def creer_tables() -> None:
    """Crée les tables si elles n'existent pas encore. Pour une évolution
    de schéma en production, voir `alembic/` (migrations versionnées) —
    cette fonction sert surtout au démarrage local / tests."""
    from . import models  # noqa: F401 (enregistre les modèles sur Base.metadata)

    Base.metadata.create_all(bind=engine)
