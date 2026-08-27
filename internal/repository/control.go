package repository

import (
	"context"

	"iamllm/internal/domain"
)

type KeyAuthorization struct {
	Key         *domain.APIKey
	LimitReason string
	RetryAfter  int
}

type ControlRepository interface {
	EnsureProfile(context.Context, string) error
	GetProfile(context.Context) (domain.Profile, error)
	UpdateProfile(context.Context, domain.Profile) (domain.Profile, error)
	ListQuickReplies(context.Context, bool) ([]domain.QuickReply, error)
	GetQuickReply(context.Context, string) (domain.QuickReply, error)
	SaveQuickReply(context.Context, domain.QuickReply) (domain.QuickReply, error)
	DeleteQuickReply(context.Context, string) error
	ListAutoReplyRules(context.Context) ([]domain.AutoReplyRule, error)
	GetAutoReplyRule(context.Context, string) (domain.AutoReplyRule, error)
	SaveAutoReplyRule(context.Context, domain.AutoReplyRule) (domain.AutoReplyRule, error)
	DeleteAutoReplyRule(context.Context, string) error
	ResolveAutoReply(context.Context, string, string, int) (*domain.AutoReplyRule, error)
	CreateAPIKey(context.Context, domain.APIKey, string) (domain.APIKey, error)
	ListAPIKeys(context.Context, int64, int64) ([]domain.APIKey, error)
	GetAPIKey(context.Context, string, int64, int64) (domain.APIKey, error)
	SaveAPIKey(context.Context, domain.APIKey) (domain.APIKey, error)
	RevokeAPIKey(context.Context, string) (domain.APIKey, error)
	AuthorizeAPIKey(context.Context, string, bool, int64, int64) (KeyAuthorization, error)
	SavePairingCode(context.Context, string, string, int64) error
	ConsumePairingCode(context.Context, string, int64) (bool, error)
	CreateDevice(context.Context, domain.AdminDevice, string) (domain.AdminDevice, error)
	GetDeviceByRefreshHash(context.Context, string) (domain.AdminDevice, error)
	RotateDeviceRefresh(context.Context, string, string) error
	ListDevices(context.Context) ([]domain.AdminDevice, error)
	UpdateDeviceMetadata(context.Context, string, domain.AdminDevice) error
	TouchDevice(context.Context, string, string, string) error
	RevokeDevice(context.Context, string) error
	CreateConversation(context.Context, domain.Conversation, string) (domain.Conversation, error)
	GetConversation(context.Context, string, string) (domain.Conversation, error)
	AddConversationMessage(context.Context, string, domain.Message, string) error
	ConversationMessages(context.Context, string) ([]domain.Message, error)
	ConversationHasPending(context.Context, string) (bool, error)
	RenameConversation(context.Context, string, string) error
}

type Repository interface {
	RequestRepository
	ControlRepository
}
