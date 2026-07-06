# syntax=docker/dockerfile:1
FROM python:3.14-slim

WORKDIR /app/bots/bosun

# Install git so pip can install dependencies referenced via git+https://...
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Copy the bot package and install it. The bot depends on the pacto-bot-sdk
# package from PyPI, which is resolved automatically by pip.
COPY bots/bosun/ ./
RUN pip install --no-cache-dir .

ENTRYPOINT ["python", "-m", "bosun"]
CMD []
