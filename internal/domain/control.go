package domain

type Profile struct {
	DisplayName string   `json:"display_name"`
	Bio         string   `json:"bio"`
	Skills      []string `json:"skills"`
	UpdatedAt   int64    `json:"updated_at"`
}

type QuickReply struct {
	ID        string `json:"id"`
	Title     string `json:"title"`
	Content   string `json:"content"`
	Category  string `json:"category"`
	Active    bool   `json:"active"`
	CreatedAt int64  `json:"created_at"`
	UpdatedAt int64  `json:"updated_at"`
}

type AutoReplyRule struct {
	ID           string `json:"id"`
	Name         string `json:"name"`
	RuleType     string `json:"rule_type"`
	MatchType    string `json:"match_type,omitempty"`
	Pattern      string `json:"pattern,omitempty"`
	ResponseText string `json:"response_text"`
	StartTime    string `json:"start_time,omitempty"`
	EndTime      string `json:"end_time,omitempty"`
	Days         []int  `json:"days"`
	DelaySeconds int    `json:"delay_seconds"`
	Priority     int    `json:"priority"`
	Active       bool   `json:"active"`
	CreatedAt    int64  `json:"created_at"`
	UpdatedAt    int64  `json:"updated_at"`
}

type APIKey struct {
	ID                 string `json:"id"`
	Name               string `json:"name"`
	KeyHint            string `json:"key_hint"`
	Active             bool   `json:"active"`
	Revoked            bool   `json:"revoked"`
	RateLimitPerMinute int    `json:"rate_limit_per_minute"`
	DailyLimit         int    `json:"daily_limit"`
	MaxConcurrent      int    `json:"max_concurrent"`
	RequestCount       int    `json:"request_count"`
	UsageMinute        int    `json:"usage_minute"`
	UsageToday         int    `json:"usage_today"`
	PendingRequests    int    `json:"pending_requests"`
	CreatedAt          int64  `json:"created_at"`
	UpdatedAt          int64  `json:"updated_at"`
	LastUsedAt         int64  `json:"last_used_at,omitempty"`
	RevokedAt          int64  `json:"revoked_at,omitempty"`
}

type AdminDevice struct {
	ID          string `json:"id"`
	Name        string `json:"name"`
	Platform    string `json:"platform"`
	DeviceModel string `json:"device_model,omitempty"`
	OSVersion   string `json:"os_version,omitempty"`
	AppVersion  string `json:"app_version,omitempty"`
	Locale      string `json:"locale,omitempty"`
	Timezone    string `json:"timezone,omitempty"`
	IPAddress   string `json:"ip_address,omitempty"`
	UserAgent   string `json:"user_agent,omitempty"`
	CreatedAt   int64  `json:"created_at"`
	UpdatedAt   int64  `json:"updated_at"`
	LastSeenAt  int64  `json:"last_seen_at,omitempty"`
	RevokedAt   int64  `json:"revoked_at,omitempty"`
}

type AdminEvent struct {
	ID         int64          `json:"id"`
	Type       string         `json:"type"`
	ResourceID string         `json:"resource_id,omitempty"`
	Payload    map[string]any `json:"payload"`
	CreatedAt  int64          `json:"created_at"`
}

type Conversation struct {
	ID        string    `json:"id"`
	Title     string    `json:"title"`
	Messages  []Message `json:"messages"`
	CreatedAt int64     `json:"created_at"`
	UpdatedAt int64     `json:"updated_at"`
}
