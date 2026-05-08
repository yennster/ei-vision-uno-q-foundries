FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py /app/
COPY static/ /app/static/

EXPOSE 8088
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8088"]
