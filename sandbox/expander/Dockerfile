# Amaan expansion worker (layer L5): follows a link hop by hop, without a browser.
# Same user id as the Amaan backend (10001) so both can use the socket in the shared volume.
FROM python:3.11-slim
RUN useradd --no-create-home --uid 10001 amaan \
    && mkdir -p /run/amaan-expander && chown amaan /run/amaan-expander
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY expander.py .
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER amaan
CMD ["python", "expander.py"]
