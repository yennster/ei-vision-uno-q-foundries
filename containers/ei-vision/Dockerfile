FROM --platform=linux/arm64 debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates gnupg \
      libsdl2-dev libgl1 libglib2.0-0 \
      v4l-utils ffmpeg \
      python3 python3-pip \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g --unsafe-perm edge-impulse-linux \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY model.eim /app/model.eim
RUN chmod +x /app/model.eim

EXPOSE 4912

CMD ["edge-impulse-linux-runner", \
     "--model-file", "/app/model.eim", \
     "--enable-camera", \
     "--silent"]
