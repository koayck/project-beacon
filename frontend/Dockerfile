# Builder stage - build Next.js SSG
FROM node:20-alpine AS builder

WORKDIR /app/frontend

# Install dependencies from the frontend lockfile
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Copy frontend source and shared world data used by the build script
COPY frontend ./
COPY shared /app/shared

# Generate world environment and build the static export
RUN npm run build

# Runtime stage - serve static files
FROM node:20-alpine

WORKDIR /app/frontend

# Install serve to run static site
RUN npm install -g serve

# Create non-root user
RUN addgroup -g 1001 -S nodejs
RUN adduser -S nextjs -u 1001

# Copy built output from builder
COPY --from=builder /app/frontend/out ./out

# Ownership
RUN chown -R nextjs:nodejs /app/frontend

USER nextjs

EXPOSE 3000

# Serve the static site
CMD ["serve", "-s", "out", "-l", "3000"]
