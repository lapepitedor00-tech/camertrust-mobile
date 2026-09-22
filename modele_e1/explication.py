"""
CamerTrust — E1 — `explication.py`
=====================================

Livrable explicitement demandé par la checklist de validation E1 (plan
p.6) : « `explication.py` : toute transaction scorée renvoie un motif de
moins de 120 caractères en français ». C'est le point d'entrée qu'E2 doit
utiliser — pas `camertrust_e1.py` directement — pour rester découplé des
détails internes du modèle (E2 n'a besoin de connaître que la fonction
`expliquer()` ci-dessous et le fichier `model_info.json`).

Usage typique côté E2 :

    from explication import expliquer

    motif = expliquer(
        transaction={"step": 26, "amount": 450000, "type": "TRANSFER", "nameDest": "M99"},
        historique_compte={
            "montant_moyen": 45000,
            "heures_habituelles": [8, 9, 10],
            "destinataires_connus": ["M12", "M45"],
            "nb_transactions_7j": 5,
        },
    )
    # -> "transaction destinataire que vous n'avez jamais utilise et montant..."  (< 120 caractères)

En ligne de commande (utile pour un test rapide sans écrire de code) :

    python explication.py --amount 450000 --step 26 --type TRANSFER --dest M99
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from camertrust_e1 import (
    FEATURES,
    charger_pipeline,
    construire_vecteur_transaction,
    expliquer_transaction,
)

_DOSSIER_MODELE = Path(__file__).resolve().parent.parent / "models"
_PIPELINE_PAR_DEFAUT = _DOSSIER_MODELE / "pipeline_complet.pkl"
_MODEL_INFO_PAR_DEFAUT = _DOSSIER_MODELE / "model_info.json"

_explainer_shap = None  # chargé paresseusement, seulement si demandé (voir `expliquer`)


def _charger_seuil_production(chemin_model_info: Path = _MODEL_INFO_PAR_DEFAUT) -> float:
    if chemin_model_info.exists():
        info = json.loads(chemin_model_info.read_text(encoding="utf-8"))
        return float(info.get("threshold", 0.5))
    return 0.5


def scorer_et_expliquer(
    transaction: dict,
    historique_compte: dict | None = None,
    pipeline=None,
    seuil: float | None = None,
) -> dict:
    """Fonction complète livrée à E2 : score la transaction ET renvoie le
    motif en français. C'est l'équivalent Python de l'endpoint
    `POST /transactions/score` d'E2 — E2 peut soit appeler cette fonction
    directement (déploiement dans le même processus), soit s'en inspirer
    pour construire son propre appel au pipeline.
    """
    if pipeline is None:
        pipeline = charger_pipeline(_PIPELINE_PAR_DEFAUT)
    if seuil is None:
        seuil = _charger_seuil_production()

    import pandas as pd

    vecteur = construire_vecteur_transaction(transaction, historique_compte)
    x = pd.DataFrame([{f: vecteur.get(f, 0) for f in FEATURES}])
    proba = float(pipeline.predict_proba(x)[0][1])
    est_fraude = proba >= seuil

    motif = expliquer(transaction, historique_compte) if est_fraude else ""

    return {
        "is_fraud": bool(est_fraude),
        "score": round(proba, 4),
        "motif": motif,
        "seuil_utilise": seuil,
    }


def expliquer(transaction: dict, historique_compte: dict | None = None, utiliser_shap: bool = False) -> str:
    """Renvoie le motif en français (< 120 caractères) pour UNE
    transaction. Ne fait AUCUN scoring — c'est `scorer_et_expliquer` qui
    combine les deux si besoin.

    `utiliser_shap=True` calcule les 2 variables les plus contributives
    avec SHAP (plus fidèle au modèle, mais plus lent — voir notebook 07) ;
    par défaut, on applique les règles métier simplifiées recommandées par
    le plan pour la production (p.4, « SHAP trop lent »).
    """
    vecteur = construire_vecteur_transaction(transaction, historique_compte)

    explainer = None
    if utiliser_shap:
        global _explainer_shap
        if _explainer_shap is None:
            import shap

            pipeline = charger_pipeline(_PIPELINE_PAR_DEFAUT)
            modele = pipeline.named_steps["modele"] if hasattr(pipeline, "named_steps") else pipeline
            _explainer_shap = shap.TreeExplainer(modele)
        explainer = _explainer_shap

    return expliquer_transaction(vecteur, explainer=explainer)


def _cli() -> None:
    parser = argparse.ArgumentParser(description="Teste rapidement expliquer() en ligne de commande.")
    parser.add_argument("--amount", type=float, required=True)
    parser.add_argument("--step", type=int, required=True)
    parser.add_argument("--type", dest="type_op", default="TRANSFER")
    parser.add_argument("--dest", dest="name_dest", default="INCONNU")
    parser.add_argument("--montant-moyen", type=float, default=None, help="Si fourni, simule un compte avec historique")
    args = parser.parse_args()

    transaction = {"step": args.step, "amount": args.amount, "type": args.type_op, "nameDest": args.name_dest}
    historique = None
    if args.montant_moyen is not None:
        historique = {
            "montant_moyen": args.montant_moyen,
            "heures_habituelles": [8, 9, 10, 18, 19],
            "destinataires_connus": [],
            "nb_transactions_7j": 3,
        }

    motif = expliquer(transaction, historique)
    print(f"Motif ({len(motif)} caractères) : {motif}")


if __name__ == "__main__":
    _cli()
