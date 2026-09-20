/**
 * Typed client for the Estock API.
 *
 * Business rules live in the backend; this client only carries the session
 * token and turns API errors into something the UI can show (PRD 18).
 */

const CONFIGURED_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

/**
 * Where to call the API from the browser.
 *
 * In development the API runs on the same host as this page. When the page is
 * opened from somewhere other than localhost — a WSL VM address, or a LAN
 * address while testing on a phone — a configured `localhost` would send the
 * browser back to itself and every request would fail.
 *
 * So a *local* configured host is rewritten to whatever host served the page.
 * Anything else is used exactly as configured, which is what a deployment sets.
 */
function resolveBaseUrl(): string {
  if (typeof window === "undefined") return CONFIGURED_BASE_URL;
  try {
    const configured = new URL(CONFIGURED_BASE_URL, window.location.origin);
    const configuredIsLocal =
      configured.hostname === "localhost" || configured.hostname === "127.0.0.1";
    if (configuredIsLocal && window.location.hostname !== configured.hostname) {
      configured.hostname = window.location.hostname;
      return configured.toString().replace(/\/$/, "");
    }
    return CONFIGURED_BASE_URL;
  } catch {
    return CONFIGURED_BASE_URL;
  }
}

const TOKEN_KEY = "estock.token";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }

  /** True when the caller needs to sign in again. */
  get isAuthError(): boolean {
    return this.status === 401;
  }
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null): void {
  if (typeof window === "undefined") return;
  if (token) window.localStorage.setItem(TOKEN_KEY, token);
  else window.localStorage.removeItem(TOKEN_KEY);
}

type RequestOptions = {
  method?: string;
  body?: unknown;
  /** Public storefront endpoints are called without a token. */
  anonymous?: boolean;
  signal?: AbortSignal;
};

export async function request<T>(
  path: string,
  { method = "GET", body, anonymous = false, signal }: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";

  if (!anonymous) {
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetch(`${resolveBaseUrl()}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (cause) {
    // A network failure is not the same as a rejected request; say so plainly.
    throw new ApiError(
      0,
      "network_error",
      "Could not reach the server. Check your connection and try again.",
      cause,
    );
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  const payload = text ? safeParse(text) : null;

  if (!response.ok) {
    const error = (payload ?? {}) as {
      code?: string;
      message?: string;
      details?: unknown;
    };
    throw new ApiError(
      response.status,
      error.code ?? "error",
      error.message ?? `Request failed (${response.status})`,
      error.details,
    );
  }

  return payload as T;
}

function safeParse(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

// --------------------------------------------------------------------------- //
// Types mirroring the API responses we use
// --------------------------------------------------------------------------- //

export type User = {
  id: string;
  email: string;
  full_name: string;
  phone: string | null;
};

export type Branch = {
  id: string;
  name: string;
  is_default: boolean;
  is_active: boolean;
};

export type Session = {
  user: User;
  tenant_id: string;
  tenant_name: string;
  currency: string;
  locale: string;
  role: string;
  permissions: string[];
  all_branches: boolean;
  branches: Branch[];
  subscription: {
    tenant_status: string;
    read_only: boolean;
    days_remaining: number | null;
    message: string | null;
  };
};

export type Variant = {
  id: string;
  name: string | null;
  sku: string | null;
  barcode: string | null;
  selling_price: string | null;
  quantity_on_hand: string | null;
  landed_cost: string | null;
  average_cost: string | null;
  min_stock: string | null;
  reorder_level: string | null;
};

export type Product = {
  id: string;
  name: string;
  sku: string | null;
  category_name: string | null;
  unit_of_measure: string;
  is_published: boolean;
  track_stock: boolean;
  variants: Variant[];
  quantity_on_hand: string | null;
  stock_status: string | null;
};

export type Page<T> = {
  items: T[];
  total: number;
  limit: number;
  offset: number;
};

export type CreditSummary = {
  kind: string;
  currency: string;
  total_outstanding: string;
  due_today: string;
  due_within_7_days: string;
  overdue: string;
  no_due_date: string;
  transaction_count: number;
};

export type Dashboard = {
  date: string;
  currency: string;
  today?: {
    sale_count: number;
    items_sold: string;
    net_sales: string;
    gross_sales: string;
    discounts: string;
    tax: string;
    cost_of_goods?: string;
    gross_profit?: string;
    profit_basis?: string;
  };
  low_stock_count?: number;
  low_stock?: Array<{
    product_id: string;
    name: string;
    quantity: string;
    severity: string;
  }>;
  receivables?: CreditSummary;
  payables?: CreditSummary;
  setup?: Array<{ key: string; label: string; done: boolean; action_url: string | null }>;
  setup_complete?: boolean;
};

export type CreditTransaction = {
  id: string;
  reference: string;
  kind: string;
  status: string;
  counterparty_name: string | null;
  original_amount: string;
  amount_paid: string;
  balance: string;
  currency: string;
  issued_on: string;
  due_date: string | null;
  is_overdue: boolean;
  days_overdue: number | null;
};

export type Sale = {
  id: string;
  number: string;
  sold_at: string;
  status: string;
  total_amount: string;
  amount_paid: string;
  balance_due: string;
  currency: string;
  lines: Array<{
    id: string;
    description: string;
    quantity: string;
    unit_price: string;
    line_total: string;
  }>;
};

export type Customer = {
  id: string;
  name: string;
  phone: string | null;
  outstanding_balance: string | null;
};

export type StockLevel = {
  product_id: string;
  variant_id: string;
  name: string;
  branch_id: string;
  branch_name: string | null;
  quantity: string;
  min_stock: string | null;
  reorder_level: string | null;
  status: string;
};

// --------------------------------------------------------------------------- //
// Endpoint helpers
// --------------------------------------------------------------------------- //

export const api = {
  login: (email: string, password: string) =>
    request<{ access_token: string; user: User; tenant_id: string | null }>(
      "/auth/login",
      { method: "POST", body: { email, password }, anonymous: true },
    ),

  register: (body: {
    business_name: string;
    full_name: string;
    email: string;
    password: string;
    phone?: string;
  }) =>
    request<{ access_token: string; user: User; tenant_id: string }>(
      "/auth/register",
      { method: "POST", body, anonymous: true },
    ),

  session: () => request<Session>("/auth/session"),

  dashboard: () => request<Dashboard>("/dashboard"),

  products: (params: { q?: string; limit?: number; offset?: number } = {}) =>
    request<Page<Product>>(`/products${toQuery(params)}`),

  createProduct: (body: Record<string, unknown>) =>
    request<Product>("/products", { method: "POST", body }),

  lookupBarcode: (barcode: string) =>
    request<Variant>(`/products/lookup/barcode/${encodeURIComponent(barcode)}`),

  stockLevels: (params: { branch_id?: string; q?: string; limit?: number } = {}) =>
    request<Page<StockLevel>>(`/stock/levels${toQuery(params)}`),

  lowStock: () => request<StockLevel[]>("/stock/low"),

  createSale: (body: Record<string, unknown>) =>
    request<{
      sale: Sale;
      credit_transaction_id: string | null;
      warnings: string[];
    }>("/sales", { method: "POST", body }),

  sales: (params: { limit?: number; offset?: number } = {}) =>
    request<Page<Sale>>(`/sales${toQuery(params)}`),

  customers: (params: { q?: string; limit?: number } = {}) =>
    request<Page<Customer>>(`/customers${toQuery(params)}`),

  createCustomer: (body: { name: string; phone?: string }) =>
    request<Customer>("/customers", { method: "POST", body }),

  creditSummary: (kind: "receivable" | "payable") =>
    request<CreditSummary>(`/credit/summary?kind=${kind}`),

  creditTransactions: (params: {
    kind?: string;
    view?: string;
    limit?: number;
  } = {}) => request<Page<CreditTransaction>>(`/credit/transactions${toQuery(params)}`),

  recordCreditPayment: (
    id: string,
    body: { amount: string; method: string; reference?: string },
  ) =>
    request<CreditTransaction>(`/credit/transactions/${id}/payments`, {
      method: "POST",
      body,
    }),
};

function toQuery(params: Record<string, unknown>): string {
  const entries = Object.entries(params).filter(
    ([, value]) => value !== undefined && value !== null && value !== "",
  );
  if (entries.length === 0) return "";
  const search = new URLSearchParams(
    entries.map(([key, value]) => [key, String(value)]),
  );
  return `?${search.toString()}`;
}
