FROM python:3.12-slim

WORKDIR /app

# Install dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends iproute2 \
    && rm -rf /var/lib/apt/lists/*

COPY drone-sim/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY drone-sim/ .
COPY proto/ /proto/
COPY shared/ /shared/

# Generate gRPC stubs from the proto contract
RUN mkdir -p grpc_generated && \
    python -m grpc_tools.protoc \
        -I /proto \
        --python_out=grpc_generated/ \
        --grpc_python_out=grpc_generated/ \
        /proto/beacon.proto && \
    touch grpc_generated/__init__.py

ENV ASSET_ID="BEACON-01"
ENV GRPC_PORT="50051"
ENV TELEMETRY_PORT="5005"
ENV BROADCAST_HOST="255.255.255.255"

CMD ["python", "main.py"]
