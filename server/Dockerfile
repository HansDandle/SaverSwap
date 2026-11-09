FROM python:3.12-slim
# ffmpeg converts videos; nodejs lets yt-dlp solve YouTube's JavaScript challenges
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg nodejs \
 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir "yt-dlp[default]"
WORKDIR /app
COPY saverswap.py index.html ./
ENV SAVERSWAP_DATA=/data
EXPOSE 8099
VOLUME /data
CMD ["python", "saverswap.py"]
