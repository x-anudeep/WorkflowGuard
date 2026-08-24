FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libxml2 libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

COPY packages/workflow-core /app/packages/workflow-core
COPY apps/api /app/apps/api

RUN pip install --no-cache-dir -e /app/packages/workflow-core -e /app/apps/api

WORKDIR /app/apps/api
