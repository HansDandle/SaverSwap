FROM python:3.12-slim
# ffmpeg converts videos; nodejs lets yt-dlp solve YouTube's JavaScript challenges
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg nodejs \
 && rm -rf /var/lib/apt/lists/*
COPY server/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
WORKDIR /app
COPY server/saverswap.py server/rokus.py server/index.html ./
# The Roku app, so the web page can install it on the TV
COPY roku ./roku
ENV SAVERSWAP_DATA=/data PYTHONUNBUFFERED=1
EXPOSE 8099
VOLUME /data
CMD ["python", "saverswap.py"]
