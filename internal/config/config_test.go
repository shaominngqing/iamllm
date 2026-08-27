package config

import (
	"strings"
	"testing"
	"time"
)

func TestLoadUsesSelfHostedDefaults(t *testing.T) {
	values := map[string]string{
		"IAMLLM_API_KEY": "sk-test-api-key",
	}
	settings, err := load(func(name string) string { return values[name] })
	if err != nil {
		t.Fatalf("load config: %v", err)
	}
	if settings.DatabasePath != "data/iamllm.db" {
		t.Fatalf("unexpected database path: %s", settings.DatabasePath)
	}
	if settings.BindAddress != "127.0.0.1:8000" {
		t.Fatalf("unexpected bind address: %s", settings.BindAddress)
	}
	if settings.ResponseTimeout != 5*time.Minute {
		t.Fatalf("unexpected response timeout: %s", settings.ResponseTimeout)
	}
	if settings.AdminAPIToken != "development-admin-token" {
		t.Fatalf("unexpected development admin token")
	}
}

func TestProductionRequiresSeparateStrongAdminToken(t *testing.T) {
	values := map[string]string{
		"IAMLLM_ENV":            "production",
		"IAMLLM_API_KEY":        "sk-123456789012345678901234567890",
		"IAMLLM_MODEL_NAME":     "human-model",
		"IAMLLM_ADMIN_PASSWORD": "a-strong-admin-password",
		"IAMLLM_SESSION_SECRET": "a-session-secret-that-is-longer-than-thirty-two-characters",
	}
	_, err := load(func(name string) string { return values[name] })
	if err == nil || !strings.Contains(err.Error(), "IAMLLM_ADMIN_API_TOKEN") {
		t.Fatalf("expected admin token error, got %v", err)
	}
}

func TestProductionAPIKeyUsesCompatiblePrefix(t *testing.T) {
	values := map[string]string{
		"IAMLLM_ENV":             "production",
		"IAMLLM_API_KEY":         "human-key-with-more-than-twenty-four-characters",
		"IAMLLM_ADMIN_API_TOKEN": "admin-token-with-more-than-twenty-four-characters",
		"IAMLLM_ADMIN_PASSWORD":  "a-strong-admin-password",
		"IAMLLM_SESSION_SECRET":  "a-session-secret-that-is-longer-than-thirty-two-characters",
	}
	_, err := load(func(name string) string { return values[name] })
	if err == nil || !strings.Contains(err.Error(), "must start with sk-") {
		t.Fatalf("expected compatible API key prefix error, got %v", err)
	}
}
