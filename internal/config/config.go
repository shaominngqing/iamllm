package config

import (
	"errors"
	"fmt"
	"net"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

const defaultTimeoutFallback = "【超时兜底】我知道你很急，但你先别急。稍后再戳我一次。||【超时兜底】这次不是你的网络问题，是回复时间刚好用完了。"

type Config struct {
	Environment         string
	BindAddress         string
	DatabasePath        string
	APIKey              string
	AdminAPIToken       string
	AdminUsername       string
	AdminPassword       string
	SessionSecret       string
	ModelName           string
	PublicBaseURL       string
	Timezone            string
	ResponseTimeout     time.Duration
	JobTTL              time.Duration
	PollInterval        time.Duration
	StreamIdle          time.Duration
	StreamChunkDelay    time.Duration
	StreamChunkChars    int
	TimeoutFallbacks    []string
	NotificationURL     string
	NotificationTimeout time.Duration
}

func Load() (Config, error) { return load(os.Getenv) }

func load(getenv func(string) string) (Config, error) {
	environment := strings.ToLower(valueOr(getenv("IAMLLM_ENV"), "development"))
	port := valueOr(getenv("PORT"), valueOr(getenv("IAMLLM_PORT"), "8000"))
	bindIP := valueOr(getenv("IAMLLM_BIND_IP"), "127.0.0.1")
	responseSeconds, err := positiveInt(getenv, "IAMLLM_RESPONSE_TIMEOUT_SECONDS", 300)
	if err != nil {
		return Config{}, err
	}
	jobSeconds, err := positiveInt(getenv, "IAMLLM_JOB_TTL_SECONDS", 86400)
	if err != nil {
		return Config{}, err
	}
	idleSeconds, err := positiveInt(getenv, "IAMLLM_STREAM_IDLE_TIMEOUT_SECONDS", 120)
	if err != nil {
		return Config{}, err
	}
	pollMillis, err := positiveInt(getenv, "IAMLLM_POLL_INTERVAL_MS", 100)
	if err != nil {
		return Config{}, err
	}
	chunkMillis, err := nonNegativeInt(getenv, "IAMLLM_STREAM_CHUNK_DELAY_MS", 10)
	if err != nil {
		return Config{}, err
	}
	chunkChars, err := positiveInt(getenv, "IAMLLM_STREAM_CHUNK_CHARS", 3)
	if err != nil {
		return Config{}, err
	}
	notificationSeconds, err := positiveInt(getenv, "IAMLLM_NOTIFICATION_WEBHOOK_TIMEOUT_SECONDS", 5)
	if err != nil {
		return Config{}, err
	}
	databasePath := filepath.Clean(valueOr(getenv("IAMLLM_DATABASE_PATH"), "data/iamllm.db"))
	adminToken := strings.TrimSpace(getenv("IAMLLM_ADMIN_API_TOKEN"))
	if adminToken == "" && environment != "production" {
		adminToken = "development-admin-token"
	}
	sessionSecret := valueOr(getenv("IAMLLM_SESSION_SECRET"), "iamllm-local-session-secret")
	config := Config{
		Environment: environment, BindAddress: net.JoinHostPort(bindIP, port),
		DatabasePath: databasePath,
		APIKey:       valueOr(getenv("IAMLLM_API_KEY"), "sk-human-local-demo-key"), AdminAPIToken: adminToken,
		AdminUsername: valueOr(getenv("IAMLLM_ADMIN_USERNAME"), "admin"),
		AdminPassword: valueOr(getenv("IAMLLM_ADMIN_PASSWORD"), "iamllm-local"), SessionSecret: sessionSecret,
		ModelName:       valueOr(getenv("IAMLLM_MODEL_NAME"), "iam-human"),
		PublicBaseURL:   strings.TrimRight(strings.TrimSpace(getenv("IAMLLM_PUBLIC_BASE_URL")), "/"),
		Timezone:        valueOr(getenv("IAMLLM_TIMEZONE"), "UTC"),
		ResponseTimeout: time.Duration(responseSeconds) * time.Second, JobTTL: time.Duration(jobSeconds) * time.Second,
		PollInterval: time.Duration(pollMillis) * time.Millisecond, StreamIdle: time.Duration(idleSeconds) * time.Second,
		StreamChunkDelay: time.Duration(chunkMillis) * time.Millisecond, StreamChunkChars: chunkChars,
		TimeoutFallbacks:    splitFallbacks(valueOr(getenv("IAMLLM_TIMEOUT_FALLBACK_TEXTS"), defaultTimeoutFallback)),
		NotificationURL:     strings.TrimSpace(getenv("IAMLLM_NOTIFICATION_WEBHOOK_URL")),
		NotificationTimeout: time.Duration(notificationSeconds) * time.Second,
	}
	if err := config.Validate(); err != nil {
		return Config{}, err
	}
	return config, nil
}

func (config Config) Validate() error {
	switch config.Environment {
	case "development", "test", "production":
	default:
		return errors.New("IAMLLM_ENV must be development, test, or production")
	}
	if strings.TrimSpace(config.APIKey) == "" {
		return errors.New("IAMLLM_API_KEY is required")
	}
	if strings.TrimSpace(config.AdminAPIToken) == "" {
		return errors.New("IAMLLM_ADMIN_API_TOKEN is required")
	}
	if strings.TrimSpace(config.AdminUsername) == "" || strings.TrimSpace(config.AdminPassword) == "" {
		return errors.New("admin username and password are required")
	}
	if strings.TrimSpace(config.SessionSecret) == "" {
		return errors.New("IAMLLM_SESSION_SECRET is required")
	}
	if _, err := time.LoadLocation(config.Timezone); err != nil {
		return fmt.Errorf("IAMLLM_TIMEZONE is invalid: %w", err)
	}
	for name, raw := range map[string]string{"IAMLLM_PUBLIC_BASE_URL": config.PublicBaseURL, "IAMLLM_NOTIFICATION_WEBHOOK_URL": config.NotificationURL} {
		if raw == "" {
			continue
		}
		parsed, err := url.Parse(raw)
		if err != nil || (parsed.Scheme != "http" && parsed.Scheme != "https") {
			return fmt.Errorf("%s must use http:// or https://", name)
		}
	}
	if config.Environment == "production" {
		if !strings.HasPrefix(config.APIKey, "sk-") {
			return errors.New("IAMLLM_API_KEY must start with sk- in production")
		}
		if len(config.APIKey) < 24 {
			return errors.New("IAMLLM_API_KEY must be at least 24 characters in production")
		}
		if len(config.AdminAPIToken) < 24 {
			return errors.New("IAMLLM_ADMIN_API_TOKEN must be at least 24 characters in production")
		}
		if len(config.AdminPassword) < 16 {
			return errors.New("IAMLLM_ADMIN_PASSWORD must be at least 16 characters in production")
		}
		if len(config.SessionSecret) < 32 {
			return errors.New("IAMLLM_SESSION_SECRET must be at least 32 characters in production")
		}
	}
	return nil
}

func valueOr(value, fallback string) string {
	if strings.TrimSpace(value) == "" {
		return fallback
	}
	return strings.TrimSpace(value)
}
func positiveInt(getenv func(string) string, name string, fallback int) (int, error) {
	value, err := nonNegativeInt(getenv, name, fallback)
	if err != nil || value <= 0 {
		return 0, fmt.Errorf("%s must be a positive integer", name)
	}
	return value, nil
}
func nonNegativeInt(getenv func(string) string, name string, fallback int) (int, error) {
	raw := strings.TrimSpace(getenv(name))
	if raw == "" {
		return fallback, nil
	}
	value, err := strconv.Atoi(raw)
	if err != nil || value < 0 {
		return 0, fmt.Errorf("%s must be a non-negative integer", name)
	}
	return value, nil
}
func splitFallbacks(value string) []string {
	result := []string{}
	for _, item := range strings.Split(value, "||") {
		if item = strings.TrimSpace(item); item != "" {
			result = append(result, item)
		}
	}
	return result
}
