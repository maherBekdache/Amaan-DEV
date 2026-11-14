# Amaan browser sandbox (layer L6): one headless Chromium page per container life.
# Same user id as the Amaan backend (10001) so both can use the socket in the shared volume.
FROM python:3.11-slim-bookworm
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/browsers PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --no-create-home --uid 10001 amaan \
    && mkdir -p /run/amaan-browser && chown amaan /run/amaan-browser
COPY browser.py .
# The image is read-only at run time; Chromium's profile, cache and downloads go to the
# in-memory /tmp, which disappears with the container after its single link.
ENV HOME=/tmp XDG_CONFIG_HOME=/tmp/.config XDG_CACHE_HOME=/tmp/.cache
USER amaan
CMD ["python", "browser.py"]
