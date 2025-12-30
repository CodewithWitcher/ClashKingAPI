FROM python:3.13.7-slim

LABEL org.opencontainers.image.source=https://github.com/ClashKingInc/ClashKingAPI
LABEL org.opencontainers.image.description="Image for the ClashKing API"
LABEL org.opencontainers.image.licenses=MIT

# Install uv and system dependencies
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    gcc \
    git \
    libsnappy-dev \
    python3-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy pyproject.toml first for better caching
COPY pyproject.toml .

# Install dependencies using uv
RUN uv pip install --system .

# Now remove build dependencies to reduce image size
RUN apt-get remove -y build-essential gcc python3-dev git \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/* /root/.cache/pip

# Copy the rest of the application code into the container
COPY . .

EXPOSE 8010

CMD ["uv", "run", "python", "main.py"]