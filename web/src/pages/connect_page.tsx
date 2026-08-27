import { useEffect, useState } from "react";
import { api } from "../api";
import type { Overview } from "../types";
import { Icon, PageHead } from "../ui";

export function ConnectPage() {
  const [copied, setCopied] = useState("");
  const [overview, setOverview] = useState<Overview | null>(null);

  useEffect(() => {
    api.request<Overview>("/admin/api/v1/overview").then(setOverview).catch(() => {});
  }, []);

  const base = (overview?.public_base_url || location.origin).replace(/\/$/, "");
  const model = overview?.model || "iam-human";

  async function copy(label: string, value: string) {
    await navigator.clipboard.writeText(value);
    setCopied(label);
    window.setTimeout(() => setCopied(""), 1600);
  }

  return (
    <section className="page narrow">
      <PageHead eyebrow="QUICK START" title="接入指南" subtitle="选你常用的客户端，复制地址，再填入一把 API Key。" />
      <div className="connectNotice"><Icon name="shield" /><div><b>先创建一把分享钥匙</b><p>不要把环境总钥匙发给别人。分享钥匙可以随时撤销，也能单独限制额度。</p></div></div>
      <div className="guide">
        <article className="violet">
          <div className="clientTitle"><span><Icon name="code" /></span><b>OpenAI / OpenCode</b></div>
          <div className="copyField"><code>{base}/v1</code><button aria-label="复制 OpenAI 地址" onClick={() => copy("openai", `${base}/v1`)}>{copied === "openai" ? <Icon name="check" /> : <Icon name="copy" />}</button></div>
          <p>使用 POST /v1/chat/completions 或 /v1/responses。</p>
        </article>
        <article className="orange">
          <div className="clientTitle"><span><Icon name="spark" /></span><b>Claude Code</b></div>
          <div className="copyField"><code>{base}</code><button aria-label="复制 Claude 地址" onClick={() => copy("claude", base)}>{copied === "claude" ? <Icon name="check" /> : <Icon name="copy" />}</button></div>
          <p>ANTHROPIC_BASE_URL 使用服务根地址，不要额外追加 /v1。</p>
        </article>
        <article className="blue">
          <div className="clientTitle"><span><Icon name="bolt" /></span><b>Gemini</b></div>
          <div className="copyField"><code>{base}</code><button aria-label="复制 Gemini 地址" onClick={() => copy("gemini", base)}>{copied === "gemini" ? <Icon name="check" /> : <Icon name="copy" />}</button></div>
          <p>支持 generateContent、streamGenerateContent 和 countTokens。</p>
        </article>
        <pre>{`curl -N ${base}/v1/chat/completions \\\n+  -H 'Authorization: Bearer sk-...' \\\n+  -H 'Content-Type: application/json' \\\n+  -d '{"model":"${model}","stream":true,"messages":[{"role":"user","content":"你好"}]}'`}</pre>
      </div>
    </section>
  );
}
