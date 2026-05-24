FROM nvidia/cuda:12.8.0-cudnn-runtime-ubuntu22.04

WORKDIR /app

# Install system dependencies in a single layer and clean up to reduce image size
RUN apt-get update && apt-get install -y \
    curl \
    gcc \
    g++ \
    python3.10 \
    python3-pip \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN ln -s /usr/bin/python3.10 /usr/bin/python
# Copy requirements first — leverages Docker layer cache.
# If requirements.txt hasn't changed, pip install is skipped on rebuild.

<<<<<<< Updated upstream
<<<<<<< Updated upstream
RUN pip install --no-cache-dir torch==2.6.0 torchvision==0.21.0 \
=======
RUN pip install --no-cache-dir torch==2.7.1+cu128 torchvision \
>>>>>>> Stashed changes
=======

RUN pip install --no-cache-dir torch==2.7.1+cu128 torchvision \
>>>>>>> Stashed changes
    --index-url https://download.pytorch.org/whl/cu128
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/requirements.txt \
    "fastapi[standard]" \
    python-jose \
    mysql-connector-python \
    google-genai \
    sentence-transformers

# Copy application code after deps — keeps code change rebuilds fast
COPY . /app

# Non-root user for security — never run app as root in production
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Expose internal port — docker-compose maps this to host
EXPOSE 80

# Healthcheck — lets docker-compose and orchestrators know when app is ready
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:80/ || exit 1

CMD ["fastapi", "run", "main.py", "--port", "80"]