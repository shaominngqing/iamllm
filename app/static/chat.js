(() => {
  const app = document.querySelector(".chat-app");
  if (!app) return;

  const elements = {
    title: document.querySelector("#conversation-title"),
    sidebarTitle: document.querySelector("#sidebar-conversation-title"),
    messages: document.querySelector("#chat-messages"),
    welcome: document.querySelector("#welcome-message"),
    form: document.querySelector("#chat-form"),
    input: document.querySelector("#message-input"),
    imageInput: document.querySelector("#image-input"),
    preview: document.querySelector("#upload-preview"),
    waiting: document.querySelector("#waiting-bar"),
    waitingCopy: document.querySelector("#waiting-copy"),
    error: document.querySelector("#chat-error"),
    send: document.querySelector("#send-button"),
    newChat: document.querySelector("#new-chat-button"),
    connection: document.querySelector("#connection-status"),
  };

  const state = {
    conversationId: window.localStorage.getItem("iamllm_conversation_id"),
    imageUrls: [],
    pending: false,
    eventSource: null,
    uploading: false,
    expiresAt: null,
    liveChunkCount: 0,
    autoReply: null,
  };
  const defaultWaitingCopy = elements.waitingCopy.textContent;

  const updateWaitingCopy = () => {
    if (!state.pending) return;
    if (state.autoReply) {
      const seconds = Math.max(0, Math.ceil((state.autoReply.due_at - Date.now()) / 1000));
      elements.waitingCopy.textContent = `规则「${state.autoReply.label}」将在约 ${seconds} 秒后返回响应`;
      return;
    }
    if (!state.expiresAt) {
      elements.waitingCopy.textContent = defaultWaitingCopy;
      return;
    }
    const seconds = Math.max(0, Math.ceil(state.expiresAt - Date.now() / 1000));
    const clock = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
    elements.waitingCopy.textContent = state.liveChunkCount
      ? `正在流式输出 · 已收到 ${state.liveChunkCount} 个 chunk · 空闲 ${clock} 后自动结束`
      : `正在等待首个响应片段 · ${clock}`;
  };

  const request = async (url, options = {}) => {
    const response = await fetch(url, options);
    let body = null;
    try {
      body = await response.json();
    } catch (_) {
      body = {};
    }
    if (!response.ok) {
      const detail = body.detail;
      throw new Error(
        typeof detail === "string" ? detail : "请求失败，请稍后再试"
      );
    }
    return body;
  };

  const setError = (message = "") => {
    elements.error.textContent = message;
    elements.error.hidden = !message;
  };

  const setPending = (pending) => {
    state.pending = pending;
    elements.waiting.hidden = !pending;
    elements.send.disabled = pending || state.uploading;
    elements.input.disabled = pending;
    elements.imageInput.disabled = pending;
  };

  const contentPart = (content, className = "message-text") => {
    const container = document.createElement("div");
    container.className = className;
    const pattern = /```([\w-]*)\n?([\s\S]*?)```/g;
    let cursor = 0;
    let match;
    while ((match = pattern.exec(content)) !== null) {
      if (match.index > cursor) {
        const text = document.createElement("span");
        text.textContent = content.slice(cursor, match.index);
        container.appendChild(text);
      }
      const pre = document.createElement("pre");
      const code = document.createElement("code");
      code.textContent = match[2].replace(/\n$/, "");
      if (match[1]) code.dataset.language = match[1];
      pre.appendChild(code);
      container.appendChild(pre);
      cursor = pattern.lastIndex;
    }
    if (cursor < content.length || !container.childNodes.length) {
      const text = document.createElement("span");
      text.textContent = content.slice(cursor);
      container.appendChild(text);
    }
    return container;
  };

  const renderMessage = (message) => {
    const article = document.createElement("article");
    article.className = `chat-bubble chat-bubble-${message.role}`;
    if (message.streaming) article.classList.add("chat-bubble-streaming");

    const head = document.createElement("div");
    head.className = "chat-bubble-head";
    const role = document.createElement("span");
    role.className = "chat-bubble-role";
    role.textContent = message.role === "user"
      ? "You"
      : `${app.dataset.modelName || "Assistant"}${message.streaming ? " · Streaming" : ""}`;
    head.appendChild(role);
    if (message.role === "assistant" && typeof message.content === "string") {
      const copy = document.createElement("button");
      copy.type = "button";
      copy.className = "message-copy";
      copy.textContent = "复制";
      copy.addEventListener("click", async () => {
        try { await navigator.clipboard.writeText(message.content); copy.textContent = "已复制"; }
        catch { copy.textContent = "复制失败"; }
        window.setTimeout(() => { copy.textContent = "复制"; }, 1600);
      });
      head.appendChild(copy);
    }
    article.appendChild(head);

    if (typeof message.content === "string") {
      article.appendChild(contentPart(message.content));
    } else if (Array.isArray(message.content)) {
      message.content.forEach((part) => {
        if (part.type === "text") {
          article.appendChild(contentPart(part.text));
        }
        if (part.type === "image_url" && part.image_url?.url) {
          const image = document.createElement("img");
          image.src = part.image_url.url;
          image.alt = "对话图片";
          image.loading = "lazy";
          article.appendChild(image);
        }
      });
    }

    if (Array.isArray(message.tool_calls)) {
      message.tool_calls.forEach((toolCall) => {
        const tool = document.createElement("div");
        tool.className = "chat-tool-call";
        tool.textContent = `Tool call · ${toolCall.function?.name || "unknown"}`;
        article.appendChild(tool);
      });
    }
    return article;
  };

  const renderConversation = (conversation) => {
    elements.title.textContent = conversation.title || "新对话";
    elements.sidebarTitle.textContent = conversation.title || "新对话";
    const fragments = document.createDocumentFragment();
    if (!conversation.messages.length) {
      elements.welcome.hidden = false;
    } else {
      elements.welcome.hidden = true;
      conversation.messages.forEach((message) => {
        fragments.appendChild(renderMessage(message));
      });
      if (conversation.live_response?.content) {
        fragments.appendChild(renderMessage({
          role: "assistant",
          content: conversation.live_response.content,
          streaming: true,
        }));
      }
    }
    elements.messages
      .querySelectorAll(".chat-bubble")
      .forEach((message) => message.remove());
    elements.messages.appendChild(fragments);
    elements.messages.scrollTop = elements.messages.scrollHeight;
    state.expiresAt = conversation.live_response?.expires_at || conversation.expires_at || null;
    state.liveChunkCount = conversation.live_response?.chunks?.length || 0;
    state.autoReply = conversation.auto_reply || null;
    setPending(Boolean(conversation.pending));
    updateWaitingCopy();
  };

  const createConversation = async () => {
    const conversation = await request("/chat/api/conversations", {
      method: "POST",
    });
    state.conversationId = conversation.id;
    window.localStorage.setItem("iamllm_conversation_id", conversation.id);
    return conversation;
  };

  const loadConversation = async () => {
    if (!state.conversationId) await createConversation();
    try {
      const conversation = await request(
        `/chat/api/conversations/${state.conversationId}`
      );
      renderConversation(conversation);
      if (conversation.pending) startRealtime();
      elements.connection.classList.remove("offline");
    } catch (error) {
      if (error.message === "Conversation not found") {
        await createConversation();
        return loadConversation();
      }
      elements.connection.classList.add("offline");
      setError(error.message);
    }
  };

  const pollOnce = async () => {
    if (!state.conversationId) return;
    try {
      const conversation = await request(
        `/chat/api/conversations/${state.conversationId}`
      );
      renderConversation(conversation);
      if (!conversation.pending) stopRealtime();
    } catch (error) {
      setError(error.message);
    }
  };

  const startRealtime = () => {
    if (state.eventSource || !window.EventSource) return;
    state.eventSource = new EventSource(
      `/chat/api/conversations/${state.conversationId}/events`
    );
    state.eventSource.onmessage = pollOnce;
    state.eventSource.onopen = () => elements.connection.classList.remove("offline");
    state.eventSource.onerror = () => elements.connection.classList.add("offline");
  };

  const stopRealtime = () => {
    if (state.eventSource) state.eventSource.close();
    state.eventSource = null;
    elements.connection.classList.remove("offline");
  };

  window.setInterval(updateWaitingCopy, 1_000);

  const renderUploadPreview = () => {
    elements.preview.replaceChildren();
    state.imageUrls.forEach((url, index) => {
      const wrapper = document.createElement("div");
      const image = document.createElement("img");
      image.src = url;
      image.alt = `待发送图片 ${index + 1}`;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "×";
      remove.setAttribute("aria-label", "移除图片");
      remove.addEventListener("click", () => {
        state.imageUrls.splice(index, 1);
        renderUploadPreview();
      });
      wrapper.append(image, remove);
      elements.preview.appendChild(wrapper);
    });
    elements.preview.hidden = state.imageUrls.length === 0;
  };

  const uploadImage = async (file) => {
    const form = new FormData();
    form.append("image", file);
    return request("/chat/api/uploads", {method: "POST", body: form});
  };

  elements.imageInput.addEventListener("change", async () => {
    const files = Array.from(elements.imageInput.files || []);
    if (files.length + state.imageUrls.length > 4) {
      setError("每条消息最多发送 4 张图片");
      elements.imageInput.value = "";
      return;
    }
    state.uploading = true;
    elements.send.disabled = true;
    setError("");
    try {
      for (const file of files) {
        const uploaded = await uploadImage(file);
        state.imageUrls.push(uploaded.url);
      }
      renderUploadPreview();
    } catch (error) {
      setError(error.message);
    } finally {
      state.uploading = false;
      elements.send.disabled = state.pending;
      elements.imageInput.value = "";
    }
  });

  elements.form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (state.pending || state.uploading) return;
    const text = elements.input.value.trim();
    if (!text && !state.imageUrls.length) return;
    setError("");
    setPending(true);
    try {
      await request(
        `/chat/api/conversations/${state.conversationId}/messages`,
        {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({text, image_urls: state.imageUrls}),
        }
      );
      elements.input.value = "";
      elements.input.style.height = "auto";
      state.imageUrls = [];
      renderUploadPreview();
      await pollOnce();
      if (state.pending) startRealtime();
    } catch (error) {
      setPending(false);
      setError(error.message);
    }
  });

  elements.input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      elements.form.requestSubmit();
    }
  });
  elements.input.addEventListener("input", () => {
    elements.input.style.height = "auto";
    elements.input.style.height = `${Math.min(elements.input.scrollHeight, 160)}px`;
  });

  document.querySelectorAll("[data-prompt]").forEach((button) => {
    button.addEventListener("click", () => {
      elements.input.value = button.dataset.prompt || "";
      elements.input.dispatchEvent(new Event("input"));
      elements.input.focus();
    });
  });

  elements.newChat.addEventListener("click", async () => {
    stopRealtime();
    setError("");
    state.imageUrls = [];
    renderUploadPreview();
    await createConversation();
    await loadConversation();
    elements.input.focus();
  });

  loadConversation();
})();
