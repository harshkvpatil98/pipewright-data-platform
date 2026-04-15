FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1     PYTHONUNBUFFERED=1     PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY packages /app/packages
COPY services /app/services
COPY apps/api-gateway /app/apps/api-gateway
COPY scripts /app/scripts
COPY .env.example /app/.env.example

RUN pip install --upgrade pip     && pip install -e /app/packages/shared-python     && pip install -e /app/services/service-projects     && pip install -e /app/services/service-sources     && pip install -e /app/services/service-datasets     && pip install -e /app/services/service-auth     && pip install -e /app/services/service-pipeline-runs     && pip install -e /app/services/service-comparisons     && pip install -e /app/services/service-destinations     && pip install -e /app/services/service-ingestion     && pip install -e /app/services/service-transformations     && pip install -e '/app/apps/api-gateway[dev]'

WORKDIR /app/apps/api-gateway

EXPOSE 8000

CMD ["uvicorn", "api_gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]
