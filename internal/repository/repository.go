package repository

import (
	"context"
	"errors"
	"time"

	"iamllm/internal/domain"
)

var (
	ErrNotFound        = errors.New("request not found")
	ErrNotPending      = errors.New("request is no longer pending")
	ErrNoStreamChunks  = errors.New("request has no stream chunks")
	ErrHasStreamChunks = errors.New("request already has stream chunks")
	ErrClaimed         = errors.New("request is claimed by another operator")
)

type RequestRepository interface {
	CreateRequest(context.Context, domain.HumanRequest) error
	GetRequest(context.Context, string) (domain.HumanRequest, error)
	ListRequests(context.Context, domain.RequestStatus, int, int64, string) ([]domain.HumanRequest, error)
	ListChunks(context.Context, string, int) ([]domain.StreamChunk, error)
	AppendChunk(context.Context, string, string, string, time.Duration) (domain.StreamChunk, bool, error)
	CompleteRequest(context.Context, string, string) (domain.HumanRequest, error)
	AnswerRequest(context.Context, string, string, string) (domain.HumanRequest, error)
	AnswerResponse(context.Context, string, *domain.ResponseMessage, string) (domain.HumanRequest, error)
	ClaimRequest(context.Context, string, string, time.Duration) (domain.HumanRequest, error)
	ReleaseClaim(context.Context, string, string) error
	MarkRequestRead(context.Context, string) (domain.HumanRequest, error)
	SaveRequestDraft(context.Context, string, string, string) (domain.HumanRequest, error)
	TouchClient(context.Context, string) error
	ListDueAutoReplies(context.Context, int64, int) ([]domain.HumanRequest, error)
	ExpireDue(context.Context, int64) (int, error)
	ListEvents(context.Context, int64, int) ([]domain.AdminEvent, error)
	PendingCount(context.Context) (int, error)
	Close() error
}
