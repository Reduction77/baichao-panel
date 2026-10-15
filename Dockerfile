FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PANEL_DATA_DIR=/data
WORKDIR /app
COPY requirements-server.txt ./
RUN pip install --no-cache-dir -r requirements-server.txt && useradd --uid 10001 --create-home panel && mkdir /data && chown panel:panel /data
COPY admin/windows/app.py admin/windows/app.py
COPY admin/windows/static admin/windows/static
COPY admin/windows/seed admin/windows/seed
COPY server server
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD ["python", "-m", "server.manage", "healthcheck"]
CMD ["gunicorn", "--workers", "1", "--threads", "4", "--worker-class", "gthread", "--timeout", "180", "--bind", "0.0.0.0:8080", "--access-logfile", "/dev/null", "--error-logfile", "-", "server.app:create_app()"]
