import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { api } from "./api";
import type { Page } from "./types";
import { Icon, LogoMark } from "./ui";
import type { IconName } from "./ui";
import { ConnectPage } from "./pages/connect_page";
import { PlaygroundPage } from "./pages/playground_page";
import { KeysPage } from "./pages/keys_page";
import { AutomationPage } from "./pages/automation_page";
import { SettingsPage } from "./pages/settings_page";
import { InboxPage } from "./pages/inbox_page";
import "./styles.css";
import "./playground.css";

function App() {
  const [logged, setLogged] = useState(Boolean(api.access || api.refreshToken));
  const pages: Page[] = ["inbox", "keys", "automation", "connect", "settings"];
  const initial = location.hash.slice(1) as Page;
  const [page, setPageState] = useState<Page>(pages.includes(initial) ? initial : "inbox");
  const [pending, setPending] = useState(0);
  function setPage(next: Page) {
    setPageState(next);
    history.replaceState(null, "", `#${next}`);
  }
  useEffect(() => {
    const sync = () => {
      const next = location.hash.slice(1) as Page;
      if (pages.includes(next)) setPageState(next);
    };
    addEventListener("hashchange", sync);
    return () => removeEventListener("hashchange", sync);
  }, []);
  if (!logged) return <Login onDone={() => setLogged(true)} />;
  if (location.pathname === "/playground") return <PlaygroundPage />;
  return (
    <div className="shell">
      <Sidebar
        page={page}
        setPage={setPage}
        pending={pending}
        logout={() => {
          api.clear();
          setLogged(false);
        }}
      />
      <main>
        {page === "inbox" && <InboxPage onPending={setPending} />}{" "}
        {page === "keys" && <KeysPage />}
        {page === "automation" && <AutomationPage />}
        {page === "connect" && <ConnectPage />}
        {page === "settings" && <SettingsPage />}
      </main>
    </div>
  );
}
function Login({ onDone }: { onDone: () => void }) {
  const [user, setUser] = useState("admin"),
    [password, setPassword] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.login(user, password);
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : "登录失败");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="login">
      <div className="loginStory" aria-hidden="true">
        <div className="loginBrand"><LogoMark /><b>iamllm</b></div>
        <div>
          <span className="signal"><i /> HUMAN ONLINE</span>
          <h2>把你的判断力，<br />接到任何 AI 客户端。</h2>
          <p>标准协议进来，真实的人来回答。上下文、图片、工具调用，一个都不会丢。</p>
        </div>
        <div className="loginProtocol">OPENAI <i /> ANTHROPIC <i /> GEMINI</div>
      </div>
      <form onSubmit={submit} className="loginCard">
        <div className="loginMobileBrand"><LogoMark /><b>iamllm</b></div>
        <p className="eyebrow">CONTROL ROOM</p>
        <h1>欢迎回来</h1>
        <p className="loginIntro">登录后接管会话、自动回复和 API 访问。</p>
        <label>
          <span>用户名</span>
          <div className="inputShell"><Icon name="user" /><input
              value={user}
              onChange={(e) => setUser(e.target.value)}
              autoComplete="username"
            /></div>
        </label>
        <label>
          <span>密码</span>
          <div className="inputShell"><Icon name="lock" /><input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              autoFocus
            /></div>
        </label>
        {error && <div className="error">{error}</div>}
        <button disabled={busy}>{busy ? "正在连接…" : <>进入控制台 <Icon name="arrow" /></>}</button>
        <small className="loginHint"><i className="online" /> 服务数据只保存在你的服务器</small>
      </form>
    </div>
  );
}
function Sidebar({
  page,
  setPage,
  pending,
  logout,
}: {
  page: Page;
  setPage: (p: Page) => void;
  pending: number;
  logout: () => void;
}) {
  const links: [Page, IconName, string, string][] = [
    ["inbox", "inbox", "会话工作台", "接收与回复"],
    ["keys", "key", "API 密钥", "访问与额度"],
    ["connect", "code", "接入指南", "客户端配置"],
    ["automation", "bolt", "自动回复", "规则与话术"],
    ["settings", "settings", "服务设置", "资料与设备"],
  ];
  return (
    <aside>
      <div className="logo">
        <LogoMark />
        <span>
          <strong>iamllm</strong>
          <small>HUMAN MODEL CONSOLE</small>
        </span>
      </div>
      <small className="navLabel">工作空间</small>
      <nav>
        {links.map(([id, icon, label, caption]) => (
          <button
            className={page === id ? "active" : ""}
            onClick={() => setPage(id)}
            key={id}
          >
            <i><Icon name={icon} /></i>
            <span><b>{label}</b><small>{caption}</small></span>
            {id === "inbox" && pending > 0 && <em>{pending}</em>}
          </button>
        ))}
      </nav>
      <div className="asideFoot">
        <div className="serviceCard">
          <i className="online" />
          <span><b>服务正常</b><small>API 正在监听请求</small></span>
        </div>
        <button className="playgroundLink" onClick={() => location.assign("/playground")}>
          <Icon name="spark" /> 打开 Playground <Icon name="external" />
        </button>
        <button className="logout" onClick={logout}><Icon name="logout" /> 退出登录</button>
      </div>
    </aside>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
