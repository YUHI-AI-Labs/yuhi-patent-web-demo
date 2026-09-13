# Self-contained: build context is this repo's own root.
# docker build -t yuhi-patent-web-demo .
FROM python:3.11-slim

# cadquery-ocp (OpenCascade) wheels need these even headless.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglu1-mesa libxrender1 libsm6 libxext6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# The real CAD analysis engine (vendored copy of ../cad-worker's yuhi_cad
# package), installed as a normal package. Run as `python -m yuhi_cad.cli`,
# isolated per request via subprocess - no PyInstaller freeze needed here.
COPY cad-worker/pyproject.toml cad-worker/pyproject.toml
COPY cad-worker/yuhi_cad cad-worker/yuhi_cad
RUN pip install --no-cache-dir ./cad-worker

COPY app.py glossary.py ./
COPY static ./static
COPY patents.db ./patents.db

EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
