import { APP_VERSION } from "./app_info";

export type TokenPair = {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  device: { id: string; name: string; platform: string };
};
const ACCESS = "iamllm.access",
  REFRESH = "iamllm.refresh";

function browserName() {
  const agent = navigator.userAgent;
  if (agent.includes("Edg/")) return "Edge";
  if (agent.includes("Chrome/")) return "Chrome";
  if (agent.includes("Safari/") && !agent.includes("Chrome/")) return "Safari";
  if (agent.includes("Firefox/")) return "Firefox";
  return "浏览器";
}

export function browserDeviceMetadata() {
  const system = navigator.userAgent.match(
    /(Mac OS X [\d_]+|Android [^;)]+|Windows NT [\d.]+|iPhone OS [\d_]+)/,
  )?.[1];
  const platform = navigator.platform || "Web";
  return {
    device_name: `${browserName()} · ${platform}`,
    platform: "web",
    device_model: platform,
    os_version: system?.replaceAll("_", ".") || "Web platform",
    app_version: `Web Console ${APP_VERSION}`,
    locale: navigator.language || "",
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "",
  };
}

export class API {
  access = localStorage.getItem(ACCESS) || "";
  refreshToken = localStorage.getItem(REFRESH) || "";
  save(pair: TokenPair) {
    this.access = pair.access_token;
    this.refreshToken = pair.refresh_token;
    localStorage.setItem(ACCESS, this.access);
    localStorage.setItem(REFRESH, this.refreshToken);
  }
  clear() {
    this.access = "";
    this.refreshToken = "";
    localStorage.removeItem(ACCESS);
    localStorage.removeItem(REFRESH);
  }
  async login(username: string, password: string) {
    const pair = await this.raw<TokenPair>(
      "/admin/api/v1/auth/login",
      {
        method: "POST",
        body: JSON.stringify({
          username,
          password,
          ...browserDeviceMetadata(),
        }),
      },
      false,
    );
    this.save(pair);
    return pair;
  }
  async refresh() {
    if (!this.refreshToken) throw new Error("登录已失效");
    const pair = await this.raw<TokenPair>(
      "/admin/api/v1/auth/refresh",
      {
        method: "POST",
        body: JSON.stringify({
          refresh_token: this.refreshToken,
          ...browserDeviceMetadata(),
        }),
      },
      false,
    );
    this.save(pair);
  }
  async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    try {
      return await this.raw<T>(path, init, true);
    } catch (error) {
      if (
        error instanceof APIError &&
        error.status === 401 &&
        this.refreshToken
      ) {
        await this.refresh();
        return this.raw<T>(path, init, true);
      }
      throw error;
    }
  }
  async raw<T>(path: string, init: RequestInit, auth: boolean) {
    const headers = new Headers(init.headers);
    if (init.body && !headers.has("Content-Type"))
      headers.set("Content-Type", "application/json");
    if (auth && this.access)
      headers.set("Authorization", `Bearer ${this.access}`);
    const response = await fetch(path, { ...init, headers });
    if (!response.ok) {
      let message = `请求失败 (${response.status})`;
      try {
        const body = await response.json();
        message = body.error?.message || body.detail || message;
      } catch {}
      throw new APIError(response.status, message);
    }
    if (response.status === 204) return undefined as T;
    return response.json() as Promise<T>;
  }
}
export class APIError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export const api = new API();
