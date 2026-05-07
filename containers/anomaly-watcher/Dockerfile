FROM --platform=linux/arm64 debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl ffmpeg \
      python3 python3-pip python3-opencv \
      libsdl2-dev libgl1 libglib2.0-0 \
    && pip3 install --no-cache-dir --break-system-packages edge_impulse_linux requests \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY anomaly.eim          /app/anomaly.eim
COPY anomaly-watcher.py   /app/anomaly-watcher.py
COPY capture-and-upload.sh /app/capture-and-upload.sh
RUN chmod +x /app/anomaly.eim /app/anomaly-watcher.py /app/capture-and-upload.sh

ENV ANOMALY_MODEL=/app/anomaly.eim
ENV UPLOAD_SCRIPT=/app/capture-and-upload.sh

CMD ["/app/anomaly-watcher.py"]
