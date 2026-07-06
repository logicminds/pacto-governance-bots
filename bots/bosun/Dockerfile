# syntax=docker/dockerfile:1
FROM python:3.14-slim

WORKDIR /app/bots/bosun

# Copy the bot package and install it. The bot depends on the pacto-bot-sdk
# package from PyPI, which is resolved automatically by pip.
COPY bots/bosun/ ./
RUN pip install --no-cache-dir .

CMD ["python", "bosun.py"]
