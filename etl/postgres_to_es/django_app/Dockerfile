FROM python:3.9-alpine AS builder

WORKDIR /app
COPY requirements.txt .


RUN apk add --no-cache --virtual .build-deps \
    postgresql-dev gcc python3-dev musl-dev && \
    pip install --user --no-cache-dir -r requirements.txt && \
    apk del .build-deps


FROM python:3.9-alpine


COPY --from=builder /root/.local /root/.local
COPY --from=builder /app/requirements.txt .

WORKDIR /app
COPY wait-for-es.sh /app/wait-for-es.sh
RUN chmod +x /app/wait-for-es.sh
COPY . .

ENV PATH=/root/.local/bin:$PATH \
    PYTHONPATH=/app


RUN find /app -type d -name __pycache__ -exec rm -r {} + && \
    rm -rf /var/cache/apk/* && \
    rm requirements.txt 

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]









