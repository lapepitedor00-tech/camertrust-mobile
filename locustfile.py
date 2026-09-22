"""
CamerTrust — E2 — Test de charge (plan p.9, checklist : « latence < 2 s
en charge »)
==============================================================================

Usage (interface web, par défaut sur http://localhost:8089) :

    locust -f locustfile.py --host http://localhost:8000

Ou en ligne de commande, sans interface, pour un rapport HTML autonome :

    locust -f locustfile.py --host http://localhost:8000 \\
        --headless -u 20 -r 5 -t 1m --html rapport_charge.html

Chaque utilisateur virtuel simule un abonné réel : inscription une fois,
puis une boucle de transactions représentatives (majoritairement
normales, occasionnellement au-dessus du plafond pour exercer aussi le
chemin « alerte »).
"""

from __future__ import annotations

import random

from locust import HttpUser, between, task


class AbonneCamerTrust(HttpUser):
    wait_time = between(0.5, 2.0)

    def on_start(self) -> None:
        self.numero = f"+2376{random.randint(10_000_000, 99_999_999)}"
        r = self.client.post("/users/register", json={"phone_number": self.numero}, name="/users/register")
        self.user_id = r.json()["user_id"] if r.status_code == 201 else None

    @task(10)
    def transaction_normale(self) -> None:
        if not self.user_id:
            return
        self.client.post(
            "/transactions/score",
            json={
                "user_id": self.user_id,
                "amount": random.randint(500, 20_000),
                "type": random.choice(["PAYMENT", "CASH_OUT", "TRANSFER"]),
                "hour": random.randint(7, 21),
                "step": random.randint(1, 500),
            },
            name="/transactions/score (normale)",
        )

    @task(1)
    def transaction_suspecte(self) -> None:
        if not self.user_id:
            return
        self.client.post(
            "/transactions/score",
            json={
                "user_id": self.user_id,
                "amount": random.randint(600_000, 2_000_000),
                "type": "TRANSFER",
                "hour": random.choice([1, 2, 3, 23]),
                "step": random.randint(1, 500),
            },
            name="/transactions/score (suspecte)",
        )

    @task(3)
    def consulter_score_confiance(self) -> None:
        if not self.user_id:
            return
        self.client.get(f"/users/{self.user_id}/trustscore", name="/users/{id}/trustscore")

    @task(2)
    def naviguer_ussd(self) -> None:
        if not self.user_id:
            return
        self.client.post(
            "/ussd",
            data={"sessionId": f"charge-{self.user_id}", "phoneNumber": self.numero, "text": ""},
            name="/ussd (menu racine)",
        )
