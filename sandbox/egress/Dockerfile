# Amaan egress proxy: the sandbox networks' only way out (see egress.py).
# Standard library only.
FROM python:3.11-slim
RUN useradd --no-create-home --uid 10002 egress
WORKDIR /app
COPY egress.py .
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER egress
EXPOSE 3128
CMD ["python", "egress.py"]
