"""
CamerTrust — E1 — Module de détection de fraude
==================================================

Module réutilisé par tous les notebooks (01 à 09). Il concentre toute la
logique métier — chargement des données, ingénierie des variables de
profil comportemental, entraînement, évaluation par seuil, explicabilité,
export du pipeline, boucle de retour — pour que chaque notebook reste
court et lisible (le jury pose des questions sur chaque ligne : mieux vaut
des fonctions nommées et testées qu'un notebook monolithique).

Livré à E2 : `pipeline_complet.pkl` (voir `construire_pipeline_complet` /
`sauvegarder_pipeline`) et `model_info.json` (voir `generer_model_info`).
E2 doit construire, pour chaque transaction, EXACTEMENT le même vecteur de
variables que celui décrit par `FEATURES` et `model_info.json` — c'est le
contrat à faire valider avec E2 (voir README).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.model_selection import GridSearchCV, StratifiedKFold, cross_val_score, train_test_split
from sklearn.pipeline import Pipeline

# ---------------------------------------------------------------------------
# Colonnes attendues (schéma PaySim) et variables de profil comportemental
# ---------------------------------------------------------------------------
COLONNES_PAYSIM = [
    "step", "type", "amount", "nameOrig", "oldbalanceOrg", "newbalanceOrig",
    "nameDest", "oldbalanceDest", "newbalanceDest", "isFraud", "isFlaggedFraud",
]

TYPES_OPERATION = ["CASH_IN", "CASH_OUT", "DEBIT", "PAYMENT", "TRANSFER"]

# Les 3 variables de profil comportemental exigées par le plan (p.4), plus
# les variables de contexte qui les accompagnent. C'est cette liste, dans
# cet ordre, qui doit apparaître dans `model_info.json`.
FEATURES = [
    "amount",
    "heure",
    "ecart_montant_moyen",
    "heure_inhabituelle",
    "destinataire_jamais_vu",
    "nb_transactions_compte_7j",
    "compte_nouveau",
    "type_CASH_IN",
    "type_CASH_OUT",
    "type_DEBIT",
    "type_PAYMENT",
    "type_TRANSFER",
]

FENETRE_7J_EN_HEURES = 7 * 24  # `step` = 1 heure, comme dans PaySim réel
SEUIL_PROPORTION_HEURE_HABITUELLE = 0.10  # en dessous, l'heure est jugée inhabituelle pour ce compte

# Traduction variable -> motif en français, utilisée par `expliquer_transaction`.
# Tenue à jour manuellement (pas par SHAP) car ce sont des phrases destinées
# à un abonné, pas des noms de variables : voir plan p.4, "Nouveau — Traduction
# métier".
MOTIFS_TRADUCTION = {
    "amount": "montant {valeur:,.0f} FCFA, largement au-dessus de vos habitudes",
    "heure": "transaction {heure_txt}, inhabituelle pour vous",
    "ecart_montant_moyen": "montant {ratio:.1f} fois supérieur à votre moyenne habituelle",
    "heure_inhabituelle": "transaction {heure_txt}, inhabituelle pour vous",
    "destinataire_jamais_vu": "destinataire que vous n'avez jamais utilisé",
    "nb_transactions_compte_7j": "activité inhabituellement élevée sur votre compte cette semaine",
    "compte_nouveau": "compte récent, encore peu d'historique pour vous connaître",
    "type_TRANSFER": "un transfert",
    "type_CASH_OUT": "un retrait",
}

LONGUEUR_MAX_MOTIF = 120  # caractères — contrainte SMS du plan (p.4 et p.18)


# ---------------------------------------------------------------------------
# 1. Chargement
# ---------------------------------------------------------------------------
def charger_paysim(chemin: str | Path) -> pd.DataFrame:
    """Charge le CSV PaySim (réel ou synthétique) et vérifie le schéma.

    Lève une erreur explicite si une colonne attendue manque, plutôt que de
    laisser une KeyError sortir plus loin dans le pipeline.
    """
    df = pd.read_csv(chemin)
    colonnes_manquantes = set(COLONNES_PAYSIM) - set(df.columns)
    if colonnes_manquantes:
        raise ValueError(
            f"Colonnes PaySim manquantes dans {chemin} : {sorted(colonnes_manquantes)}. "
            "Vérifiez que le fichier téléchargé est bien PaySim (Kaggle : ealaxi/paysim1)."
        )
    # Colonnes techniques éventuellement présentes dans un jeu de test
    # synthétique (voir scripts/generer_donnees_test.py) : jamais dans le
    # vrai PaySim, à retirer si présentes.
    colonnes_techniques = [c for c in df.columns if c.startswith("_")]
    if colonnes_techniques:
        df = df.drop(columns=colonnes_techniques)
    return df


# Emplacements usuels du fichier une fois téléchargé depuis Kaggle
# (https://www.kaggle.com/datasets/ealaxi/paysim1) — le nom exact du fichier
# distribué par Kaggle est `PS_20174392719_1491204439457_log.csv`, mais la
# plupart des gens le renomment `PaySim.csv` après téléchargement. Les deux
# noms sont donc reconnus, en local comme dans `/content` (Google Colab).
CHEMINS_PAYSIM_PAR_DEFAUT = [
    "data/PaySim.csv",
    "data/PS_20174392719_1491204439457_log.csv",
    "/content/PaySim.csv",
    "/content/PS_20174392719_1491204439457_log.csv",
    "../data/PaySim.csv",
    "../data/PS_20174392719_1491204439457_log.csv",
]


def charger_paysim_ou_repli(
    chemins: list[str] = CHEMINS_PAYSIM_PAR_DEFAUT,
    chemin_synthetique: str = "data/paysim_synthetique.csv",
) -> tuple[pd.DataFrame, bool]:
    """Charge le vrai PaySim s'il est trouvé à l'un des emplacements
    usuels ; sinon, replie sur un jeu synthétique structurellement
    identique (voir `scripts/generer_donnees_test.py`) pour que les
    notebooks restent exécutables de bout en bout AVANT que PaySim ne soit
    téléchargé.

    C'est cette fonction qui permet à E1 de développer/tester tout le
    pipeline sans attendre le téléchargement (470 Mo) : il suffit ensuite
    de déposer `PaySim.csv` dans `data/` (ou `/content/` sur Colab) et de
    relancer les notebooks pour basculer automatiquement sur les vraies
    données — aucune autre modification n'est nécessaire.

    Retourne `(dataframe, utilise_vrai_paysim)`.
    """
    for chemin in chemins:
        if Path(chemin).exists():
            return charger_paysim(chemin), True

    if Path(chemin_synthetique).exists():
        print(
            "⚠️  PaySim introuvable (voir CHEMINS_PAYSIM_PAR_DEFAUT) — "
            f"utilisation du jeu de test synthétique existant : {chemin_synthetique}\n"
            "   Téléchargez PaySim (kaggle.com/datasets/ealaxi/paysim1), "
            "placez-le dans data/, puis relancez ce notebook."
        )
        return charger_paysim(chemin_synthetique), False

    print(
        "⚠️  PaySim introuvable et aucun jeu de test existant — génération "
        "d'un jeu synthétique à la volée (voir scripts/generer_donnees_test.py).\n"
        "   Téléchargez PaySim (kaggle.com/datasets/ealaxi/paysim1), "
        "placez-le dans data/, puis relancez ce notebook."
    )
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from generer_donnees_test import generer_paysim_synthetique

    df = generer_paysim_synthetique()
    Path(chemin_synthetique).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(chemin_synthetique, index=False)
    return df, False


# ---------------------------------------------------------------------------
# 2. Ingénierie des variables de profil comportemental
# ---------------------------------------------------------------------------
MULTIPLICATEUR_CLE_FENETRE = 10**9  # marge très large devant `step` (PaySim : 1 à 744)


def calculer_variables_profil(df: pd.DataFrame) -> pd.DataFrame:
    """Ajoute au DataFrame les variables de profil comportemental par
    compte (plan p.4, point (1) « profil comportemental ») :

    - `ecart_montant_moyen` : montant / moyenne historique du compte.
    - `heure_inhabituelle` : 1 si moins de `SEUIL_PROPORTION_HEURE_HABITUELLE`
      de l'historique du compte tombe dans une fenêtre +/-3h autour de
      l'heure courante.
    - `destinataire_jamais_vu` : 1 si ce destinataire n'a jamais reçu
      d'argent de ce compte auparavant.
    - `nb_transactions_compte_7j` : activité récente du compte (7 jours).
    - `compte_nouveau` : 1 pour la toute première transaction d'un compte
      (aucun historique disponible).

    Le calcul est strictement causal (aucune fuite du futur) : chaque ligne
    n'utilise que les transactions antérieures du même compte -- jamais le
    futur, sinon les métriques seraient optimistes et invérifiables en
    production.

    Cas du compte neuf (plan p.4, « Difficultés identifiées ») : la toute
    première transaction d'un compte n'a par définition aucun historique.
    On ne pénalise pas ce cas par une valeur extrême -- `ecart_montant_moyen`
    vaut 1.0 (neutre) et `heure_inhabituelle` vaut 0 -- mais on le signale
    explicitement via `compte_nouveau`.

    Implémentation entièrement vectorisée (NumPy/pandas), sans boucle
    Python sur les comptes : une première version bouclait explicitement
    sur chaque groupe `nameOrig` puis, à l'intérieur, sur chaque ligne
    (`.iterrows()`) -- largement assez rapide sur le petit jeu synthétique
    de développement, mais rédhibitoire sur le vrai PaySim (6,3 M lignes,
    ~8 M comptes distincts, la plupart à 1-2 transactions) : le coût n'est
    pas le calcul lui-même mais les millions d'appels Python et de petits
    objets pandas créés par la boucle. Voir
    `reports/note_optimisation_performance.md` pour la mesure avant/après
    et la preuve d'équivalence des résultats.
    """
    df = df.copy()
    df["heure"] = (df["step"] % 24).astype(int)

    index_original = df.index
    df_trie = df.sort_values(["nameOrig", "step"], kind="mergesort").reset_index(drop=False)
    n = len(df_trie)

    montants = df_trie["amount"].to_numpy(dtype=float)
    steps = df_trie["step"].to_numpy(dtype=np.int64)
    heures = df_trie["heure"].to_numpy(dtype=np.int64)

    grp_compte = df_trie.groupby("nameOrig", sort=False)
    group_ids = grp_compte.ngroup().to_numpy()
    position_dans_groupe = grp_compte.cumcount().to_numpy()  # 0 = première transaction du compte
    compte_nouveau = (position_dans_groupe == 0).astype(int)
    nb_transactions_avant = np.maximum(position_dans_groupe, 1)  # dénominateur sûr (évite la division par 0)

    # --- ecart_montant_moyen : moyenne cumulée du compte, décalée d'un cran
    # (on ne doit jamais inclure la transaction courante dans "l'historique").
    cumsum_montant_inclus = grp_compte["amount"].cumsum().to_numpy()
    cumsum_montant_avant = cumsum_montant_inclus - montants
    with np.errstate(divide="ignore", invalid="ignore"):
        moyenne_avant = cumsum_montant_avant / nb_transactions_avant
        ecart_brut = montants / moyenne_avant
    ecart_montant_moyen = np.where((position_dans_groupe > 0) & (moyenne_avant > 0), ecart_brut, 1.0)

    # --- destinataire_jamais_vu : première apparition chronologique du
    # couple (compte, destinataire) -- équivalent exact de "ce destinataire
    # n'a jamais reçu d'argent de ce compte avant cette ligne".
    est_premiere_paire = df_trie.groupby(["nameOrig", "nameDest"], sort=False).cumcount().to_numpy() == 0
    destinataire_jamais_vu = est_premiere_paire.astype(int)

    # --- heure_inhabituelle : proportion de l'historique du compte tombant
    # dans une fenêtre +/-3h. Comme il n'y a que 24 heures possibles, on
    # matérialise un indicateur (n, 24) et on en prend le cumul PAR COMPTE
    # (décalé d'un cran) plutôt qu'un dictionnaire mis à jour ligne à ligne.
    indicateurs_heure = np.zeros((n, 24), dtype=np.int64)
    indicateurs_heure[np.arange(n), heures] = 1
    cumsum_heure_inclus = (
        pd.DataFrame(indicateurs_heure).groupby(df_trie["nameOrig"].to_numpy(), sort=False).cumsum().to_numpy()
    )
    cumsum_heure_avant = cumsum_heure_inclus - indicateurs_heure
    offsets_fenetre = np.arange(-3, 4)
    colonnes_fenetre = (heures[:, None] + offsets_fenetre[None, :]) % 24  # (n, 7), fenêtre circulaire
    transactions_dans_la_fenetre = np.take_along_axis(cumsum_heure_avant, colonnes_fenetre, axis=1).sum(axis=1)
    proportion_habituelle = transactions_dans_la_fenetre / nb_transactions_avant
    heure_inhabituelle = np.where(
        position_dans_groupe > 0,
        (proportion_habituelle < SEUIL_PROPORTION_HEURE_HABITUELLE).astype(int),
        0,
    )

    # --- nb_transactions_compte_7j : recherche binaire GLOBALE (une seule
    # fois pour tout le jeu de données, pas compte par compte). Astuce : en
    # encodant chaque ligne par `identifiant_compte * MULTIPLICATEUR + step`,
    # le tableau reste trié ET les comptes ne peuvent jamais "déborder" les
    # uns sur les autres tant que MULTIPLICATEUR est bien plus grand que
    # l'étendue des `step` (PaySim : 1 à 744) -- une seule passe
    # `np.searchsorted` retrouve alors, pour chaque ligne, le nombre de
    # transactions du MÊME compte dans les `FENETRE_7J_EN_HEURES` heures
    # précédentes, sans jamais parcourir les comptes un par un.
    cle_triee = group_ids.astype(np.int64) * MULTIPLICATEUR_CLE_FENETRE + steps
    cible_fenetre = group_ids.astype(np.int64) * MULTIPLICATEUR_CLE_FENETRE + (steps - FENETRE_7J_EN_HEURES)
    bornes_gauche = np.searchsorted(cle_triee, cible_fenetre, side="left")
    nb_transactions_compte_7j = np.arange(n) - bornes_gauche

    df_trie["ecart_montant_moyen"] = ecart_montant_moyen
    df_trie["heure_inhabituelle"] = heure_inhabituelle
    df_trie["destinataire_jamais_vu"] = destinataire_jamais_vu
    df_trie["compte_nouveau"] = compte_nouveau
    df_trie["nb_transactions_compte_7j"] = nb_transactions_compte_7j

    df_trie = df_trie.set_index("index")
    df_trie.index.name = None
    df = df_trie.loc[index_original]  # restaure l'ordre d'origine des lignes
    return encoder_type_operation(df)



def encoder_type_operation(df: pd.DataFrame) -> pd.DataFrame:
    """One-hot encode `type` en 5 colonnes fixes (`type_CASH_IN`, ...),
    toujours toutes présentes même si un type est absent du jeu de
    données — indispensable pour qu'E2 puisse construire un vecteur de
    même forme pour une seule transaction à la fois."""
    df = df.copy()
    type_norm = df["type"].str.replace("-", "_", regex=False)
    dummies = pd.get_dummies(type_norm, prefix="type")
    for colonne in [f"type_{t}" for t in TYPES_OPERATION]:
        if colonne not in dummies.columns:
            dummies[colonne] = 0
    dummies = dummies[[f"type_{t}" for t in TYPES_OPERATION]].astype(int)
    return pd.concat([df, dummies], axis=1)


def construire_vecteur_transaction(transaction: dict, historique_compte: dict | None = None) -> dict:
    """Construit, pour UNE transaction isolée (cas d'E2 en production : une
    transaction à la fois, pas un DataFrame), le même dictionnaire de
    variables que `calculer_variables_profil` produit en traitement par lot.

    `historique_compte` (optionnel) est un résumé déjà calculé et
    persistant côté E2 (montant moyen du compte, heures habituelles,
    destinataires déjà vus, nb transactions 7j) — c'est cette fonction qui
    matérialise la « fonction qui renvoie le vecteur de features » livrée
    à E2 (voir README, section intégration).

    `heures_habituelles` doit lister les heures couvrant au moins
    `SEUIL_PROPORTION_HEURE_HABITUELLE` (10 %) de l'historique du compte
    (pas simplement « déjà vues une fois »), pour rester cohérent avec la
    définition utilisée en traitement par lot (`_historique_compte`).

    Si `historique_compte` est `None`, la transaction est traitée comme un
    compte neuf (voir `compte_nouveau` dans `_historique_compte`).
    """
    heure = int(transaction["step"]) % 24
    if not historique_compte:
        vecteur = {
            "amount": float(transaction["amount"]),
            "heure": heure,
            "ecart_montant_moyen": 1.0,
            "heure_inhabituelle": 0,
            "destinataire_jamais_vu": 1,
            "nb_transactions_compte_7j": 0,
            "compte_nouveau": 1,
        }
    else:
        moyenne = historique_compte.get("montant_moyen", 0.0)
        heures_habituelles = set(historique_compte.get("heures_habituelles", []))
        destinataires_connus = set(historique_compte.get("destinataires_connus", []))
        vecteur = {
            "amount": float(transaction["amount"]),
            "heure": heure,
            "ecart_montant_moyen": float(transaction["amount"]) / moyenne if moyenne > 0 else 1.0,
            "heure_inhabituelle": 0 if any((heure + d) % 24 in heures_habituelles for d in range(-3, 4)) else 1,
            "destinataire_jamais_vu": 0 if transaction.get("nameDest") in destinataires_connus else 1,
            "nb_transactions_compte_7j": int(historique_compte.get("nb_transactions_7j", 0)),
            "compte_nouveau": 0,
        }
    type_norm = str(transaction["type"]).replace("-", "_")
    for t in TYPES_OPERATION:
        vecteur[f"type_{t}"] = int(type_norm == t)
    return vecteur


# ---------------------------------------------------------------------------
# 3. Prétraitement / split / SMOTE
# ---------------------------------------------------------------------------
@dataclass
class JeuDonnees:
    X_train: pd.DataFrame
    X_test: pd.DataFrame
    y_train: pd.Series
    y_test: pd.Series
    X_train_smote: pd.DataFrame = field(default=None)
    y_train_smote: pd.Series = field(default=None)


def preparer_jeu_entrainement(
    df: pd.DataFrame,
    features: list[str] = FEATURES,
    cible: str = "isFraud",
    taille_test: float = 0.25,
    graine: int = 42,
    appliquer_smote: bool = True,
    smote_sampling_strategy: float | str = "auto",
) -> JeuDonnees:
    """Split stratifié train/test, puis SMOTE **uniquement sur le jeu
    d'entraînement** (plan p.4 : « attention, n'applique SMOTE que sur le
    jeu d'entraînement, jamais sur le jeu de test, sinon les métriques sont
    faussées »). Le jeu de test garde donc la vraie proportion de fraude.

    `smote_sampling_strategy` contrôle le degré de rééquilibrage : `"auto"`
    (défaut, comportement historique) porte la classe minoritaire à 100 %
    de la classe majoritaire — parfait sur un petit jeu, mais sur le vrai
    PaySim (des millions de transactions légitimes) cela crée un jeu
    d'entraînement synthétique ÉNORME, qui ralentit fortement
    l'entraînement et la recherche d'hyperparamètres. Passer une valeur
    entre 0 et 1 (ex. `0.3`) limite la classe minoritaire à cette fraction
    de la majoritaire — un rééquilibrage partiel, nettement plus rapide,
    qui reste largement suffisant pour aider le modèle à apprendre la
    fraude (voir `reports/note_optimisation_performance.md`)."""
    X = df[features].fillna(0)
    y = df[cible].astype(int)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=taille_test, random_state=graine, stratify=y,
    )

    jeu = JeuDonnees(X_train=X_train, X_test=X_test, y_train=y_train, y_test=y_test)

    if appliquer_smote:
        from imblearn.over_sampling import SMOTE

        n_minoritaire = int(y_train.sum())
        k_voisins = max(1, min(5, n_minoritaire - 1))
        smote = SMOTE(random_state=graine, k_neighbors=k_voisins, sampling_strategy=smote_sampling_strategy)
        X_res, y_res = smote.fit_resample(X_train, y_train)
        jeu.X_train_smote, jeu.y_train_smote = X_res, y_res

    return jeu


# ---------------------------------------------------------------------------
# 4. Entraînement
# ---------------------------------------------------------------------------
def entrainer_random_forest(X_train, y_train, **kwargs) -> RandomForestClassifier:
    parametres = {"n_estimators": 200, "max_depth": 12, "random_state": 42, "n_jobs": -1, "class_weight": "balanced_subsample"}
    parametres.update(kwargs)
    modele = RandomForestClassifier(**parametres)
    modele.fit(X_train, y_train)
    return modele


def entrainer_xgboost(X_train, y_train, **kwargs):
    from xgboost import XGBClassifier

    scale_pos_weight = max(1.0, (len(y_train) - sum(y_train)) / max(1, sum(y_train)))
    parametres = {
        "n_estimators": 300, "max_depth": 6, "learning_rate": 0.1,
        "eval_metric": "logloss", "random_state": 42, "scale_pos_weight": scale_pos_weight,
    }
    parametres.update(kwargs)
    modele = XGBClassifier(**parametres)
    modele.fit(X_train, y_train)
    return modele


def optimiser_hyperparametres(estimateur, grille: dict, X_train, y_train, cv: int = 5, scoring: str = "f1"):
    recherche = GridSearchCV(estimateur, grille, cv=StratifiedKFold(cv), scoring=scoring, n_jobs=-1)
    recherche.fit(X_train, y_train)
    return recherche


# ---------------------------------------------------------------------------
# 5. Évaluation par seuil (coût du faux positif)
# ---------------------------------------------------------------------------
def evaluer_seuils(modele, X_test, y_test, seuils: list[float] = (0.3, 0.4, 0.5, 0.6, 0.7)) -> pd.DataFrame:
    """Pour chaque seuil de décision, calcule précision/rappel/F1 ET le
    nombre de fausses alertes pour 1000 transactions (plan p.4, point (3)
    « coût du faux positif » — chaque fausse alerte est un SMS inutile qui
    pousse l'abonné à se désinscrire)."""
    probabilites = modele.predict_proba(X_test)[:, 1]
    lignes = []
    for seuil in seuils:
        predictions = (probabilites >= seuil).astype(int)
        faux_positifs = int(((predictions == 1) & (y_test == 0)).sum())
        lignes.append({
            "seuil": seuil,
            "precision": precision_score(y_test, predictions, zero_division=0),
            "rappel": recall_score(y_test, predictions, zero_division=0),
            "f1": f1_score(y_test, predictions, zero_division=0),
            "faux_positifs": faux_positifs,
            "alertes_inutiles_pour_1000_tx": round(1000 * faux_positifs / len(y_test), 2),
        })
    return pd.DataFrame(lignes)


def calculer_courbe_roc(modele, X_test, y_test) -> dict:
    probabilites = modele.predict_proba(X_test)[:, 1]
    fpr, tpr, seuils = roc_curve(y_test, probabilites)
    auc = roc_auc_score(y_test, probabilites)
    return {"fpr": fpr, "tpr": tpr, "seuils": seuils, "auc": auc}


def metriques_globales(modele, X_test, y_test, seuil: float = 0.5) -> dict:
    probabilites = modele.predict_proba(X_test)[:, 1]
    predictions = (probabilites >= seuil).astype(int)
    return {
        "accuracy": accuracy_score(y_test, predictions),
        "precision": precision_score(y_test, predictions, zero_division=0),
        "rappel": recall_score(y_test, predictions, zero_division=0),
        "f1": f1_score(y_test, predictions, zero_division=0),
        "auc_roc": roc_auc_score(y_test, probabilites),
        "seuil": seuil,
    }


# ---------------------------------------------------------------------------
# 6. Explicabilité — motif en français, < 120 caractères
# ---------------------------------------------------------------------------
def _formater_montant(valeur: float) -> str:
    return f"{valeur:,.0f}".replace(",", " ")


def _formater_heure(heure: int) -> str:
    if 0 <= heure <= 5 or heure >= 22:
        return "la nuit"
    if 6 <= heure <= 9:
        return "tôt le matin"
    return "à une heure inhabituelle pour vous"


def expliquer_transaction(
    transaction_vecteur: dict,
    explainer=None,
    feature_names: list[str] = FEATURES,
    max_longueur: int = LONGUEUR_MAX_MOTIF,
) -> str:
    """Renvoie une phrase en français de moins de `max_longueur` caractères
    expliquant pourquoi une transaction a été jugée suspecte (plan p.4 :
    « chaque score s'accompagne des deux variables qui l'ont le plus fait
    monter, traduites en français simple »).

    Deux modes :
    - Si `explainer` (un `shap.TreeExplainer`) est fourni, les 2 variables
      les plus contributives SONT calculées par SHAP (voir notebook 07).
    - Sinon (repli documenté au plan p.4, « SHAP trop lent » / usage en
      production), on applique 3 règles métier fixes, dans l'ordre : compte
      neuf, destinataire jamais vu, écart de montant + heure inhabituelle.
    """
    if transaction_vecteur.get("compte_nouveau"):
        phrase = f"transaction de {_formater_montant(transaction_vecteur['amount'])} FCFA, compte recent sans historique"
        return phrase[:max_longueur]

    if explainer is not None:
        x = pd.DataFrame([{f: transaction_vecteur.get(f, 0) for f in feature_names}])
        valeurs_shap = explainer.shap_values(x)
        contributions = valeurs_shap[1][0] if isinstance(valeurs_shap, list) else valeurs_shap[0]
        ordre = np.argsort(-np.abs(contributions))[:2]
        variables_top = [feature_names[i] for i in ordre]
    else:
        variables_top = []
        if transaction_vecteur.get("destinataire_jamais_vu"):
            variables_top.append("destinataire_jamais_vu")
        if transaction_vecteur.get("heure_inhabituelle"):
            variables_top.append("heure_inhabituelle")
        if transaction_vecteur.get("ecart_montant_moyen", 1.0) >= 3 and "ecart_montant_moyen" not in variables_top:
            variables_top.append("ecart_montant_moyen")
        if not variables_top:
            variables_top = ["amount"]
        variables_top = variables_top[:2]

    morceaux = []
    for variable in variables_top:
        gabarit = MOTIFS_TRADUCTION.get(variable)
        if gabarit is None:
            continue
        morceaux.append(gabarit.format(
            valeur=transaction_vecteur.get("amount", 0),
            ratio=transaction_vecteur.get("ecart_montant_moyen", 1.0),
            heure_txt=_formater_heure(int(transaction_vecteur.get("heure", 12))),
        ))

    if not morceaux:
        morceaux = [f"montant de {_formater_montant(transaction_vecteur.get('amount', 0))} FCFA inhabituel"]

    phrase = "transaction " + " et ".join(morceaux)
    return phrase[:max_longueur]


# ---------------------------------------------------------------------------
# 7. Pipeline complet — export vers E2
# ---------------------------------------------------------------------------
def construire_pipeline_complet(modele, features: list[str] = FEATURES) -> Pipeline:
    """Assemble un `Pipeline` scikit-learn : imputation des valeurs
    manquantes (médiane — robuste au cas du compte neuf) + modèle entraîné.
    C'est ce pipeline, et lui seul, qu'E2 doit charger avec `joblib.load`."""
    imputeur = SimpleImputer(strategy="median")
    pipeline = Pipeline([("imputation", imputeur), ("modele", modele)])
    # Le modèle est déjà entraîné ; on "entraîne" seulement l'imputeur sur
    # des données factices de la bonne forme pour que le pipeline soit
    # directement utilisable (l'appelant doit malgré tout appeler
    # `pipeline.fit(X_train, y_train)` une fois avant l'export — voir
    # notebook 07 — pour que l'imputeur connaisse les vraies médianes).
    pipeline.features_ = features
    return pipeline


def sauvegarder_pipeline(pipeline, chemin: str | Path) -> None:
    joblib.dump(pipeline, chemin)


def charger_pipeline(chemin: str | Path):
    return joblib.load(chemin)


def generer_model_info(
    features: list[str],
    seuil: float,
    metriques: dict,
    motifs_disponibles: dict = MOTIFS_TRADUCTION,
    chemin: str | Path | None = None,
) -> dict:
    """Construit (et sauvegarde si `chemin` est fourni) `model_info.json`,
    le contrat lu dynamiquement par E2 (voir suivi de projet : E2 importe
    cette liste de `features` pour construire son vecteur — plutôt que de
    coder les noms en dur)."""
    info = {
        "features": features,
        "input_format": "vecteur numérique, une valeur par feature, dans l'ordre de `features`",
        "threshold": seuil,
        "metrics": metriques,
        "motifs": list(motifs_disponibles.keys()),
        "longueur_max_motif": LONGUEUR_MAX_MOTIF,
    }
    if chemin is not None:
        Path(chemin).write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    return info


# ---------------------------------------------------------------------------
# 8. Boucle de retour (feedback loop) — S9 et S12 du plan
# ---------------------------------------------------------------------------
def traiter_retours_utilisateurs(df_reponses: pd.DataFrame) -> pd.DataFrame:
    """Transforme les réponses des abonnés aux alertes (colonnes attendues :
    `alert_id`, `reponse` [1 = c'est moi, 2 = ce n'est pas moi], et les
    variables de la transaction d'origine) en nouvelles lignes étiquetées,
    directement utilisables pour ré-entraîner le modèle (plan p.5 :
    « script qui relit les réponses ' 1 / 2 ' des utilisateurs et les
    transforme en étiquettes »).

    Convention retenue : réponse « 2 » (ce n'est pas moi) confirme la
    fraude -> étiquette 1. Réponse « 1 » (c'est moi) infirme l'alerte ->
    étiquette 0 (faux positif confirmé par l'abonné lui-même).
    """
    if df_reponses.empty:
        return df_reponses.assign(isFraud=pd.Series(dtype=int))
    df = df_reponses.copy()
    df["isFraud"] = (df["reponse"] == 2).astype(int)
    return df.drop(columns=["reponse"])


def fusionner_pour_reentrainement(df_original: pd.DataFrame, df_retours_etiquetes: pd.DataFrame) -> pd.DataFrame:
    """Concatène le jeu PaySim d'origine et les nouvelles lignes issues de
    la boucle de retour, en ne gardant que les colonnes communes (features
    + `isFraud`) — utilisé par le notebook 09 puis en S12 pour le modèle v2."""
    colonnes_communes = [c for c in df_original.columns if c in df_retours_etiquetes.columns]
    if "isFraud" not in colonnes_communes:
        colonnes_communes.append("isFraud")
    return pd.concat(
        [df_original[colonnes_communes], df_retours_etiquetes[colonnes_communes]],
        ignore_index=True,
    )
