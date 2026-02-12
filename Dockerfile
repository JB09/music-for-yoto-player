FROM python:3.12-slim

# ffmpeg is needed if using the local yt-dlp fallback (no sidecar)
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/downloads

EXPOSE 5000

CMD ["python", "web_app.py"]
