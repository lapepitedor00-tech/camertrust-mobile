# CamerTrust — E2 — Image de l'API (plan p.9, snippet de référence)
FROM python:3.11-slim

WORKDIR /app

# Dépendances système minimales pour psycopg2 et xgboost/shap (compilation native)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api ./api
COPY modele_e1 ./modele_e1
COPY alembic ./alembic
COPY alembic.ini .

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
