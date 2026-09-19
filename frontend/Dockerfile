# Outlay frontend — React + Vite build, served by nginx
#
# Multi-stage: stage 1 builds the static assets with Node, stage 2 serves
# them with nginx. The final image is small (~25MB) and has no Node runtime.

# --- Stage 1: build ---
FROM node:18-slim AS build
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci --silent
COPY frontend/ ./
# Build with the production API base URL pointing at the backend container.
# In docker-compose, the backend service is named "backend" and listens on 5000.
# The browser hits nginx (this container) on 5173, which proxies /api/* to the
# backend — so the frontend uses a RELATIVE path (no host) and nginx proxies it.
ENV VITE_API_BASE_URL=/api
RUN npm run build

# --- Stage 2: serve ---
FROM nginx:alpine AS serve
# Copy the built static assets from stage 1.
COPY --from=build /app/dist /usr/share/nginx/html
# Replace the default nginx config with one that:
#   1. Serves index.html for all routes (React Router handles client-side routing)
#   2. Proxies /api/* to the backend container on port 5000
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
