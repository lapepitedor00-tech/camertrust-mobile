"""
CamerTrust — E2 — Intégration du modèle d'E1
================================================

Point de couture entre E1 et E2 : charge `pipeline_complet.pkl` et
`model_info.json` livrés par E1 (dossier `modele_e1/`), reconstruit
l'historique de compte nécessaire à `construire_vecteur_transaction`, et
applique l'ordre d'évaluation exigé par le plan (p.8, S7) :

    liste blanche  →  plafond personnel  →  modèle ML

Mode dégradé (plan p.8, S8 : « le service répond même sans modèle
chargé ») : si `pipeline_complet.pkl` est absent, corrompu, ou que son
chargement échoue pour toute autre raison, `PIPELINE` reste `None` et
`scorer_transaction` bascule automatiquement sur les seules règles
(liste blanche + plafond) — le service ne plante jamais, il répond avec
`degraded_mode: true`.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from collections import Counter
from pathlib import Path

from sqlalchemy.orm import Session

from . import models
from .security import hacher_numero

logger = logging.getLogger("camertrust.scoring")

DOSSIER_MODELE = Path(__file__).resolve().parent.parent / "modele_e1"
sys.path.insert(0, str(DOSSIER_MODELE))  # pour `import camertrust_e1`

try:
    import camertrust_e1 as ce1  # module livré par E1
except ImportError:  # pragma: no cover - ne devrait pas arriver si modele_e1/ est bien livré
    ce1 = None
    logger.error("camertrust_e1.py introuvable dans %s — le scoring tournera en mode dégradé pur.", DOSSIER_MODELE)


def _charger_pipeline():
    chemin_pipeline = DOSSIER_MODELE / "pipeline_complet.pkl"
    chemin_info = DOSSIER_MODELE / "model_info.json"
    if not chemin_pipeline.exists() or not chemin_info.exists() or ce1 is None:
        logger.warning("Modèle d'E1 introuvable (%s) — démarrage en MODE DÉGRADÉ.", DOSSIER_MODELE)
        return None, None
    try:
        pipeline = ce1.charger_pipeline(chemin_pipeline)
        info = json.loads(chemin_info.read_text(encoding="utf-8"))
        logger.info("Pipeline E1 chargé : seuil=%s, %d features.", info.get("threshold"), len(info.get("features", [])))
        return pipeline, info
    except Exception:  # noqa: BLE001 — n'importe quelle erreur de chargement -> mode dégradé, jamais un crash au démarrage
        logger.exception("Échec du chargement du pipeline d'E1 — démarrage en MODE DÉGRADÉ.")
        return None, None


PIPELINE, MODEL_INFO = _charger_pipeline()


def recharger_modele() -> None:
    """Permet de recharger le modèle sans redémarrer le service (utile
    après le dépôt d'un nouveau `pipeline_complet.pkl` par E1, S12) —
    exposé aussi pour les tests du mode dégradé."""
    global PIPELINE, MODEL_INFO
    PIPELINE, MODEL_INFO = _charger_pipeline()


def modele_disponible() -> bool:
    return PIPELINE is not None and MODEL_INFO is not None


def calculer_historique_compte(db: Session, user: models.User, step_courant: int) -> dict | None:
    """Reconstruit, à partir de la table `transactions`, le résumé
    d'historique attendu par `camertrust_e1.construire_vecteur_transaction`
    (montant moyen, heures habituelles, destinataires connus, activité
    récente). Renvoie `None` pour un compte sans aucune transaction
    antérieure (E1 traite alors le cas comme un compte neuf).

    `heures_habituelles` reprend EXACTEMENT la définition d'E1
    (`SEUIL_PROPORTION_HEURE_HABITUELLE`) pour rester cohérent avec le
    calcul fait en traitement par lot côté E1 — voir le README pour cette
    réconciliation.
    """
    transactions = (
        db.query(models.Transaction)
        .filter(models.Transaction.user_id == user.id)
        .order_by(models.Transaction.step)
        .all()
    )
    if not transactions:
        return None

    montants = [t.montant for t in transactions]
    montant_moyen = sum(montants) / len(montants)

    compteur_heures = Counter(t.step % 24 for t in transactions)
    total = len(transactions)
    seuil = ce1.SEUIL_PROPORTION_HEURE_HABITUELLE if ce1 else 0.10
    heures_habituelles = [h for h in range(24) if _proportion_fenetre(compteur_heures, h, total) >= seuil]

    destinataires_connus = list({t.destinataire_hash for t in transactions})
    fenetre = ce1.FENETRE_7J_EN_HEURES if ce1 else 7 * 24
    nb_transactions_7j = sum(1 for t in transactions if t.step > step_courant - fenetre)

    return {
        "montant_moyen": montant_moyen,
        "heures_habituelles": heures_habituelles,
        "destinataires_connus": destinataires_connus,
        "nb_transactions_7j": nb_transactions_7j,
    }


def _proportion_fenetre(compteur_heures: Counter, heure: int, total: int) -> float:
    """Même logique de fenêtre ±3h que `camertrust_e1._historique_compte`."""
    dans_la_fenetre = sum(compteur_heures.get((heure + delta) % 24, 0) for delta in range(-3, 4))
    return dans_la_fenetre / total if total else 0.0


def _formater_heure_texte(heure: int) -> str:
    if 0 <= heure <= 5 or heure >= 22:
        return "la nuit"
    return f"a {heure:02d}h00"


class ResultatScoring:
    def __init__(self, is_fraud: bool, score: float, motif: str, latence_ms: float, degraded_mode: bool = False):
        self.is_fraud = is_fraud
        self.score = score
        self.motif = motif
        self.latence_ms = latence_ms
        self.degraded_mode = degraded_mode


def scorer_transaction(
    db: Session,
    user: models.User,
    reglages: models.Settings,
    montant: float,
    type_operation: str,
    heure: int,
    step: int,
    destinataire_hash: str | None,
) -> ResultatScoring:
    """Applique l'ordre d'évaluation du plan (p.8) : liste blanche →
    plafond personnel → modèle ML. Chaque étape court-circuite la
    suivante — c'est délibéré (un destinataire de confiance ne doit
    jamais être bloqué même si le modèle le jugerait suspect)."""
    t0 = time.perf_counter()

    # 1. Liste blanche — jamais d'alerte pour un destinataire déjà approuvé
    if destinataire_hash and destinataire_hash in (reglages.liste_blanche or []):
        return ResultatScoring(False, 0.0, "", _duree_ms(t0))

    # 2. Plafond personnel (jour ou nuit selon l'heure)
    plafond_applicable = reglages.plafond_nocturne if (heure <= 5 or heure >= 22) else reglages.plafond
    if montant > plafond_applicable:
        motif = f"montant {montant:,.0f} FCFA au-dessus de votre plafond ({plafond_applicable:,.0f} FCFA)".replace(",", " ")
        return ResultatScoring(True, 1.0, motif[:120], _duree_ms(t0))

    # 3. Modèle ML (ou repli en mode dégradé)
    if not modele_disponible():
        return _scoring_degrade(montant, heure, reglages, t0)

    historique = calculer_historique_compte(db, user, step)
    vecteur = ce1.construire_vecteur_transaction(
        {"step": step, "amount": montant, "type": type_operation, "nameDest": destinataire_hash or "INCONNU"},
        historique,
    )
    import pandas as pd

    x = pd.DataFrame([{f: vecteur.get(f, 0) for f in MODEL_INFO["features"]}])
    proba = float(PIPELINE.predict_proba(x)[0][1])
    seuil = float(MODEL_INFO["threshold"])
    est_fraude = proba >= seuil

    motif = ce1.expliquer_transaction(vecteur) if est_fraude else ""
    return ResultatScoring(est_fraude, round(proba, 4), motif, _duree_ms(t0))


SEUIL_DEGRADE_MONTANT_NUIT = 200_000  # FCFA — seuil fixe et volontairement grossier


def _scoring_degrade(montant: float, heure: int, reglages: models.Settings, t0: float) -> ResultatScoring:
    """Repli sans modèle : seule une règle simple (montant élevé la nuit)
    s'applique, documentée comme dégradée. Le seuil est FIXE et
    indépendant du plafond personnel (celui-ci a déjà été vérifié à
    l'étape précédente — une transaction qui arrive ici est forcément
    sous le plafond de l'abonné) : c'est un filet de sécurité minimal,
    pas une règle de gestion. Toujours mieux qu'un service qui ne répond
    plus (plan p.8, checklist : « mode dégradé testé »)."""
    nuit = heure <= 5 or heure >= 22
    est_fraude = nuit and montant > SEUIL_DEGRADE_MONTANT_NUIT
    motif = "montant tres eleve la nuit (mode degrade, modele indisponible)" if est_fraude else ""
    return ResultatScoring(est_fraude, 1.0 if est_fraude else 0.0, motif[:120], _duree_ms(t0), degraded_mode=True)


def _duree_ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 2)
