# Dockerfile
FROM --platform=linux/amd64 python:3.11-slim


# Install Google Chrome stable (required by undetected-chromedriver)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git wget gnupg unzip \
    && wget -q -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get install -y /tmp/chrome.deb \
    && rm /tmp/chrome.deb \
    && rm -rf /var/lib/apt/lists/*


WORKDIR /app


COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download uc_driver (patched chromedriver for UC mode) at build time
RUN seleniumbase install uc_driver

# copy repository files (script, sites.json, etc.)
COPY . .


# default command (we'll override with explicit command in workflow)
CMD ["python", "detect_platform.py"]