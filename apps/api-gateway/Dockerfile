FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY packages /app/packages
COPY services /app/services
COPY apps/api-gateway /app/apps/api-gateway
COPY scripts /app/scripts
COPY .env.example /app/.env.example

# Every workspace, in the order scripts/ci-bootstrap-python-venv.sh uses: they
# depend on each other by name and are not on PyPI, so each must be installed
# before anything that needs it. (This image used to install ten of the 24
# services, so pip went looking on PyPI for the rest and the build failed.)
RUN pip install --upgrade pip \
    && for workspace in \
        packages/shared-python \
        services/service-auth \
        services/service-projects \
        services/service-access \
        services/service-sources \
        services/service-datasets \
        services/service-pipeline-runs \
        services/service-ingestion \
        services/service-comparisons \
        services/service-notifications \
        services/service-destinations \
        services/service-transformations \
        services/service-schedules \
        services/service-quality \
        services/service-extraction \
        services/service-writeback \
        services/service-workbench \
        services/service-enterprise \
        services/service-governance \
        services/service-connectors \
        services/service-observability \
        services/service-reporting \
        services/service-workflows \
        services/service-lineage \
        services/service-intelligence; \
      do pip install -e "/app/$workspace" || exit 1; done \
    && pip install -e /app/apps/api-gateway

WORKDIR /app/apps/api-gateway

# Stored files (uploads, datasets, versions) live under data/ unless
# STORAGE_BACKEND=s3. Mount a volume here, shared by the gateway, the worker and
# the ticker, or use a bucket.
VOLUME ["/app/apps/api-gateway/data"]

EXPOSE 8000

CMD ["uvicorn", "api_gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]
