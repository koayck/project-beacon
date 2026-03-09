#!/usr/bin/env bash
# Generate gRPC stubs from proto/beacon.proto into backend/grpc/
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "Generating protobuf stubs..."
python -m grpc_tools.protoc \
    -I "$REPO_ROOT/proto" \
    --python_out="$REPO_ROOT/backend/grpc/" \
    --grpc_python_out="$REPO_ROOT/backend/grpc/" \
    "$REPO_ROOT/proto/beacon.proto"

# Fix absolute import in generated grpc file (grpcio-tools bug)
sed -i 's/^import beacon_pb2/from backend.grpc import beacon_pb2/' \
    "$REPO_ROOT/backend/grpc/beacon_pb2_grpc.py" 2>/dev/null || true

echo "Done. Stubs written to backend/grpc/"
