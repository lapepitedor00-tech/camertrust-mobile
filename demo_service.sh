#!/usr/bin/env bash
# CamerTrust — E2 — Démo scriptée pour la soutenance
# =====================================================
# Rejoue le scénario complet du plan : inscription -> transaction
# suspecte -> alerte envoyée -> réponse de l'abonné -> déblocage (ou
# blocage réel, réversible) du compte.
#
# Prérequis : l'API tourne déjà (ex. `uvicorn api.main:app` ou
# `docker compose up`) et `jq` est installé.
#
# Usage : ./demo_service.sh [URL_API]
#   URL_API par défaut : http://localhost:8000

set -euo pipefail

API="${1:-http://localhost:8000}"
NUMERO="+237690$RANDOM"

etape() { echo; echo "=== $1 ==="; }

etape "0. Vérification de santé du service"
curl -sS "$API/health" | jq .

etape "1. Inscription de l'abonné $NUMERO"
INSCRIPTION=$(curl -sS -X POST "$API/users/register" \
    -H "Content-Type: application/json" \
    -d "{\"phone_number\": \"$NUMERO\"}")
echo "$INSCRIPTION" | jq .
USER_ID=$(echo "$INSCRIPTION" | jq -r .user_id)

etape "2. SMS de confirmation reçu (boîte de sortie simulée)"
# Important : le "+" d'un numéro international doit être encodé en
# requête GET (`curl -G --data-urlencode`), sinon les serveurs HTTP le
# décodent comme une espace (convention application/x-www-form-urlencoded)
# et la recherche par numéro ne trouve plus rien.
curl -sS -G --data-urlencode "phone_number=$NUMERO" "$API/outbox" | jq .

etape "3. On abaisse le plafond pour déclencher une alerte facilement (démo)"
curl -sS -X PUT "$API/users/$USER_ID/settings" \
    -H "Content-Type: application/json" \
    -d '{"plafond": 10000, "plafond_nocturne": 10000}' | jq .

etape "4. Transaction suspecte : virement de 500 000 FCFA"
SCORING=$(curl -sS -X POST "$API/transactions/score" \
    -H "Content-Type: application/json" \
    -d "{\"user_id\": \"$USER_ID\", \"amount\": 500000, \"type\": \"TRANSFER\", \"hour\": 14, \"step\": 14}")
echo "$SCORING" | jq .
ALERT_ID=$(echo "$SCORING" | jq -r .alert_id)

if [ "$ALERT_ID" = "null" ]; then
    echo "Aucune alerte générée — vérifier les réglages du compte." >&2
    exit 1
fi

etape "5. SMS d'alerte reçu par l'abonné"
curl -sS -G --data-urlencode "phone_number=$NUMERO" "$API/outbox" | jq '.[-1]'

etape "6. L'abonné répond « 2 » (ce n'est pas moi) -> blocage réel de 30 min"
curl -sS -X POST "$API/alerts/$ALERT_ID/respond" \
    -H "Content-Type: application/json" \
    -d '{"response": 2}' | jq .

etape "7. Le compte est bien bloqué (nouvelle transaction refusée)"
curl -sS -X POST "$API/transactions/score" \
    -H "Content-Type: application/json" \
    -d "{\"user_id\": \"$USER_ID\", \"amount\": 100, \"type\": \"PAYMENT\", \"hour\": 15, \"step\": 15}" | jq .

etape "8. Vue de la console de supervision (lue par E3)"
curl -sS "$API/admin/alerts?stats=1" | jq .

etape "Démo terminée. Voir README.md et DEPLOYMENT.md pour la suite."
