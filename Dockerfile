FROM python:3.13.7-slim

LABEL org.opencontainers.image.source=https://github.com/ClashKingInc/ClashKingAPI
LABEL org.opencontainers.image.description="Image for the ClashKing API"
LABEL org.opencontainers.image.licenses=MIT

# Install uv and system dependencies
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install all build dependencies including Rust
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    gcc \
    git \
    libsnappy-dev \
    python3-dev

# Install Rust (needed for pendulum)
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# Set the working directory in the container
WORKDIR /app

# Copy pyproject.toml first for better caching
COPY pyproject.toml .

# Install dependencies using uv
RUN uv pip install --system .

# Now remove build dependencies to reduce image size
RUN apt-get remove -y build-essential gcc python3-dev git \
    && apt-get autoremove -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /root/.cache/pip /root/.cargo /root/.rustup

# Copy the rest of the application code into the container
COPY . .

EXPOSE 8010

CMD ["uv", "run", "python", "main.py"]