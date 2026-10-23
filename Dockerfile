FROM ghcr.io/astral-sh/uv:0.10.0 AS uv

FROM python:3.14-slim-bookworm AS app

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --no-install-project

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --no-dev

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]


FROM app AS app-local

RUN uv sync --no-dev --extra local


FROM ubuntu:24.04 AS office

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 \
        python3-venv \
        python3-uno \
        libreoffice-writer-nogui \
        libreoffice-impress-nogui \
        fonts-crosextra-caladea \
        fonts-crosextra-carlito \
        fonts-dejavu-core \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv --system-site-packages /opt/unoserver \
    && /opt/unoserver/bin/pip install --no-cache-dir "unoserver==3.7"

RUN useradd --create-home --uid 10001 converter

USER converter
ENV HOME=/home/converter

EXPOSE 2003

CMD ["/opt/unoserver/bin/unoserver", "--interface", "0.0.0.0", "--port", "2003", "--conversion-timeout", "90", "--stop-after", "100"]
