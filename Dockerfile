# Dockerfile
FROM python:3.11-slim


# Install minimal system deps (add more if you need Playwright/chromium etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
ca-certificates git && \
rm -rf /var/lib/apt/lists/*


WORKDIR /app


COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright and Chromium browser with all required system dependencies
RUN playwright install --with-deps chromium


# copy repository files (script, sites.json, etc.)
COPY . .


# default command (we'll override with explicit command in workflow)
CMD ["python", "detect_platform.py"]