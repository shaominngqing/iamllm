package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"iamllm/internal/application"
	"iamllm/internal/config"
	"iamllm/internal/notification"
	"iamllm/internal/repository/sqlite"
	"iamllm/internal/transport/httpapi"
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	settings, err := config.Load()
	if err != nil {
		logger.Error("invalid configuration", "error", err)
		os.Exit(1)
	}
	rootContext, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	store, err := sqlite.Open(rootContext, settings.DatabasePath)
	if err != nil {
		logger.Error("database startup failed", "error", err)
		os.Exit(1)
	}
	defer store.Close()
	if err := store.EnsureProfile(rootContext, settings.ModelName); err != nil {
		logger.Error("profile startup failed", "error", err)
		os.Exit(1)
	}
	location, _ := time.LoadLocation(settings.Timezone)
	notifier := notification.NewWebhook(settings.NotificationURL, settings.PublicBaseURL, settings.NotificationTimeout, logger)
	service := application.New(store, application.Options{
		JobTTL:           settings.JobTTL,
		ResponseTimeout:  settings.ResponseTimeout,
		PollInterval:     settings.PollInterval,
		StreamIdle:       settings.StreamIdle,
		TimeoutFallbacks: settings.TimeoutFallbacks,
		StreamChunkDelay: settings.StreamChunkDelay,
		StreamChunkChars: settings.StreamChunkChars,
		Timezone:         location,
		Notify:           notifier.Enqueue,
	})
	control := application.NewControl(store, application.ControlOptions{
		MasterAPIKey: settings.APIKey, AdminToken: settings.AdminAPIToken,
		AdminUsername: settings.AdminUsername, AdminPassword: settings.AdminPassword,
		SessionSecret: settings.SessionSecret, Timezone: location,
	})
	go service.RunAutomation(rootContext)
	go notifier.Run(rootContext)
	api := httpapi.New(settings, service, control, logger)
	server := &http.Server{
		Addr:              settings.BindAddress,
		Handler:           api.Handler(),
		ReadHeaderTimeout: 10 * time.Second,
		IdleTimeout:       75 * time.Second,
	}
	serverErrors := make(chan error, 1)
	go func() {
		logger.Info(
			"iamllm started",
			"address", settings.BindAddress,
			"database", settings.DatabasePath,
		)
		serverErrors <- server.ListenAndServe()
	}()
	select {
	case <-rootContext.Done():
		logger.Info("shutdown signal received")
	case err := <-serverErrors:
		if !errors.Is(err, http.ErrServerClosed) {
			logger.Error("HTTP server failed", "error", err)
		}
	}
	shutdownContext, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	if err := server.Shutdown(shutdownContext); err != nil {
		logger.Error("graceful shutdown failed", "error", err)
	}
}
