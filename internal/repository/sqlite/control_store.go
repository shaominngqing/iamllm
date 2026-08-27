package sqlite

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"iamllm/internal/domain"
	"iamllm/internal/repository"
)

func (store *Store) EnsureProfile(ctx context.Context, displayName string) error {
	_, err := store.database.ExecContext(ctx, `
		INSERT INTO model_profile(singleton_id, display_name, bio, skills_json, updated_at)
		VALUES (1, ?, 'A human-operated language model.', '[]', ?)
		ON CONFLICT(singleton_id) DO UPDATE SET display_name = CASE
			WHEN model_profile.display_name = 'Human Model' THEN excluded.display_name
			ELSE model_profile.display_name END
	`, displayName, time.Now().UnixMilli())
	return err
}

func (store *Store) GetProfile(ctx context.Context) (domain.Profile, error) {
	var item domain.Profile
	var skills string
	err := store.database.QueryRowContext(ctx, `
		SELECT display_name, bio, skills_json, updated_at
		FROM model_profile WHERE singleton_id = 1
	`).Scan(&item.DisplayName, &item.Bio, &skills, &item.UpdatedAt)
	if err != nil {
		return item, fmt.Errorf("get profile: %w", err)
	}
	if err := json.Unmarshal([]byte(skills), &item.Skills); err != nil {
		return item, fmt.Errorf("decode profile skills: %w", err)
	}
	return item, nil
}

func (store *Store) UpdateProfile(ctx context.Context, item domain.Profile) (domain.Profile, error) {
	item.UpdatedAt = time.Now().UnixMilli()
	skills, _ := json.Marshal(item.Skills)
	_, err := store.database.ExecContext(ctx, `
		UPDATE model_profile SET display_name = ?, bio = ?, skills_json = ?, updated_at = ?
		WHERE singleton_id = 1
	`, item.DisplayName, item.Bio, string(skills), item.UpdatedAt)
	if err != nil {
		return item, fmt.Errorf("update profile: %w", err)
	}
	return item, nil
}

func (store *Store) ListQuickReplies(ctx context.Context, includeInactive bool) ([]domain.QuickReply, error) {
	query := `SELECT id, title, content, category, active, created_at, updated_at FROM quick_replies`
	if !includeInactive {
		query += ` WHERE active = 1`
	}
	query += ` ORDER BY category, created_at`
	rows, err := store.database.QueryContext(ctx, query)
	if err != nil {
		return nil, fmt.Errorf("list quick replies: %w", err)
	}
	defer rows.Close()
	items := []domain.QuickReply{}
	for rows.Next() {
		item, err := scanQuickReply(rows)
		if err != nil {
			return nil, err
		}
		items = append(items, item)
	}
	return items, rows.Err()
}

func scanQuickReply(row scanner) (domain.QuickReply, error) {
	var item domain.QuickReply
	var active int
	err := row.Scan(&item.ID, &item.Title, &item.Content, &item.Category, &active, &item.CreatedAt, &item.UpdatedAt)
	item.Active = active != 0
	return item, err
}

func (store *Store) GetQuickReply(ctx context.Context, id string) (domain.QuickReply, error) {
	item, err := scanQuickReply(store.database.QueryRowContext(ctx, `
		SELECT id, title, content, category, active, created_at, updated_at FROM quick_replies WHERE id = ?
	`, id))
	if errors.Is(err, sql.ErrNoRows) {
		return item, repository.ErrNotFound
	}
	return item, err
}

func (store *Store) SaveQuickReply(ctx context.Context, item domain.QuickReply) (domain.QuickReply, error) {
	now := time.Now().UnixMilli()
	if item.ID == "" {
		var err error
		item.ID, err = domain.NewID("reply")
		if err != nil {
			return item, err
		}
		item.CreatedAt = now
	}
	item.UpdatedAt = now
	_, err := store.database.ExecContext(ctx, `
		INSERT INTO quick_replies(id, title, content, category, active, created_at, updated_at)
		VALUES (?, ?, ?, ?, ?, ?, ?)
		ON CONFLICT(id) DO UPDATE SET title = excluded.title, content = excluded.content,
			category = excluded.category, active = excluded.active, updated_at = excluded.updated_at
	`, item.ID, item.Title, item.Content, item.Category, boolInt(item.Active), item.CreatedAt, item.UpdatedAt)
	if err != nil {
		return item, fmt.Errorf("save quick reply: %w", err)
	}
	return item, nil
}

func (store *Store) DeleteQuickReply(ctx context.Context, id string) error {
	result, err := store.database.ExecContext(ctx, `DELETE FROM quick_replies WHERE id = ?`, id)
	if err != nil {
		return err
	}
	if n, _ := result.RowsAffected(); n == 0 {
		return repository.ErrNotFound
	}
	return nil
}

func scanAutoRule(row scanner) (domain.AutoReplyRule, error) {
	var item domain.AutoReplyRule
	var matchType, pattern, startTime, endTime sql.NullString
	var days string
	var active int
	err := row.Scan(&item.ID, &item.Name, &item.RuleType, &matchType, &pattern,
		&item.ResponseText, &startTime, &endTime, &days, &item.DelaySeconds,
		&item.Priority, &active, &item.CreatedAt, &item.UpdatedAt)
	item.MatchType, item.Pattern = matchType.String, pattern.String
	item.StartTime, item.EndTime, item.Active = startTime.String, endTime.String, active != 0
	if err == nil {
		err = json.Unmarshal([]byte(days), &item.Days)
	}
	return item, err
}

const autoRuleColumns = `id, name, rule_type, match_type, pattern, response_text, start_time, end_time,
	days_json, delay_seconds, priority, active, created_at, updated_at`

func (store *Store) ListAutoReplyRules(ctx context.Context) ([]domain.AutoReplyRule, error) {
	rows, err := store.database.QueryContext(ctx, `SELECT `+autoRuleColumns+` FROM auto_reply_rules ORDER BY priority DESC, created_at`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := []domain.AutoReplyRule{}
	for rows.Next() {
		item, err := scanAutoRule(rows)
		if err != nil {
			return nil, err
		}
		items = append(items, item)
	}
	return items, rows.Err()
}

func (store *Store) GetAutoReplyRule(ctx context.Context, id string) (domain.AutoReplyRule, error) {
	item, err := scanAutoRule(store.database.QueryRowContext(ctx, `SELECT `+autoRuleColumns+` FROM auto_reply_rules WHERE id = ?`, id))
	if errors.Is(err, sql.ErrNoRows) {
		return item, repository.ErrNotFound
	}
	return item, err
}

func (store *Store) SaveAutoReplyRule(ctx context.Context, item domain.AutoReplyRule) (domain.AutoReplyRule, error) {
	now := time.Now().UnixMilli()
	if item.ID == "" {
		var err error
		item.ID, err = domain.NewID("rule")
		if err != nil {
			return item, err
		}
		item.CreatedAt = now
	}
	item.UpdatedAt = now
	days, _ := json.Marshal(item.Days)
	_, err := store.database.ExecContext(ctx, `
		INSERT INTO auto_reply_rules(`+autoRuleColumns+`) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
		ON CONFLICT(id) DO UPDATE SET name=excluded.name, rule_type=excluded.rule_type,
		match_type=excluded.match_type, pattern=excluded.pattern, response_text=excluded.response_text,
		start_time=excluded.start_time, end_time=excluded.end_time, days_json=excluded.days_json,
		delay_seconds=excluded.delay_seconds, priority=excluded.priority, active=excluded.active,
		updated_at=excluded.updated_at
	`, item.ID, item.Name, item.RuleType, nullString(item.MatchType), nullString(item.Pattern),
		item.ResponseText, nullString(item.StartTime), nullString(item.EndTime), string(days),
		item.DelaySeconds, item.Priority, boolInt(item.Active), item.CreatedAt, item.UpdatedAt)
	if err != nil {
		return item, fmt.Errorf("save auto reply rule: %w", err)
	}
	return item, nil
}

func (store *Store) DeleteAutoReplyRule(ctx context.Context, id string) error {
	result, err := store.database.ExecContext(ctx, `DELETE FROM auto_reply_rules WHERE id = ?`, id)
	if err != nil {
		return err
	}
	if n, _ := result.RowsAffected(); n == 0 {
		return repository.ErrNotFound
	}
	return nil
}

func (store *Store) ResolveAutoReply(ctx context.Context, text, clock string, weekday int) (*domain.AutoReplyRule, error) {
	rules, err := store.ListAutoReplyRules(ctx)
	if err != nil {
		return nil, err
	}
	for _, rule := range rules {
		if !rule.Active || !containsInt(rule.Days, weekday) {
			continue
		}
		matched := false
		if rule.RuleType == "keyword" {
			if rule.MatchType == "exact" {
				matched = strings.EqualFold(strings.TrimSpace(text), strings.TrimSpace(rule.Pattern))
			} else {
				matched = strings.Contains(strings.ToLower(text), strings.ToLower(rule.Pattern))
			}
		} else if rule.RuleType == "schedule" {
			if rule.StartTime <= rule.EndTime {
				matched = clock >= rule.StartTime && clock <= rule.EndTime
			} else {
				matched = clock >= rule.StartTime || clock <= rule.EndTime
			}
		}
		if matched {
			copy := rule
			return &copy, nil
		}
	}
	return nil, nil
}

func containsInt(values []int, target int) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}

func (store *Store) CreateAPIKey(ctx context.Context, item domain.APIKey, keyHash string) (domain.APIKey, error) {
	_, err := store.database.ExecContext(ctx, `
		INSERT INTO api_keys(id, name, key_hint, key_hash, active, rate_limit_per_minute,
			daily_limit, max_concurrent, request_count, created_at, updated_at)
		VALUES (?, ?, ?, ?, 1, ?, ?, ?, 0, ?, ?)
	`, item.ID, item.Name, item.KeyHint, keyHash, item.RateLimitPerMinute, item.DailyLimit,
		item.MaxConcurrent, item.CreatedAt, item.UpdatedAt)
	if err != nil {
		return item, fmt.Errorf("create api key: %w", err)
	}
	return item, nil
}

func (store *Store) ListAPIKeys(ctx context.Context, minuteStart, dayStart int64) ([]domain.APIKey, error) {
	rows, err := store.database.QueryContext(ctx, `SELECT id FROM api_keys ORDER BY created_at DESC`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := []domain.APIKey{}
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		item, err := store.GetAPIKey(ctx, id, minuteStart, dayStart)
		if err != nil {
			return nil, err
		}
		items = append(items, item)
	}
	return items, rows.Err()
}

func (store *Store) GetAPIKey(ctx context.Context, id string, minuteStart, dayStart int64) (domain.APIKey, error) {
	var item domain.APIKey
	var active int
	var lastUsed, revoked sql.NullInt64
	err := store.database.QueryRowContext(ctx, `
		SELECT id, name, key_hint, active, rate_limit_per_minute, daily_limit, max_concurrent,
		request_count, created_at, updated_at, last_used_at, revoked_at FROM api_keys WHERE id = ?
	`, id).Scan(&item.ID, &item.Name, &item.KeyHint, &active, &item.RateLimitPerMinute,
		&item.DailyLimit, &item.MaxConcurrent, &item.RequestCount, &item.CreatedAt, &item.UpdatedAt,
		&lastUsed, &revoked)
	if errors.Is(err, sql.ErrNoRows) {
		return item, repository.ErrNotFound
	}
	if err != nil {
		return item, err
	}
	item.Active, item.Revoked, item.LastUsedAt, item.RevokedAt = active != 0, revoked.Valid, lastUsed.Int64, revoked.Int64
	_ = store.database.QueryRowContext(ctx, `SELECT COUNT(*) FROM api_key_calls WHERE api_key_id = ? AND created_at >= ?`, id, minuteStart).Scan(&item.UsageMinute)
	_ = store.database.QueryRowContext(ctx, `SELECT COUNT(*) FROM api_key_calls WHERE api_key_id = ? AND created_at >= ?`, id, dayStart).Scan(&item.UsageToday)
	_ = store.database.QueryRowContext(ctx, `SELECT COUNT(*) FROM human_requests WHERE api_key_id = ? AND status = 'pending'`, id).Scan(&item.PendingRequests)
	return item, nil
}

func (store *Store) SaveAPIKey(ctx context.Context, item domain.APIKey) (domain.APIKey, error) {
	item.UpdatedAt = time.Now().UnixMilli()
	result, err := store.database.ExecContext(ctx, `
		UPDATE api_keys SET name=?, active=?, rate_limit_per_minute=?, daily_limit=?,
		max_concurrent=?, updated_at=? WHERE id=? AND revoked_at IS NULL
	`, item.Name, boolInt(item.Active), item.RateLimitPerMinute, item.DailyLimit,
		item.MaxConcurrent, item.UpdatedAt, item.ID)
	if err != nil {
		return item, err
	}
	if n, _ := result.RowsAffected(); n == 0 {
		return item, repository.ErrNotFound
	}
	return item, nil
}

func (store *Store) RevokeAPIKey(ctx context.Context, id string) (domain.APIKey, error) {
	now := time.Now().UnixMilli()
	result, err := store.database.ExecContext(ctx, `UPDATE api_keys SET active=0, revoked_at=?, updated_at=? WHERE id=? AND revoked_at IS NULL`, now, now, id)
	if err != nil {
		return domain.APIKey{}, err
	}
	if n, _ := result.RowsAffected(); n == 0 {
		return domain.APIKey{}, repository.ErrNotFound
	}
	return store.GetAPIKey(ctx, id, now-60_000, now-86_400_000)
}

func (store *Store) AuthorizeAPIKey(ctx context.Context, hash string, count bool, minuteStart, dayStart int64) (repository.KeyAuthorization, error) {
	var id string
	var active, minuteLimit, dailyLimit, concurrent int
	err := store.database.QueryRowContext(ctx, `SELECT id, active, rate_limit_per_minute, daily_limit, max_concurrent FROM api_keys WHERE key_hash = ? AND revoked_at IS NULL`, hash).Scan(&id, &active, &minuteLimit, &dailyLimit, &concurrent)
	if errors.Is(err, sql.ErrNoRows) || active == 0 {
		return repository.KeyAuthorization{}, nil
	}
	if err != nil {
		return repository.KeyAuthorization{}, err
	}
	now := time.Now().UnixMilli()
	item, err := store.GetAPIKey(ctx, id, minuteStart, dayStart)
	if err != nil {
		return repository.KeyAuthorization{}, err
	}
	if count {
		switch {
		case item.UsageMinute >= minuteLimit:
			return repository.KeyAuthorization{Key: &item, LimitReason: "minute", RetryAfter: 60}, nil
		case item.UsageToday >= dailyLimit:
			return repository.KeyAuthorization{Key: &item, LimitReason: "daily", RetryAfter: 3600}, nil
		case item.PendingRequests >= concurrent:
			return repository.KeyAuthorization{Key: &item, LimitReason: "concurrent", RetryAfter: 30}, nil
		}
		tx, err := store.database.BeginTx(ctx, nil)
		if err != nil {
			return repository.KeyAuthorization{}, err
		}
		defer tx.Rollback()
		if _, err := tx.ExecContext(ctx, `INSERT INTO api_key_calls(api_key_id, created_at) VALUES (?, ?)`, id, now); err != nil {
			return repository.KeyAuthorization{}, err
		}
		if _, err := tx.ExecContext(ctx, `UPDATE api_keys SET request_count=request_count+1, last_used_at=?, updated_at=? WHERE id=?`, now, now, id); err != nil {
			return repository.KeyAuthorization{}, err
		}
		if err := tx.Commit(); err != nil {
			return repository.KeyAuthorization{}, err
		}
	}
	return repository.KeyAuthorization{Key: &item}, nil
}
