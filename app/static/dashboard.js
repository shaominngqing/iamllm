(() => {
  const hero = document.querySelector("#queue-hero");
  if (!hero || !window.EventSource) return;

  const renderedVersion = String(hero.dataset.queueVersion || "");
  const livePill = hero.querySelector(".live-pill");
  let unseenVersion = null;
  let reloadScheduled = false;

  const reloadWhenSafe = () => {
    if (reloadScheduled) return;
    reloadScheduled = true;
    window.setTimeout(() => window.location.reload(), 180);
  };

  const events = new EventSource("/admin/events");
  events.onopen = () => {
    if (livePill) livePill.lastChild.textContent = " 实时监听中，无需刷新";
  };
  events.onmessage = (event) => {
    if (String(event.data) === renderedVersion) return;
    if (document.hidden) {
      unseenVersion = event.data;
      document.title = "● 有新问题 · iamllm";
      return;
    }
    reloadWhenSafe();
  };
  events.onerror = () => {
    if (livePill) livePill.lastChild.textContent = " 正在重新连接…";
  };

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && unseenVersion) reloadWhenSafe();
  });
})();

