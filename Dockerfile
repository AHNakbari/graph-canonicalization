FROM python:3.13.2-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=0 \
    PYTHONPATH=/app/src

WORKDIR /app

# Test dependencies only. The package goes on PYTHONPATH rather than being
# installed, so the build never reaches the network for a build backend the
# stdlib-only pipeline does not need.
COPY requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY tests/ ./tests/
COPY tools/ ./tools/
COPY schemas/ ./schemas/
COPY config/ ./config/

RUN mkdir -p /app/submission/output \
    && useradd --create-home --uid 1000 runner \
    && chown -R runner:runner /app
USER runner

ENTRYPOINT ["python", "-m", "graphcanon"]
CMD ["run", "--input-dir", "data/input", "--output-dir", "submission/output"]
