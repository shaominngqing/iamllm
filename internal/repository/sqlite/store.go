package sqlite

import (
	"context"
	"database/sql"
	"embed"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"

	"iamllm/internal/domain"
	"iamllm/internal/repository"
	_ "modernc.org/sqlite"
)

//go:embed migrations/*.sql
var migrationFiles embed.FS

type Store struct{ database *sql.DB }

func Open(ctx context.Context, path string) (*Store, error) {
	if err := os.MkdirAll(filepath.Dir(path), 0o750); err != nil {
		return nil, fmt.Errorf("create database directory: %w", err)
	}
	dsn := "file:" + filepath.ToSlash(path) +
		"?_pragma=journal_mode(WAL)&_pragma=foreign_keys(1)&_pragma=busy_timeout(5000)"
	database, err := sql.Open("sqlite", dsn)
	if err != nil {
		return nil, fmt.Errorf("open sqlite: %w", err)
	}
	database.SetMaxOpenConns(4)
	database.SetMaxIdleConns(4)
	store := &Store{database: database}
	if err := store.migrate(ctx); err != nil {
		database.Close()
		return nil, err
	}
	if err := database.PingContext(ctx); err != nil {
		database.Close()
		return nil, fmt.Errorf("ping sqlite: %w", err)
	}
	return store, nil
}

func (store *Store) Close() error {
	return store.database.Close()
}

type migration struct {
	version int
	name    string
}

func embeddedMigrations() ([]migration, error) {
	entries, err := fs.ReadDir(migrationFiles, "migrations")
	if err != nil {
		return nil, fmt.Errorf("read embedded migrations: %w", err)
	}
	result := make([]migration, 0, len(entries))
	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".sql") {
			continue
		}
		versionText, _, ok := strings.Cut(entry.Name(), "_")
		if !ok {
			return nil, fmt.Errorf("migration %s has no numeric prefix", entry.Name())
		}
		version, err := strconv.Atoi(versionText)
		if err != nil {
			return nil, fmt.Errorf("migration %s has invalid version: %w", entry.Name(), err)
		}
		result = append(result, migration{version: version, name: entry.Name()})
	}
	sort.Slice(result, func(i, j int) bool { return result[i].version < result[j].version })
	return result, nil
}

func (store *Store) migrate(ctx context.Context) error {
	if _, err := store.database.ExecContext(ctx, `
		CREATE TABLE IF NOT EXISTS schema_migrations (
			version INTEGER PRIMARY KEY,
			name TEXT NOT NULL,
			applied_at INTEGER NOT NULL
		)`); err != nil {
		return fmt.Errorf("create schema_migrations: %w", err)
	}
	migrations, err := embeddedMigrations()
	if err != nil {
		return err
	}
	for _, migration := range migrations {
		version, name := migration.version, migration.name
		var applied int
		err = store.database.QueryRowContext(
			ctx,
			"SELECT COUNT(*) FROM schema_migrations WHERE version = ?",
			version,
		).Scan(&applied)
		if err != nil {
			return fmt.Errorf("inspect migration %s: %w", name, err)
		}
		if applied > 0 {
			continue
		}
		script, err := migrationFiles.ReadFile("migrations/" + name)
		if err != nil {
			return fmt.Errorf("read migration %s: %w", name, err)
		}
		transaction, err := store.database.BeginTx(ctx, nil)
		if err != nil {
			return fmt.Errorf("begin migration %s: %w", name, err)
		}
		if _, err = transaction.ExecContext(ctx, string(script)); err == nil {
			_, err = transaction.ExecContext(
				ctx,
				"INSERT INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
				version,
				name,
				time.Now().UnixMilli(),
			)
		}
		if err != nil {
			transaction.Rollback()
			return fmt.Errorf("apply migration %s: %w", name, err)
		}
		if err := transaction.Commit(); err != nil {
			return fmt.Errorf("commit migration %s: %w", name, err)
		}
	}
	return nil
}

func (store *Store) CreateRequest(ctx context.Context, request domain.HumanRequest) error {
	messagesJSON, err := json.Marshal(request.Messages)
	if err != nil {
		return fmt.Errorf("encode messages: %w", err)
	}
	toolsJSON, err := json.Marshal(request.Tools)
	if err != nil {
		return fmt.Errorf("encode tools: %w", err)
	}
	transaction, err := store.database.BeginTx(ctx, nil)
	if err != nil {
		return fmt.Errorf("begin request insert: %w", err)
	}
	defer transaction.Rollback()
	_, err = transaction.ExecContext(ctx, `
		INSERT INTO human_requests (
			id, model, messages_json, preview, context_chars, message_count,
			system_count, tool_count, attachment_count, status,
			mode, created_at, expires_at, tools_json, source, updated_at,
			stream_requested, stream_chunk_count, conversation_id, api_key_id,
			auto_reply_rule_id, auto_reply_due_at, auto_reply_label, auto_reply_text
		) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)
	`,
		request.ID,
		request.Model,
		string(messagesJSON),
		request.Preview,
		request.ContextChars,
		request.MessageCount,
		request.SystemCount,
		request.ToolCount,
		request.AttachmentCount,
		request.Status,
		request.Mode,
		request.CreatedAt,
		request.ExpiresAt,
		string(toolsJSON),
		request.Source,
		request.UpdatedAt,
		boolInt(request.StreamRequested),
		nullString(request.ConversationID),
		nullString(request.APIKeyID),
		nullString(request.AutoReplyRuleID),
		nullInt64(request.AutoReplyDueAt),
		nullString(request.AutoReplyLabel),
		nullString(request.AutoReplyText),
	)
	if err != nil {
		return fmt.Errorf("insert request: %w", err)
	}
	if err := store.bumpQueueVersion(ctx, transaction); err != nil {
		return err
	}
	if err := store.insertEvent(ctx, transaction, "request.created", request.ID, map[string]any{
		"status": request.Status, "preview": request.Preview, "source": request.Source,
		"automated": request.AutoReplyRuleID != "",
	}); err != nil {
		return err
	}
	if err := transaction.Commit(); err != nil {
		return fmt.Errorf("commit request insert: %w", err)
	}
	return nil
}

const requestColumns = `
	id, model, messages_json, tools_json, preview, context_chars, message_count,
	system_count, tool_count, attachment_count, status, mode, source,
	conversation_id, stream_requested, stream_chunk_count, answer, response_json,
	answer_source, auto_reply_rule_id, auto_reply_due_at, auto_reply_label,
	auto_reply_text, claim_owner, claim_expires_at, client_last_seen_at, api_key_id,
	read_at, draft_text, draft_updated_at, draft_device_id,
	created_at, updated_at, answered_at, expires_at`

const requestSummaryColumns = `
	id, model, preview, context_chars, message_count, system_count, tool_count,
	attachment_count, status, mode, source, conversation_id,
	stream_requested, stream_chunk_count, answer_source, auto_reply_rule_id,
	auto_reply_label, claim_owner, claim_expires_at, client_last_seen_at,
	read_at, draft_text, draft_updated_at, draft_device_id,
	created_at, updated_at, answered_at, expires_at`

func (store *Store) GetRequest(ctx context.Context, requestID string) (domain.HumanRequest, error) {
	row := store.database.QueryRowContext(
		ctx,
		"SELECT "+requestColumns+" FROM human_requests WHERE id = ?",
		requestID,
	)
	request, err := scanRequest(row)
	if errors.Is(err, sql.ErrNoRows) {
		return domain.HumanRequest{}, repository.ErrNotFound
	}
	if err != nil {
		return domain.HumanRequest{}, fmt.Errorf("get request: %w", err)
	}
	return request, nil
}

func (store *Store) ListRequests(
	ctx context.Context,
	status domain.RequestStatus,
	limit int,
	beforeCreatedAt int64,
	beforeID string,
) ([]domain.HumanRequest, error) {
	if limit <= 0 || limit > 500 {
		limit = 100
	}
	query := "SELECT " + requestSummaryColumns + " FROM human_requests"
	arguments := []any{}
	conditions := []string{}
	if status != "" {
		conditions = append(conditions, "status = ?")
		arguments = append(arguments, status)
	}
	if status == domain.StatusPending {
		conditions = append(conditions, "auto_reply_rule_id IS NULL")
	}
	if beforeCreatedAt > 0 && beforeID != "" {
		conditions = append(conditions, "(created_at < ? OR (created_at = ? AND id < ?))")
		arguments = append(arguments, beforeCreatedAt, beforeCreatedAt, beforeID)
	}
	if len(conditions) > 0 {
		query += " WHERE " + strings.Join(conditions, " AND ")
	}
	query += " ORDER BY created_at DESC, id DESC LIMIT ?"
	arguments = append(arguments, limit)
	rows, err := store.database.QueryContext(ctx, query, arguments...)
	if err != nil {
		return nil, fmt.Errorf("list requests: %w", err)
	}
	defer rows.Close()
	requests := make([]domain.HumanRequest, 0)
	for rows.Next() {
		request, err := scanRequestSummary(rows)
		if err != nil {
			return nil, fmt.Errorf("scan request: %w", err)
		}
		requests = append(requests, request)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate requests: %w", err)
	}
	return requests, nil
}

func scanRequestSummary(row scanner) (domain.HumanRequest, error) {
	var request domain.HumanRequest
	var streamRequested int
	var conversationID, answerSource, autoRuleID, autoLabel, claimOwner sql.NullString
	var draftText, draftDeviceID sql.NullString
	var claimExpiresAt, clientLastSeenAt, readAt, draftUpdatedAt, answeredAt sql.NullInt64
	err := row.Scan(
		&request.ID, &request.Model, &request.Preview, &request.ContextChars,
		&request.MessageCount, &request.SystemCount, &request.ToolCount,
		&request.AttachmentCount, &request.Status,
		&request.Mode, &request.Source, &conversationID, &streamRequested,
		&request.StreamChunkCount, &answerSource, &autoRuleID, &autoLabel,
		&claimOwner, &claimExpiresAt, &clientLastSeenAt, &readAt, &draftText,
		&draftUpdatedAt, &draftDeviceID, &request.CreatedAt,
		&request.UpdatedAt, &answeredAt, &request.ExpiresAt,
	)
	if err != nil {
		return domain.HumanRequest{}, err
	}
	request.ConversationID = conversationID.String
	request.StreamRequested = streamRequested != 0
	request.AnswerSource = answerSource.String
	request.AutoReplyRuleID = autoRuleID.String
	request.AutoReplyLabel = autoLabel.String
	request.ClaimOwner = claimOwner.String
	request.ClaimExpiresAt = claimExpiresAt.Int64
	request.ClientLastSeenAt = clientLastSeenAt.Int64
	request.ReadAt = readAt.Int64
	request.Draft = draftText.String
	request.DraftUpdatedAt = draftUpdatedAt.Int64
	request.DraftDeviceID = draftDeviceID.String
	request.AnsweredAt = answeredAt.Int64
	return request, nil
}

type scanner interface {
	Scan(...any) error
}

func scanRequest(row scanner) (domain.HumanRequest, error) {
	var request domain.HumanRequest
	var messagesJSON string
	var toolsJSON string
	var streamRequested int
	var answer, responseJSON, answerSource, conversationID, autoRuleID sql.NullString
	var autoLabel, autoText, claimOwner, apiKeyID sql.NullString
	var draftText, draftDeviceID sql.NullString
	var answeredAt, autoDueAt, claimExpiresAt, clientLastSeenAt sql.NullInt64
	var readAt, draftUpdatedAt sql.NullInt64
	err := row.Scan(
		&request.ID,
		&request.Model,
		&messagesJSON,
		&toolsJSON,
		&request.Preview,
		&request.ContextChars,
		&request.MessageCount,
		&request.SystemCount,
		&request.ToolCount,
		&request.AttachmentCount,
		&request.Status,
		&request.Mode,
		&request.Source,
		&conversationID,
		&streamRequested,
		&request.StreamChunkCount,
		&answer,
		&responseJSON,
		&answerSource,
		&autoRuleID,
		&autoDueAt,
		&autoLabel,
		&autoText,
		&claimOwner,
		&claimExpiresAt,
		&clientLastSeenAt,
		&apiKeyID,
		&readAt,
		&draftText,
		&draftUpdatedAt,
		&draftDeviceID,
		&request.CreatedAt,
		&request.UpdatedAt,
		&answeredAt,
		&request.ExpiresAt,
	)
	if err != nil {
		return domain.HumanRequest{}, err
	}
	if err := json.Unmarshal([]byte(messagesJSON), &request.Messages); err != nil {
		return domain.HumanRequest{}, fmt.Errorf("decode messages: %w", err)
	}
	if err := json.Unmarshal([]byte(toolsJSON), &request.Tools); err != nil {
		return domain.HumanRequest{}, fmt.Errorf("decode tools: %w", err)
	}
	request.StreamRequested = streamRequested != 0
	request.Answer = answer.String
	request.AnswerSource = answerSource.String
	request.ConversationID = conversationID.String
	request.AutoReplyRuleID = autoRuleID.String
	request.AutoReplyDueAt = autoDueAt.Int64
	request.AutoReplyLabel = autoLabel.String
	request.AutoReplyText = autoText.String
	request.ClaimOwner = claimOwner.String
	request.ClaimExpiresAt = claimExpiresAt.Int64
	request.ClientLastSeenAt = clientLastSeenAt.Int64
	request.APIKeyID = apiKeyID.String
	request.ReadAt = readAt.Int64
	request.Draft = draftText.String
	request.DraftUpdatedAt = draftUpdatedAt.Int64
	request.DraftDeviceID = draftDeviceID.String
	request.AnsweredAt = answeredAt.Int64
	if responseJSON.Valid {
		var response domain.ResponseMessage
		if err := json.Unmarshal([]byte(responseJSON.String), &response); err != nil {
			return domain.HumanRequest{}, fmt.Errorf("decode response: %w", err)
		}
		request.Response = &response
	}
	return request, nil
}

func (store *Store) ListChunks(
	ctx context.Context,
	requestID string,
	afterPosition int,
) ([]domain.StreamChunk, error) {
	rows, err := store.database.QueryContext(ctx, `
		SELECT request_id, COALESCE(chunk_id, ''), position, content, created_at
		FROM human_stream_chunks
		WHERE request_id = ? AND position > ?
		ORDER BY position
	`, requestID, afterPosition)
	if err != nil {
		return nil, fmt.Errorf("list stream chunks: %w", err)
	}
	defer rows.Close()
	chunks := make([]domain.StreamChunk, 0)
	for rows.Next() {
		var chunk domain.StreamChunk
		if err := rows.Scan(
			&chunk.RequestID,
			&chunk.ChunkID,
			&chunk.Position,
			&chunk.Content,
			&chunk.CreatedAt,
		); err != nil {
			return nil, fmt.Errorf("scan stream chunk: %w", err)
		}
		chunks = append(chunks, chunk)
	}
	return chunks, rows.Err()
}

func (store *Store) AppendChunk(
	ctx context.Context,
	requestID string,
	chunkID string,
	content string,
	idleTimeout time.Duration,
) (domain.StreamChunk, bool, error) {
	content = strings.TrimSpace(content)
	if content == "" {
		return domain.StreamChunk{}, false, errors.New("stream chunk must not be empty")
	}
	if chunkID == "" {
		var err error
		chunkID, err = domain.NewID("chunk")
		if err != nil {
			return domain.StreamChunk{}, false, err
		}
	}
	transaction, err := store.database.BeginTx(ctx, nil)
	if err != nil {
		return domain.StreamChunk{}, false, fmt.Errorf("begin append chunk: %w", err)
	}
	defer transaction.Rollback()
	var existing domain.StreamChunk
	err = transaction.QueryRowContext(ctx, `
		SELECT request_id, chunk_id, position, content, created_at
		FROM human_stream_chunks
		WHERE request_id = ? AND chunk_id = ?
	`, requestID, chunkID).Scan(
		&existing.RequestID,
		&existing.ChunkID,
		&existing.Position,
		&existing.Content,
		&existing.CreatedAt,
	)
	if err == nil {
		return existing, false, nil
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return domain.StreamChunk{}, false, fmt.Errorf("find idempotent chunk: %w", err)
	}

	now := time.Now()
	var status domain.RequestStatus
	if err := transaction.QueryRowContext(
		ctx,
		"SELECT status FROM human_requests WHERE id = ?",
		requestID,
	).Scan(&status); errors.Is(err, sql.ErrNoRows) {
		return domain.StreamChunk{}, false, repository.ErrNotFound
	} else if err != nil {
		return domain.StreamChunk{}, false, fmt.Errorf("read request status: %w", err)
	}
	if status != domain.StatusPending {
		return domain.StreamChunk{}, false, repository.ErrNotPending
	}
	var position int
	err = transaction.QueryRowContext(ctx, `
		UPDATE human_requests
		SET stream_chunk_count = stream_chunk_count + 1,
			updated_at = ?, expires_at = ?, auto_reply_due_at = NULL,
			draft_text = NULL, draft_updated_at = NULL, draft_device_id = NULL
		WHERE id = ? AND status = 'pending'
		RETURNING stream_chunk_count
	`, now.UnixMilli(), now.Add(idleTimeout).Unix(), requestID).Scan(&position)
	if errors.Is(err, sql.ErrNoRows) {
		return domain.StreamChunk{}, false, repository.ErrNotPending
	}
	if err != nil {
		return domain.StreamChunk{}, false, fmt.Errorf("reserve chunk position: %w", err)
	}
	chunk := domain.StreamChunk{
		RequestID: requestID,
		ChunkID:   chunkID,
		Position:  position,
		Content:   content,
		CreatedAt: now.UnixMilli(),
	}
	if _, err := transaction.ExecContext(ctx, `
		INSERT INTO human_stream_chunks(request_id, chunk_id, position, content, created_at)
		VALUES (?, ?, ?, ?, ?)
	`, chunk.RequestID, chunk.ChunkID, chunk.Position, chunk.Content, chunk.CreatedAt); err != nil {
		return domain.StreamChunk{}, false, fmt.Errorf("insert stream chunk: %w", err)
	}
	if err := store.bumpQueueVersion(ctx, transaction); err != nil {
		return domain.StreamChunk{}, false, err
	}
	if err := store.insertEvent(ctx, transaction, "request.chunk", requestID, map[string]any{
		"position": chunk.Position, "chunk_id": chunk.ChunkID, "content": chunk.Content,
	}); err != nil {
		return domain.StreamChunk{}, false, err
	}
	if err := transaction.Commit(); err != nil {
		return domain.StreamChunk{}, false, fmt.Errorf("commit stream chunk: %w", err)
	}
	return chunk, true, nil
}

func (store *Store) CompleteRequest(
	ctx context.Context,
	requestID string,
	answerSource string,
) (domain.HumanRequest, error) {
	transaction, err := store.database.BeginTx(ctx, nil)
	if err != nil {
		return domain.HumanRequest{}, fmt.Errorf("begin completion: %w", err)
	}
	defer transaction.Rollback()
	var status domain.RequestStatus
	if err := transaction.QueryRowContext(
		ctx,
		"SELECT status FROM human_requests WHERE id = ?",
		requestID,
	).Scan(&status); errors.Is(err, sql.ErrNoRows) {
		return domain.HumanRequest{}, repository.ErrNotFound
	} else if err != nil {
		return domain.HumanRequest{}, fmt.Errorf("read request status: %w", err)
	}
	if status != domain.StatusPending {
		return domain.HumanRequest{}, repository.ErrNotPending
	}
	rows, err := transaction.QueryContext(ctx, `
		SELECT content FROM human_stream_chunks
		WHERE request_id = ? ORDER BY position
	`, requestID)
	if err != nil {
		return domain.HumanRequest{}, fmt.Errorf("read completion chunks: %w", err)
	}
	var answer strings.Builder
	for rows.Next() {
		var content string
		if err := rows.Scan(&content); err != nil {
			rows.Close()
			return domain.HumanRequest{}, fmt.Errorf("scan completion chunk: %w", err)
		}
		answer.WriteString(content)
	}
	if err := rows.Close(); err != nil {
		return domain.HumanRequest{}, fmt.Errorf("close completion chunks: %w", err)
	}
	if err := rows.Err(); err != nil {
		return domain.HumanRequest{}, fmt.Errorf("iterate completion chunks: %w", err)
	}
	if answer.Len() == 0 {
		return domain.HumanRequest{}, repository.ErrNoStreamChunks
	}
	now := time.Now()
	responseJSON, _ := json.Marshal(domain.TextResponse(answer.String()))
	result, err := transaction.ExecContext(ctx, `
		UPDATE human_requests
		SET status = 'answered', answer = ?, response_json = ?, answered_at = ?,
			updated_at = ?, answer_source = ?, claim_owner = NULL, claim_expires_at = NULL,
			draft_text = NULL, draft_updated_at = NULL, draft_device_id = NULL,
			read_at = COALESCE(read_at, ?)
		WHERE id = ? AND status = 'pending'
	`, answer.String(), string(responseJSON), now.Unix(), now.UnixMilli(), answerSource, now.UnixMilli(), requestID)
	if err != nil {
		return domain.HumanRequest{}, fmt.Errorf("complete request: %w", err)
	}
	if affected, _ := result.RowsAffected(); affected != 1 {
		return domain.HumanRequest{}, repository.ErrNotPending
	}
	if err := store.bumpQueueVersion(ctx, transaction); err != nil {
		return domain.HumanRequest{}, err
	}
	if err := store.insertEvent(ctx, transaction, "request.completed", requestID, map[string]any{
		"answer_source": answerSource,
	}); err != nil {
		return domain.HumanRequest{}, err
	}
	if err := store.appendConversationAnswer(ctx, transaction, requestID, domain.TextResponse(answer.String()), now.UnixMilli()); err != nil {
		return domain.HumanRequest{}, err
	}
	if err := transaction.Commit(); err != nil {
		return domain.HumanRequest{}, fmt.Errorf("commit completion: %w", err)
	}
	return store.GetRequest(ctx, requestID)
}

func (store *Store) AnswerRequest(
	ctx context.Context,
	requestID string,
	content string,
	answerSource string,
) (domain.HumanRequest, error) {
	return store.AnswerResponse(ctx, requestID, domain.TextResponse(content), answerSource)
}

func (store *Store) AnswerResponse(
	ctx context.Context,
	requestID string,
	response *domain.ResponseMessage,
	answerSource string,
) (domain.HumanRequest, error) {
	transaction, err := store.database.BeginTx(ctx, nil)
	if err != nil {
		return domain.HumanRequest{}, fmt.Errorf("begin answer: %w", err)
	}
	defer transaction.Rollback()
	now := time.Now()
	responseJSON, err := json.Marshal(response)
	if err != nil {
		return domain.HumanRequest{}, fmt.Errorf("encode response: %w", err)
	}
	content := response.Text()
	result, err := transaction.ExecContext(ctx, `
		UPDATE human_requests
		SET status = 'answered', answer = ?, response_json = ?, answered_at = ?,
			updated_at = ?, answer_source = ?, claim_owner = NULL, claim_expires_at = NULL,
			draft_text = NULL, draft_updated_at = NULL, draft_device_id = NULL,
			read_at = COALESCE(read_at, ?)
		WHERE id = ? AND status = 'pending' AND stream_chunk_count = 0
	`, content, string(responseJSON), now.Unix(), now.UnixMilli(), answerSource, now.UnixMilli(), requestID)
	if err != nil {
		return domain.HumanRequest{}, fmt.Errorf("answer request: %w", err)
	}
	if affected, _ := result.RowsAffected(); affected != 1 {
		var existing int
		if getErr := transaction.QueryRowContext(
			ctx,
			"SELECT COUNT(*) FROM human_requests WHERE id = ?",
			requestID,
		).Scan(&existing); getErr != nil {
			return domain.HumanRequest{}, fmt.Errorf("inspect unanswered request: %w", getErr)
		}
		if existing == 0 {
			return domain.HumanRequest{}, repository.ErrNotFound
		}
		var chunkCount int
		if getErr := transaction.QueryRowContext(
			ctx,
			"SELECT stream_chunk_count FROM human_requests WHERE id = ?",
			requestID,
		).Scan(&chunkCount); getErr != nil {
			return domain.HumanRequest{}, fmt.Errorf("inspect request chunks: %w", getErr)
		}
		if chunkCount > 0 {
			return domain.HumanRequest{}, repository.ErrHasStreamChunks
		}
		return domain.HumanRequest{}, repository.ErrNotPending
	}
	if err := store.bumpQueueVersion(ctx, transaction); err != nil {
		return domain.HumanRequest{}, err
	}
	if err := store.insertEvent(ctx, transaction, "request.answered", requestID, map[string]any{
		"answer_source": answerSource, "tool_call": len(response.ToolCalls) > 0,
	}); err != nil {
		return domain.HumanRequest{}, err
	}
	if err := store.appendConversationAnswer(ctx, transaction, requestID, response, now.UnixMilli()); err != nil {
		return domain.HumanRequest{}, err
	}
	if err := transaction.Commit(); err != nil {
		return domain.HumanRequest{}, fmt.Errorf("commit answer: %w", err)
	}
	return store.GetRequest(ctx, requestID)
}

func (store *Store) PendingCount(ctx context.Context) (int, error) {
	var count int
	err := store.database.QueryRowContext(ctx, `
		SELECT COUNT(*) FROM human_requests
		WHERE status = 'pending' AND auto_reply_rule_id IS NULL
	`).Scan(&count)
	if err != nil {
		return 0, fmt.Errorf("count pending requests: %w", err)
	}
	return count, nil
}

type executor interface {
	ExecContext(context.Context, string, ...any) (sql.Result, error)
}

func (store *Store) bumpQueueVersion(ctx context.Context, exec executor) error {
	_, err := exec.ExecContext(ctx, `
		INSERT INTO app_meta(key, value) VALUES ('queue_version', 1)
		ON CONFLICT(key) DO UPDATE SET value = value + 1
	`)
	if err != nil {
		return fmt.Errorf("bump queue version: %w", err)
	}
	return nil
}

func boolInt(value bool) int {
	if value {
		return 1
	}
	return 0
}

func nullString(value string) any {
	if strings.TrimSpace(value) == "" {
		return nil
	}
	return value
}

func nullInt64(value int64) any {
	if value == 0 {
		return nil
	}
	return value
}

func (store *Store) appendConversationAnswer(ctx context.Context, transaction *sql.Tx, requestID string, response *domain.ResponseMessage, createdAt int64) error {
	messageID, err := domain.NewID("msg")
	if err != nil {
		return err
	}
	var toolCalls any
	if len(response.ToolCalls) > 0 {
		encoded, _ := json.Marshal(response.ToolCalls)
		toolCalls = string(encoded)
	}
	content := "null"
	if len(response.Content) > 0 {
		content = string(response.Content)
	}
	_, err = transaction.ExecContext(ctx, `
		INSERT INTO conversation_messages(id, conversation_id, role, content_json, tool_calls_json, request_id, created_at)
		SELECT ?, conversation_id, 'assistant', ?, ?, ?, ? FROM human_requests
		WHERE id = ? AND conversation_id IS NOT NULL
		ON CONFLICT(request_id) DO NOTHING
	`, messageID, content, toolCalls, requestID, createdAt, requestID)
	if err != nil {
		return fmt.Errorf("append conversation answer: %w", err)
	}
	_, err = transaction.ExecContext(ctx, `UPDATE conversations SET updated_at=? WHERE id=(SELECT conversation_id FROM human_requests WHERE id=?)`, createdAt, requestID)
	return err
}
