# Multi-stage build: keeps the final image small by not shipping
# build tools (gcc, etc.) needed only to install psycopg2.

FROM python:3.11-slim AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

FROM python:3.11-slim

# Run as a non-root user — a basic security practice. If this
# container is ever compromised, the attacker doesn't get root.
RUN useradd --create-home appuser
WORKDIR /app

COPY --from=builder /root/.local /home/appuser/.local
COPY . .
RUN chown -R appuser:appuser /app

USER appuser
ENV PATH=/home/appuser/.local/bin:$PATH

EXPOSE 8000

# No --reload here — that's a dev-only convenience that wastes
# resources and isn't meant for production.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
