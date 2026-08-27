package notification

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"iamllm/internal/buildinfo"
	"iamllm/internal/domain"
)

type Webhook struct {
	url, publicBaseURL string
	client             *http.Client
	logger             *slog.Logger
	queue              chan domain.HumanRequest
}

func NewWebhook(url, publicBaseURL string, timeout time.Duration, logger *slog.Logger) *Webhook {
	if timeout <= 0 {
		timeout = 5 * time.Second
	}
	return &Webhook{
		url: strings.TrimSpace(url), publicBaseURL: strings.TrimRight(publicBaseURL, "/"),
		client: &http.Client{Timeout: timeout}, logger: logger, queue: make(chan domain.HumanRequest, 128),
	}
}

func (webhook *Webhook) Enqueue(item domain.HumanRequest) {
	if webhook.url == "" {
		return
	}
	select {
	case webhook.queue <- item:
	default:
		webhook.logger.Warn("notification queue full", "request_id", item.ID)
	}
}

func (webhook *Webhook) Run(ctx context.Context) {
	if webhook.url == "" {
		return
	}
	for {
		select {
		case <-ctx.Done():
			return
		case item := <-webhook.queue:
			if err := webhook.deliver(ctx, item); err != nil {
				webhook.logger.Warn("notification webhook failed", "request_id", item.ID, "error", err)
			}
		}
	}
}

func (webhook *Webhook) deliver(ctx context.Context, item domain.HumanRequest) error {
	adminURL := ""
	if webhook.publicBaseURL != "" {
		adminURL = webhook.publicBaseURL + "/admin#inbox/" + item.ID
	}
	text := "🧠 新问题到达 · " + item.Source + "\n" + item.Preview
	if adminURL != "" {
		text += "\n" + adminURL
	}
	payload := map[string]any{
		"event": "human_request.created", "text": text,
		"request": map[string]any{"id": item.ID, "model": item.Model, "source": item.Source, "preview": item.Preview, "created_at": item.CreatedAt, "admin_url": adminURL},
	}
	body, _ := json.Marshal(payload)
	var last error
	for attempt := range 3 {
		request, err := http.NewRequestWithContext(ctx, http.MethodPost, webhook.url, bytes.NewReader(body))
		if err != nil {
			return err
		}
		request.Header.Set("Content-Type", "application/json; charset=utf-8")
		request.Header.Set("User-Agent", "iamllm-webhook/"+buildinfo.Version)
		response, err := webhook.client.Do(request)
		if err == nil {
			response.Body.Close()
			if response.StatusCode < 400 {
				return nil
			}
			err = fmt.Errorf("webhook returned %d", response.StatusCode)
		}
		last = err
		if attempt < 2 {
			select {
			case <-ctx.Done():
				return ctx.Err()
			case <-time.After(time.Duration(1<<attempt) * 500 * time.Millisecond):
			}
		}
	}
	return last
}
