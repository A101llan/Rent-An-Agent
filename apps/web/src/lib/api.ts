const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface ApiError {
  error: {
    code: string;
    message: string;
    request_id?: string;
  };
}

export interface User {
  id: string;
  email: string;
  role: "customer" | "developer" | "admin";
  is_active: boolean;
  is_verified: boolean;
  display_name: string | null;
  created_at: string;
}

export interface AuthResponse {
  user: User;
  tokens: { access_token: string; token_type: string; expires_in: number };
}

export interface AgentListItem {
  id: string;
  slug: string;
  name: string;
  description: string;
  category: string;
  is_featured: boolean;
  is_verified: boolean;
  avg_rating: number;
  review_count: number;
  developer_name: string | null;
  starting_price_minor: number | null;
  pricing_model: string | null;
  capabilities: string[];
}

export interface PricingPlan {
  id: string;
  name: string;
  pricing_model: string;
  price_minor: number;
  currency: string;
  duration_minutes: number | null;
}

export interface AgentManifest {
  runtime?: { type?: string; [key: string]: unknown } | null;
  [key: string]: unknown;
}

export interface AgentDetail {
  id: string;
  slug: string;
  name: string;
  description: string;
  category: string;
  is_featured: boolean;
  is_verified: boolean;
  avg_rating: number;
  review_count: number;
  developer_name: string | null;
  developer_company: string | null;
  version: string | null;
  capabilities: string[];
  permissions: string[];
  pricing_plans: PricingPlan[];
  manifest?: AgentManifest | null;
  published_at: string | null;
}

export interface Review {
  id: string;
  rating: number;
  title: string | null;
  body: string | null;
  customer_name: string | null;
  created_at: string;
}

export interface Rental {
  id: string;
  agent_id: string;
  agent_name: string;
  agent_slug: string;
  status: string;
  started_at: string | null;
  expires_at: string | null;
  total_cost_minor: number;
  currency: string;
  created_at: string;
}

export interface SessionIntegrationInfo {
  api_base_url: string;
  session_id: string;
  auth: { type: string; header: string; description: string };
  endpoints: Record<string, { method: string; path: string }>;
  examples: { execute_curl: string; execute_python: string };
}

export interface Session {
  id: string;
  rental_id: string;
  status: string;
  started_at: string | null;
  expires_at: string;
  last_activity_at: string | null;
  agent_name: string;
  agent_slug: string;
  runtime_status: string | null;
  runtime_provider?: string | null;
  session_token?: string;
  integration?: SessionIntegrationInfo;
  embed?: EmbedSnippet;
}

export interface LocalRuntimeInfo {
  session_id: string;
  claim_endpoint: string;
  usage_endpoint: string;
  auth_header?: string;
}

export interface HireResponse {
  rental: Rental;
  session: Session;
  session_token: string;
  runtime_provider?: string | null;
  integration: SessionIntegrationInfo;
  embed: EmbedSnippet;
  local?: LocalRuntimeInfo | null;
}

export interface EmbedSnippet {
  api_key: string;
  embed_html: string;
  embed_script: string;
  demo_page_url: string;
}

export interface ExecuteResult {
  execution_id: string;
  status: string;
  output: unknown;
  usage: Record<string, number> | null;
  approval_id?: string | null;
  approval?: {
    title: string;
    description: string;
    details?: Record<string, unknown>;
  } | null;
}

export interface ApprovalRequest {
  id: string;
  session_id: string;
  execution_id: string;
  action_type: string;
  title: string;
  description: string;
  details: Record<string, unknown> | null;
  status: string;
  created_at: string;
}

export interface ExecutionHistoryItem {
  id: string;
  status: string;
  input_preview: string | null;
  output_preview: string | null;
  duration_ms: number | null;
  created_at: string;
  completed_at: string | null;
}

class ApiClient {
  private baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl;
  }

  private getToken(): string | null {
    if (typeof window === "undefined") return null;
    return localStorage.getItem("access_token");
  }

  setToken(token: string) {
    localStorage.setItem("access_token", token);
  }

  clearToken() {
    localStorage.removeItem("access_token");
  }

  async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const token = this.getToken();
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...(options.headers as Record<string, string>),
    };
    if (token) headers.Authorization = `Bearer ${token}`;

    const response = await fetch(`${this.baseUrl}${path}`, {
      ...options,
      headers,
      credentials: "include",
    });

    if (!response.ok) {
      const error: ApiError = await response.json().catch(() => ({
        error: { code: "UNKNOWN", message: response.statusText },
      }));
      throw error;
    }
    return response.json();
  }

  register(data: { email: string; password: string; role: string; display_name?: string }) {
    return this.request<AuthResponse>("/api/v1/auth/register", { method: "POST", body: JSON.stringify(data) });
  }

  login(data: { email: string; password: string }) {
    return this.request<AuthResponse>("/api/v1/auth/login", { method: "POST", body: JSON.stringify(data) });
  }

  logout() {
    return this.request<{ message: string }>("/api/v1/auth/logout", { method: "POST" });
  }

  me() {
    return this.request<User>("/api/v1/auth/me");
  }

  listAgents(params?: Record<string, string>) {
    const qs = params ? "?" + new URLSearchParams(params).toString() : "";
    return this.request<{ items: AgentListItem[]; total: number; page: number; pages: number }>(
      `/api/v1/marketplace/agents${qs}`,
    );
  }

  getAgent(slug: string) {
    return this.request<{ agent: AgentDetail; reviews: Review[] }>(`/api/v1/agents/${slug}`);
  }

  createRental(data: { agent_slug: string; pricing_plan_id: string; duration_minutes: number }, idempotencyKey?: string) {
    return this.request<Rental>("/api/v1/rentals", {
      method: "POST",
      body: JSON.stringify(data),
      headers: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {},
    });
  }

  hireAgent(
    data: { agent_slug: string; pricing_plan_id: string; duration_minutes: number },
    idempotencyKey?: string,
  ) {
    return this.request<HireResponse>("/api/v1/rentals/hire", {
      method: "POST",
      body: JSON.stringify(data),
      headers: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {},
    });
  }

  createSession(rentalId: string, idempotencyKey?: string) {
    return this.request<Session>("/api/v1/sessions", {
      method: "POST",
      body: JSON.stringify({ rental_id: rentalId }),
      headers: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {},
    });
  }

  getSession(sessionId: string) {
    return this.request<Session>(`/api/v1/sessions/${sessionId}`);
  }

  execute(sessionId: string, input: string | Record<string, unknown>, context?: Record<string, unknown>) {
    return this.request<ExecuteResult>(`/api/v1/sessions/${sessionId}/execute`, {
      method: "POST",
      body: JSON.stringify({ input, context: context ?? {} }),
    });
  }

  getSessionIntegration(sessionId: string) {
    return this.request<SessionIntegrationInfo>(`/api/v1/sessions/${sessionId}/integration`);
  }

  extendSession(sessionId: string, durationMinutes: number) {
    return this.request<Session>(`/api/v1/sessions/${sessionId}/extend`, {
      method: "POST",
      body: JSON.stringify({ duration_minutes: durationMinutes }),
    });
  }

  listRentals() {
    return this.request<Rental[]>("/api/v1/rentals");
  }

  getExecutions(sessionId: string) {
    return this.request<ExecutionHistoryItem[]>(`/api/v1/sessions/${sessionId}/executions`);
  }

  listApprovals(sessionId: string) {
    return this.request<ApprovalRequest[]>(`/api/v1/sessions/${sessionId}/approvals`);
  }

  resolveApproval(sessionId: string, approvalId: string, approved: boolean, scope?: "once" | "session") {
    return this.request<ApprovalRequest>(`/api/v1/sessions/${sessionId}/approvals/${approvalId}/resolve`, {
      method: "POST",
      body: JSON.stringify({ approved, scope: approved ? scope || "once" : undefined }),
    });
  }

  getDeveloperStats() {
    return this.request<{ published_agents: number; active_rentals: number; total_executions: number; total_revenue_minor: number; avg_rating: number }>(
      "/api/v1/developer/stats",
    );
  }

  listDeveloperAgents() {
    return this.request<Array<{ id: string; slug: string; name: string; status: string; avg_rating: number; review_count: number }>>(
      "/api/v1/developer/agents",
    );
  }

  createAgent(data: { name: string; slug: string; description: string; category: string }) {
    return this.request<{ id: string; slug: string; name: string; status: string }>("/api/v1/developer/agents", {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  createVersion(
    agentId: string,
    data: {
      version: string;
      manifest: Record<string, unknown>;
      image_name: string;
      image_digest: string;
      capabilities: string[];
      pricing_model: string;
      price_minor: number;
    },
  ) {
    return this.request<{ version_id: string; version: string; status: string }>(
      `/api/v1/developer/agents/${agentId}/versions`,
      {
        method: "POST",
        body: JSON.stringify(data),
      },
    );
  }

  publishAgent(agentId: string) {
    return this.request<{ status: string }>(`/api/v1/developer/agents/${agentId}/publish`, {
      method: "POST",
    });
  }

  submitReview(agentId: string, data: { rating: number; title?: string; body?: string }) {
    return this.request<Review>(`/api/v1/agents/${agentId}/reviews`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  }
}

export const api = new ApiClient(API_URL);

export function formatPrice(minor: number, currency = "USD"): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(minor / 100);
}

export function formatPricingModel(model: string, minor: number): string {
  const price = formatPrice(minor);
  const map: Record<string, string> = {
    per_hour: `${price}/hr`,
    per_minute: `${price}/min`,
    per_task: `${price}/task`,
    per_request: `${price}/request`,
    subscription: `${price}/mo`,
  };
  return map[model] || price;
}
