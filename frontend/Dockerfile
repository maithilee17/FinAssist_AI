FROM node:22-alpine AS build

WORKDIR /app
ARG VITE_API_URL=http://localhost:8000/api
ARG VITE_CSRF_COOKIE_NAME=finassist_csrf_token
ARG VITE_MAX_UPLOAD_SIZE_MB=50
ARG VITE_PROCESSING_TIMEOUT_MS=600000
ENV VITE_API_URL=${VITE_API_URL}
ENV VITE_CSRF_COOKIE_NAME=${VITE_CSRF_COOKIE_NAME}
ENV VITE_MAX_UPLOAD_SIZE_MB=${VITE_MAX_UPLOAD_SIZE_MB}
ENV VITE_PROCESSING_TIMEOUT_MS=${VITE_PROCESSING_TIMEOUT_MS}

COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80

