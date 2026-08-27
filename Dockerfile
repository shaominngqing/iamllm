FROM node:22-alpine AS web-builder

WORKDIR /src
COPY web/package.json web/package-lock.json ./web/
RUN cd web && npm ci
COPY web ./web
COPY internal/webassets ./internal/webassets
RUN cd web && npm run build

FROM golang:1.25-alpine AS go-builder

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY cmd ./cmd
COPY internal ./internal
COPY --from=web-builder /src/internal/webassets/dist ./internal/webassets/dist
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/iamllm ./cmd/iamllm

FROM alpine:3.22

RUN apk add --no-cache ca-certificates sqlite tzdata \
    && addgroup -S iamllm \
    && adduser -S -G iamllm -u 10001 iamllm \
    && mkdir -p /data \
    && chown -R iamllm:iamllm /data

COPY --from=go-builder /out/iamllm /usr/local/bin/iamllm

USER iamllm
WORKDIR /data
ENV IAMLLM_BIND_IP=0.0.0.0 \
    IAMLLM_DATABASE_PATH=/data/iamllm.db

EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=20s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- http://127.0.0.1:8000/health >/dev/null || exit 1

ENTRYPOINT ["iamllm"]
