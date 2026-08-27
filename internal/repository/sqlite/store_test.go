package sqlite

import (
	"context"
	"encoding/json"
	"errors"
	"path/filepath"
	"sync"
	"testing"
	"time"

	"iamllm/internal/domain"
	"iamllm/internal/repository"
)

func TestStoreMigratesAndCompletesIdempotentStream(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "iamllm.db")
	store, err := Open(ctx, path)
	if err != nil {
		t.Fatalf("open store: %v", err)
	}
	input := domain.RequestInput{
		Model:    "human",
		Messages: []domain.Message{{Role: "user", Content: json.RawMessage(`"你好"`)}},
		Stream:   true,
	}
	request, err := domain.NewHumanRequest(input, time.Hour)
	if err != nil {
		t.Fatalf("new request: %v", err)
	}
	if err := store.CreateRequest(ctx, request); err != nil {
		t.Fatalf("create request: %v", err)
	}
	first, created, err := store.AppendChunk(ctx, request.ID, "mobile-chunk-1", "你", time.Minute)
	if err != nil || !created {
		t.Fatalf("append first chunk: created=%v err=%v", created, err)
	}
	replayed, created, err := store.AppendChunk(ctx, request.ID, "mobile-chunk-1", "你", time.Minute)
	if err != nil || created {
		t.Fatalf("replay first chunk: created=%v err=%v", created, err)
	}
	if replayed.Position != first.Position {
		t.Fatalf("idempotency changed position: %d != %d", replayed.Position, first.Position)
	}
	if _, created, err := store.AppendChunk(ctx, request.ID, "mobile-chunk-2", "好", time.Minute); err != nil || !created {
		t.Fatalf("append second chunk: created=%v err=%v", created, err)
	}
	if _, err := store.AnswerRequest(ctx, request.ID, "替换答案", "human"); !errors.Is(err, repository.ErrHasStreamChunks) {
		t.Fatalf("expected direct answer to preserve stream chunks, got %v", err)
	}
	answered, err := store.CompleteRequest(ctx, request.ID, "human_stream")
	if err != nil {
		t.Fatalf("complete request: %v", err)
	}
	if answered.Answer != "你好" || answered.StreamChunkCount != 2 || answered.Status != domain.StatusAnswered {
		t.Fatalf("unexpected answer: %#v", answered)
	}
	if _, _, err := store.AppendChunk(ctx, request.ID, "mobile-chunk-3", "！", time.Minute); !errors.Is(err, repository.ErrNotPending) {
		t.Fatalf("expected not pending, got %v", err)
	}
	if err := store.Close(); err != nil {
		t.Fatalf("close store: %v", err)
	}

	reopened, err := Open(ctx, path)
	if err != nil {
		t.Fatalf("reopen store: %v", err)
	}
	defer reopened.Close()
	stored, err := reopened.GetRequest(ctx, request.ID)
	if err != nil || stored.Answer != "你好" {
		t.Fatalf("read persisted answer: %#v err=%v", stored, err)
	}
}

func TestSchemaUsesOneLatestBaseline(t *testing.T) {
	migrations, err := embeddedMigrations()
	if err != nil {
		t.Fatal(err)
	}
	if len(migrations) != 1 || migrations[0].version != 2026082701 || migrations[0].name != "2026082701_initial.sql" {
		t.Fatalf("expected one latest schema baseline, got %#v", migrations)
	}
}

func TestConcurrentChunkReplayIsIdempotent(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "iamllm.db"))
	if err != nil {
		t.Fatalf("open store: %v", err)
	}
	defer store.Close()
	request, err := domain.NewHumanRequest(domain.RequestInput{
		Model:    "human",
		Messages: []domain.Message{{Role: "user", Content: json.RawMessage(`"你好"`)}},
		Stream:   true,
	}, time.Hour)
	if err != nil {
		t.Fatalf("new request: %v", err)
	}
	if err := store.CreateRequest(ctx, request); err != nil {
		t.Fatalf("create request: %v", err)
	}

	const writers = 8
	var wait sync.WaitGroup
	wait.Add(writers)
	created := make(chan bool, writers)
	errorsFound := make(chan error, writers)
	for range writers {
		go func() {
			defer wait.Done()
			_, wasCreated, err := store.AppendChunk(
				ctx,
				request.ID,
				"same-mobile-chunk",
				"你好",
				time.Minute,
			)
			if err != nil {
				errorsFound <- err
				return
			}
			created <- wasCreated
		}()
	}
	wait.Wait()
	close(created)
	close(errorsFound)
	for err := range errorsFound {
		t.Errorf("concurrent append failed: %v", err)
	}
	createdCount := 0
	for value := range created {
		if value {
			createdCount++
		}
	}
	if createdCount != 1 {
		t.Fatalf("expected one inserted chunk, got %d", createdCount)
	}
	chunks, err := store.ListChunks(ctx, request.ID, 0)
	if err != nil || len(chunks) != 1 {
		t.Fatalf("unexpected persisted chunks: %#v err=%v", chunks, err)
	}
}

func TestConversationStatePersistsAcrossDevicesAndClearsOnSend(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "iamllm.db"))
	if err != nil {
		t.Fatalf("open store: %v", err)
	}
	defer store.Close()
	request, err := domain.NewHumanRequest(domain.RequestInput{
		Model:    "human",
		Messages: []domain.Message{{Role: "user", Content: json.RawMessage(`"帮我看看"`)}},
		Stream:   true,
	}, time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.CreateRequest(ctx, request); err != nil {
		t.Fatal(err)
	}

	drafted, err := store.SaveRequestDraft(ctx, request.ID, "我先确认一下", "iphone")
	if err != nil {
		t.Fatalf("save draft: %v", err)
	}
	if drafted.Draft != "我先确认一下" || drafted.DraftDeviceID != "iphone" || drafted.DraftUpdatedAt == 0 {
		t.Fatalf("unexpected shared draft: %#v", drafted)
	}
	read, err := store.MarkRequestRead(ctx, request.ID)
	if err != nil {
		t.Fatalf("mark read: %v", err)
	}
	if read.ReadAt == 0 {
		t.Fatal("read state was not persisted")
	}
	if _, _, err := store.AppendChunk(ctx, request.ID, "chunk-1", "收到", time.Minute); err != nil {
		t.Fatalf("append chunk: %v", err)
	}
	stored, err := store.GetRequest(ctx, request.ID)
	if err != nil {
		t.Fatal(err)
	}
	if stored.Draft != "" || stored.DraftUpdatedAt != 0 || stored.DraftDeviceID != "" {
		t.Fatalf("draft should clear after a successful send: %#v", stored)
	}
}
