FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt requirements-postgres.txt ./
RUN pip install -r requirements-postgres.txt

COPY fdq ./fdq
COPY sql ./sql
COPY reference ./reference

RUN useradd --create-home fdq && mkdir -p /data && chown fdq /data
USER fdq

ENV FDQ_DB_URL=sqlite:////data/fdq.db \
    FDQ_RAW_DIR=/data/raw \
    FDQ_REPORTS_DIR=/data/reports
VOLUME /data

ENTRYPOINT ["python", "-m", "fdq"]
CMD ["run"]
