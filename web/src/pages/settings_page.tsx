import { useEffect, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { api, browserDeviceMetadata } from "../api";
import type { AdminDeviceItem, Overview, Profile } from "../types";
import { formatDateTime, Icon, LogoMark, PageHead, relative, Toast } from "../ui";

export function SettingsPage() {
  const [profile, setProfile] = useState<Profile>({
      display_name: "",
      bio: "",
      skills: [],
    }),
    [overview, setOverview] = useState<Overview | null>(null),
    [devices, setDevices] = useState<AdminDeviceItem[]>([]),
    [currentDeviceID, setCurrentDeviceID] = useState(""),
    [pair, setPair] = useState<{
      code: string;
      expires_at: number;
      server_url: string;
      pairing_uri: string;
    } | null>(null),
    [notice, setNotice] = useState(""),
    [copied, setCopied] = useState(false);
  async function load() {
    const [nextProfile, nextOverview, deviceData] = await Promise.all([
      api.request<Profile>("/admin/api/v1/profile"),
      api.request<Overview>("/admin/api/v1/overview"),
      api.request<{ items: AdminDeviceItem[]; current_device_id: string }>(
        "/admin/api/v1/devices",
      ),
    ]);
    setProfile(nextProfile);
    setOverview(nextOverview);
    setDevices(deviceData.items);
    setCurrentDeviceID(deviceData.current_device_id || "");
  }
  useEffect(() => {
    (async () => {
      try {
        await api.request("/admin/api/v1/devices/self", {
          method: "PUT",
          body: JSON.stringify(browserDeviceMetadata()),
        });
      } catch {}
      await load();
    })().catch((e) => setNotice(e instanceof Error ? e.message : "加载失败"));
  }, []);
  async function saveProfile() {
    await api.request("/admin/api/v1/profile", {
      method: "PUT",
      body: JSON.stringify(profile),
    });
    setNotice("公开模型资料已更新，客户端查询 /v1/models 时会看到新内容。");
  }
  async function copyBaseURL() {
    if (!overview) return;
    await navigator.clipboard.writeText(`${overview.public_base_url}/v1`);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }
  const activeDevices = devices.filter((device) => !device.revoked_at);
  const pairQRCode = pair?.pairing_uri || "";
  return (
    <section className="page narrow settingsPage">
      <PageHead
        eyebrow="SERVICE & DEVICES"
        title="服务与设备"
        subtitle="确认服务怎么对外工作，并管理所有登录过后台的设备。"
      >
        <span className="livePill"><i className="online" /> 服务运行正常</span>
      </PageHead>
      {notice && <Toast text={notice} close={() => setNotice("")} />}

      <div className="settingsServiceGrid">
        <article className="serviceOverviewCard">
          <div className="serviceIdentity">
            <LogoMark size={52} />
            <div>
              <small>PUBLIC MODEL ID</small>
              <h2>{overview?.model || "正在读取…"}</h2>
              <p>这是各类客户端真正填写和识别的模型名称。</p>
            </div>
            <span className="status ok"><i className="online" /> ONLINE</span>
          </div>
          <div className="serviceURL">
            <span><small>API BASE URL</small><code>{overview ? `${overview.public_base_url}/v1` : "—"}</code></span>
            <button className="ghost" onClick={copyBaseURL}><Icon name={copied ? "check" : "copy"} />{copied ? "已复制" : "复制地址"}</button>
          </div>
          <dl className="serviceFacts">
            <div><dt>运行核心</dt><dd>{overview ? `${overview.runtime.toUpperCase()} · ${overview.database.toUpperCase()}` : "—"}</dd></div>
            <div><dt>最长等待</dt><dd>{overview ? `${Math.round(overview.response_timeout_seconds / 60)} 分钟` : "—"}</dd></div>
            <div><dt>流式节奏</dt><dd>{overview ? `${overview.stream_chunk_chars} 字 / ${overview.stream_chunk_delay_ms} ms` : "—"}</dd></div>
            <div><dt>部署环境</dt><dd>{overview?.environment || "—"}</dd></div>
          </dl>
        </article>

        <article className="panel form publicProfile">
          <div className="panelTitleRow">
            <div><small className="eyebrow">GET /V1/MODELS</small><h3>客户端可见资料</h3></div>
            <Icon name="external" />
          </div>
          <p className="formHelp">这些内容会随模型查询接口返回，用于客户端展示和模型选择；不参与回答提示词。</p>
          <label>
            对外显示名称
            <input
              value={profile.display_name}
              onChange={(e) =>
                setProfile({ ...profile, display_name: e.target.value })
              }
            />
          </label>
          <label>
            一句话说明
            <textarea
              value={profile.bio}
              onChange={(e) => setProfile({ ...profile, bio: e.target.value })}
            />
          </label>
          <label>
            能力标签
            <input
              value={profile.skills.join("、")}
              onChange={(e) =>
                setProfile({
                  ...profile,
                  skills: e.target.value
                    .split(/[、,]/)
                    .map((x) => x.trim())
                    .filter(Boolean),
                })
              }
            />
          </label>
          <div className="profilePreview">
            <small>客户端预览</small>
            <b>{profile.display_name || overview?.model || "未命名模型"}</b>
            <p>{profile.bio || "还没有填写说明。"}</p>
            <div className="tagList">{profile.skills.map((skill) => <span key={skill}>{skill}</span>)}</div>
          </div>
          <button onClick={() => saveProfile().catch((e) => setNotice(e.message))}><Icon name="check" />保存公开资料</button>
        </article>
      </div>

      <section className="deviceSection">
        <div className="deviceSectionHead">
          <div>
            <small className="eyebrow">TRUSTED DEVICES</small>
            <h2>后台设备</h2>
            <p>设备登录、刷新令牌或使用管理接口时，会自动更新活跃时间和设备信息。</p>
          </div>
          <div className="deviceHeadActions">
            <span>{activeDevices.length} 台有效设备</span>
            <button
              onClick={async () =>
                setPair(
                  await api.request("/admin/api/v1/pairing-codes", {
                    method: "POST",
                    body: JSON.stringify({ label: "Flutter 手机" }),
                  }),
                )
              }
            ><Icon name="plus" />连接新设备</button>
          </div>
        </div>
        {pair && (
          <div className="pair pairWide pairWithQR">
            <div className="pairQR">
              <QRCodeSVG
                value={pairQRCode}
                size={172}
                level="M"
                marginSize={2}
                title="iamllm 手机配对二维码"
              />
            </div>
            <div className="pairCopy">
              <span>打开手机端，点击“扫描二维码”</span>
              <h3>扫一扫，地址和配对码都会自动填写</h3>
              <small>{pair.server_url}</small>
              <div><em>无法扫码时输入</em><b>{pair.code}</b></div>
              <p>10 分钟内有效 · 仅可使用一次 · 二维码不包含管理员密码</p>
            </div>
            <button className="ghost" onClick={() => setPair(null)}>收起</button>
          </div>
        )}
        <div className="deviceGrid">
          {devices.map((device) => {
            const current = device.id === currentDeviceID;
            const active = !device.revoked_at;
            return (
              <article className={`deviceCard ${current ? "current" : ""} ${active ? "" : "revoked"}`} key={device.id}>
                <div className="deviceCardHead">
                  <span className="deviceGlyph"><Icon name={device.platform === "flutter" || device.platform === "android" || device.platform === "ios" ? "message" : "code"} /></span>
                  <div><h3>{device.name}</h3><p>{device.device_model || device.platform || "未上报设备型号"}</p></div>
                  <div className="deviceBadges">{current && <span>当前设备</span>}<span className={active ? "onlineState" : "revokedState"}>{active ? "可用" : "已移除"}</span></div>
                </div>
                <dl className="deviceFacts">
                  <div><dt>系统</dt><dd>{device.os_version || device.platform || "未上报"}</dd></div>
                  <div><dt>应用版本</dt><dd>{device.app_version || "未上报"}</dd></div>
                  <div><dt>首次连接</dt><dd>{formatDateTime(device.created_at)}</dd></div>
                  <div><dt>上次活跃</dt><dd>{device.last_seen_at ? relative(device.last_seen_at) : "尚无记录"}</dd></div>
                  <div><dt>网络地址</dt><dd>{device.ip_address || "未记录"}</dd></div>
                  <div><dt>语言 / 时区</dt><dd>{[device.locale, device.timezone].filter(Boolean).join(" · ") || "未上报"}</dd></div>
                </dl>
                <div className="deviceCardFoot">
                  <small title={device.user_agent}>{device.user_agent ? "浏览器/客户端信息已上报" : "等待设备上报更多信息"}</small>
                  {active && !current && (
                    <button className="danger" onClick={async () => {
                      await api.request(`/admin/api/v1/devices/${device.id}`, { method: "DELETE" });
                      setNotice(`已移除 ${device.name}`);
                      load();
                    }}>移除设备</button>
                  )}
                </div>
              </article>
            );
          })}
          {devices.length === 0 && <div className="empty"><b><Icon name="settings" /></b><h3>还没有设备</h3><p>生成配对码连接第一台手机。</p></div>}
        </div>
      </section>
    </section>
  );
}
