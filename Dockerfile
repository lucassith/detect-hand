# Open Palm Detection Add-on for Home Assistant
# Supports IR/low-light camera streams

ARG BUILD_FROM
FROM ${BUILD_FROM}

# Set shell
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install system dependencies
RUN apk add --no-cache \
    python3 \
    py3-pip \
    py3-numpy \
    py3-opencv \
    ffmpeg \
    libstdc++ \
    libgcc \
    musl \
    jpeg-dev \
    zlib-dev \
    libffi-dev \
    build-base \
    python3-dev

# Create working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt /app/

# Install Python dependencies
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

# Copy application files
COPY detect_hand.py /app/
COPY run.sh /app/

# Make run script executable
RUN chmod +x /app/run.sh

# Set entrypoint
ENTRYPOINT ["/app/run.sh"]
