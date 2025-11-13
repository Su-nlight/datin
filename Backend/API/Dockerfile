FROM pytorch/pytorch:2.3.1-cuda12.1-cudnn8-runtime

WORKDIR /app 
# Install system dependencies (include libs needed by OpenCV headless)
RUN apt-get update

copy . /app

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/requirements.txt \
    "fastapi[standard]" \
    python-jose \
    mysql-connector-python \
    google-genai \
    sentence-transformers


CMD ["fastapi", "run", "main.py", "--port", "80"]