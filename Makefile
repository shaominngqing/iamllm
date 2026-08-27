.PHONY: dev build test web mobile docker

web:
	cd web && npm ci && npm run build

dev: web
	go run ./cmd/iamllm

build: web
	CGO_ENABLED=0 go build -trimpath -o bin/iamllm ./cmd/iamllm

test: web
	go test -race ./...
	cd mobile && flutter analyze && flutter test

mobile:
	cd mobile && flutter pub get && flutter run

docker:
	docker compose build
