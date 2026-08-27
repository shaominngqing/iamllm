package application

import (
	"context"
	"crypto/rand"
	"errors"
	"math/big"
	"time"

	"iamllm/internal/domain"
	"iamllm/internal/repository"
)

var ErrResponseTimeout = errors.New("the human did not answer before the request timed out")

type Options struct {
	JobTTL           time.Duration
	ResponseTimeout  time.Duration
	PollInterval     time.Duration
	StreamIdle       time.Duration
	TimeoutFallbacks []string
	StreamChunkDelay time.Duration
	StreamChunkChars int
	Timezone         *time.Location
	Notify           func(domain.HumanRequest)
}

type Service struct {
	repository repository.Repository
	options    Options
}

func New(repository repository.Repository, options Options) *Service {
	return &Service{repository: repository, options: options}
}

func (service *Service) CreateRequest(
	ctx context.Context,
	input domain.RequestInput,
) (domain.HumanRequest, error) {
	if input.ConversationID != "" {
		owner := input.APIKeyID
		if owner == "" {
			owner = "master"
		}
		conversation, err := service.repository.GetConversation(ctx, input.ConversationID, owner)
		if errors.Is(err, repository.ErrNotFound) {
			now := time.Now().UnixMilli()
			conversation, err = service.repository.CreateConversation(ctx, domain.Conversation{ID: input.ConversationID, Title: "API 对话", CreatedAt: now, UpdatedAt: now}, owner)
		}
		if err != nil {
			return domain.HumanRequest{}, err
		}
		pending, err := service.repository.ConversationHasPending(ctx, conversation.ID)
		if err != nil {
			return domain.HumanRequest{}, err
		}
		if pending {
			return domain.HumanRequest{}, errors.New("this conversation already has a pending response")
		}
		for _, message := range input.Messages {
			if err := service.repository.AddConversationMessage(ctx, conversation.ID, message, ""); err != nil {
				return domain.HumanRequest{}, err
			}
		}
		input.Messages, err = service.repository.ConversationMessages(ctx, conversation.ID)
		if err != nil {
			return domain.HumanRequest{}, err
		}
		for index := len(input.Messages) - 1; index >= 0; index-- {
			if input.Messages[index].Role == "user" {
				_ = service.repository.RenameConversation(ctx, conversation.ID, domain.CleanUserText(domain.MessageText(input.Messages[index].Content)))
				break
			}
		}
	}
	ttl := service.options.JobTTL
	if ttl <= 0 {
		ttl = 24 * time.Hour
	}
	if input.Mode != "async" && service.options.ResponseTimeout > 0 {
		ttl = service.options.ResponseTimeout
	}
	request, err := domain.NewHumanRequest(input, ttl)
	if err != nil {
		return domain.HumanRequest{}, err
	}
	text := ""
	for index := len(request.Messages) - 1; index >= 0; index-- {
		if request.Messages[index].Role == "user" {
			text = domain.CleanUserText(domain.MessageText(request.Messages[index].Content))
			if text != "" {
				break
			}
		}
	}
	location := service.options.Timezone
	if location == nil {
		location = time.Local
	}
	now := time.Now().In(location)
	rule, err := service.repository.ResolveAutoReply(ctx, text, now.Format("15:04"), (int(now.Weekday())+6)%7)
	if err != nil {
		return domain.HumanRequest{}, err
	}
	if rule != nil {
		request.AutoReplyRuleID, request.AutoReplyLabel, request.AutoReplyText = rule.ID, rule.Name, rule.ResponseText
		request.AutoReplyDueAt = now.Add(time.Duration(rule.DelaySeconds) * time.Second).UnixMilli()
	}
	if err := service.repository.CreateRequest(ctx, request); err != nil {
		return domain.HumanRequest{}, err
	}
	if request.AutoReplyRuleID == "" && service.options.Notify != nil {
		service.options.Notify(request)
	}
	return request, nil
}

func (service *Service) WaitForAnswer(
	ctx context.Context,
	requestID string,
) (domain.HumanRequest, error) {
	timeout := service.options.ResponseTimeout
	if timeout <= 0 {
		timeout = 5 * time.Minute
	}
	deadline := time.NewTimer(timeout)
	defer deadline.Stop()
	interval := service.pollInterval()
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		request, err := service.repository.GetRequest(ctx, requestID)
		if err != nil {
			return domain.HumanRequest{}, err
		}
		if request.Status == domain.StatusAnswered {
			return request, nil
		}
		if request.Status == domain.StatusExpired {
			return domain.HumanRequest{}, ErrResponseTimeout
		}
		select {
		case <-ctx.Done():
			return domain.HumanRequest{}, ctx.Err()
		case <-deadline.C:
			return service.settleTimeout(ctx, requestID)
		case <-ticker.C:
		}
	}
}

func (service *Service) SettleTimeout(
	ctx context.Context,
	requestID string,
) (domain.HumanRequest, error) {
	return service.settleTimeout(ctx, requestID)
}

func (service *Service) settleTimeout(
	ctx context.Context,
	requestID string,
) (domain.HumanRequest, error) {
	current, err := service.repository.GetRequest(ctx, requestID)
	if err != nil {
		return domain.HumanRequest{}, err
	}
	if current.Status == domain.StatusAnswered {
		return current, nil
	}
	if current.StreamChunkCount > 0 {
		return service.repository.CompleteRequest(
			ctx,
			requestID,
			"human_timeout_partial",
		)
	}
	fallback := service.timeoutFallback()
	if fallback == "" {
		return domain.HumanRequest{}, ErrResponseTimeout
	}
	request, err := service.repository.AnswerRequest(
		ctx,
		requestID,
		fallback,
		"timeout_fallback",
	)
	if errors.Is(err, repository.ErrNotPending) {
		current, getErr := service.repository.GetRequest(ctx, requestID)
		if getErr == nil && current.Status == domain.StatusAnswered {
			return current, nil
		}
	}
	if err != nil {
		return domain.HumanRequest{}, err
	}
	return request, nil
}

func (service *Service) GetRequest(
	ctx context.Context,
	requestID string,
) (domain.HumanRequest, error) {
	return service.repository.GetRequest(ctx, requestID)
}

func (service *Service) ListRequests(
	ctx context.Context,
	status domain.RequestStatus,
	limit int,
	beforeCreatedAt int64,
	beforeID string,
) ([]domain.HumanRequest, error) {
	return service.repository.ListRequests(ctx, status, limit, beforeCreatedAt, beforeID)
}

func (service *Service) ListChunks(
	ctx context.Context,
	requestID string,
	afterPosition int,
) ([]domain.StreamChunk, error) {
	return service.repository.ListChunks(ctx, requestID, afterPosition)
}

func (service *Service) AppendChunk(
	ctx context.Context,
	requestID string,
	chunkID string,
	content string,
) (domain.StreamChunk, bool, error) {
	idle := service.options.StreamIdle
	if idle <= 0 {
		idle = 2 * time.Minute
	}
	return service.repository.AppendChunk(ctx, requestID, chunkID, content, idle)
}

func (service *Service) CompleteRequest(
	ctx context.Context,
	requestID string,
) (domain.HumanRequest, error) {
	return service.repository.CompleteRequest(ctx, requestID, "human_stream")
}

func (service *Service) AnswerRequest(
	ctx context.Context,
	requestID string,
	content string,
) (domain.HumanRequest, error) {
	return service.repository.AnswerRequest(ctx, requestID, content, "human")
}

func (service *Service) AnswerTool(ctx context.Context, requestID, name string, arguments map[string]any) (domain.HumanRequest, error) {
	response, err := domain.ToolResponse(name, arguments)
	if err != nil {
		return domain.HumanRequest{}, err
	}
	return service.repository.AnswerResponse(ctx, requestID, response, "human")
}

func (service *Service) ClaimRequest(ctx context.Context, requestID, ownerID string) (domain.HumanRequest, error) {
	return service.repository.ClaimRequest(ctx, requestID, ownerID, 30*time.Second)
}
func (service *Service) ReleaseClaim(ctx context.Context, requestID, ownerID string) error {
	return service.repository.ReleaseClaim(ctx, requestID, ownerID)
}
func (service *Service) MarkRequestRead(ctx context.Context, requestID string) (domain.HumanRequest, error) {
	return service.repository.MarkRequestRead(ctx, requestID)
}
func (service *Service) SaveRequestDraft(ctx context.Context, requestID, content, deviceID string) (domain.HumanRequest, error) {
	return service.repository.SaveRequestDraft(ctx, requestID, content, deviceID)
}
func (service *Service) TouchClient(ctx context.Context, requestID string) error {
	return service.repository.TouchClient(ctx, requestID)
}
func (service *Service) ListEvents(ctx context.Context, after int64, limit int) ([]domain.AdminEvent, error) {
	return service.repository.ListEvents(ctx, after, limit)
}

func (service *Service) RunAutomation(ctx context.Context) {
	ticker := time.NewTicker(maxDuration(service.options.PollInterval, 50*time.Millisecond))
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			_ = service.processAutoReplies(ctx)
			_, _ = service.repository.ExpireDue(ctx, time.Now().Unix())
		}
	}
}

func (service *Service) processAutoReplies(ctx context.Context) error {
	items, err := service.repository.ListDueAutoReplies(ctx, time.Now().UnixMilli(), 50)
	if err != nil {
		return err
	}
	for _, item := range items {
		chunks := splitChunks(item.AutoReplyText, service.options.StreamChunkChars)
		for index, chunk := range chunks {
			chunkID := item.ID + "-auto-" + time.Now().Format("150405.000000")
			if _, _, err := service.AppendChunk(ctx, item.ID, chunkID, chunk); err != nil {
				break
			}
			if index < len(chunks)-1 {
				select {
				case <-ctx.Done():
					return ctx.Err()
				case <-time.After(service.options.StreamChunkDelay):
				}
			}
		}
		if len(chunks) > 0 {
			_, _ = service.repository.CompleteRequest(ctx, item.ID, "automation")
		}
	}
	return nil
}

func (service *Service) PendingCount(ctx context.Context) (int, error) {
	return service.repository.PendingCount(ctx)
}

func (service *Service) PollInterval() time.Duration {
	return service.pollInterval()
}

func (service *Service) ResponseTimeout() time.Duration {
	return service.options.ResponseTimeout
}

func (service *Service) pollInterval() time.Duration {
	if service.options.PollInterval <= 0 {
		return 50 * time.Millisecond
	}
	return service.options.PollInterval
}

func (service *Service) timeoutFallback() string {
	values := service.options.TimeoutFallbacks
	if len(values) == 0 {
		return ""
	}
	value, err := rand.Int(rand.Reader, big.NewInt(int64(len(values))))
	if err != nil {
		return values[0]
	}
	return values[value.Int64()]
}

func splitChunks(value string, preferred int) []string {
	runes := []rune(value)
	if len(runes) == 0 {
		return nil
	}
	if preferred < 2 {
		preferred = 2
	}
	if preferred > 3 {
		preferred = 3
	}
	result := []string{}
	for len(runes) > 0 {
		size := preferred
		if len(runes) < size {
			size = len(runes)
		}
		if len(runes) == 4 && preferred == 3 {
			size = 2
		}
		result = append(result, string(runes[:size]))
		runes = runes[size:]
	}
	return result
}
func maxDuration(a, b time.Duration) time.Duration {
	if a > b {
		return a
	}
	return b
}
