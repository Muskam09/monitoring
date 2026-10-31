# ───────────────────────────────────────────────────────
# Dev stage (default, used by docker-compose for live reload)
# ───────────────────────────────────────────────────────
FROM node:20-alpine AS dev
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

# ───────────────────────────────────────────────────────
# Build stage — produces static assets in /app/dist
# ───────────────────────────────────────────────────────
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# ───────────────────────────────────────────────────────
# Production stage — nginx serves the built SPA
# Enable by passing --target prod when building:
#   docker build --target prod -t dashboard-frontend ./frontend
# ───────────────────────────────────────────────────────
FROM nginx:1.27-alpine AS prod
COPY --from=build /app/dist /usr/share/nginx/html
# SPA fallback so react-router deep links work
RUN printf 'server {\n  listen 80;\n  location / {\n    root /usr/share/nginx/html;\n    try_files $uri /index.html;\n  }\n}\n' > /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
