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

function authHeaders(anonymous: boolean): Record<string, string> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (!anonymous) {
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }
  return headers;
}

async function toError(response: Response): Promise<ApiError> {
  const text = await response.text();
  const payload = (text ? safeParse(text) : null) as {
    code?: string;
    message?: string;
    details?: unknown;
  } | null;
  return new ApiError(
    response.status,
    payload?.code ?? "error",
    payload?.message ?? `Request failed (${response.status})`,
    payload?.details,
  );
}

const NETWORK_MESSAGE = "Could not reach the server. Check your connection and try again.";

export async function request<T>(
  path: string,
  { method = "GET", body, anonymous = false, signal }: RequestOptions = {},
): Promise<T> {
  const headers = authHeaders(anonymous);
  if (body !== undefined) headers["Content-Type"] = "application/json";

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
    throw new ApiError(0, "network_error", NETWORK_MESSAGE, cause);
  }

  if (response.status === 204) return undefined as T;
  if (!response.ok) throw await toError(response);

  const text = await response.text();
  return (text ? safeParse(text) : null) as T;
}

/** Multipart upload, for the spreadsheet import. */
export async function upload<T>(path: string, form: FormData): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${resolveBaseUrl()}${path}`, {
      method: "POST",
      headers: authHeaders(false),
      body: form,
    });
  } catch (cause) {
    throw new ApiError(0, "network_error", NETWORK_MESSAGE, cause);
  }
  if (!response.ok) throw await toError(response);
  return (await response.json()) as T;
}

/** Fetch a file the API serves with the session token, and save it. */
export async function download(path: string, fallbackName: string): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${resolveBaseUrl()}${path}`, { headers: authHeaders(false) });
  } catch (cause) {
    throw new ApiError(0, "network_error", NETWORK_MESSAGE, cause);
  }
  if (!response.ok) throw await toError(response);
  const blob = await response.blob();
  const disposition = response.headers.get("content-disposition") ?? "";
  const match = /filename="?([^";]+)"?/.exec(disposition);
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = match?.[1] ?? fallbackName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
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
  code?: string | null;
  phone?: string | null;
  address?: string | null;
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
  timezone: string;
  is_support: boolean;
  subscription: {
    tenant_status: string;
    subscription_status: string | null;
    trial_ends_on: string | null;
    read_only: boolean;
    days_remaining: number | null;
    message: string | null;
  };
};

export type Variant = {
  id: string;
  product_id?: string | null;
  product_name?: string | null;
  display_name?: string | null;
  name: string | null;
  sku: string | null;
  barcode: string | null;
  is_default?: boolean;
  selling_price: string | null;
  tax_rate?: string | null;
  quantity_on_hand: string | null;
  purchase_price?: string | null;
  transport_cost?: string | null;
  other_costs?: string | null;
  landed_cost: string | null;
  average_cost: string | null;
  min_stock: string | null;
  reorder_level: string | null;
};

export type Product = {
  id: string;
  name: string;
  sku: string | null;
  description?: string | null;
  brand?: string | null;
  category_id?: string | null;
  category_name: string | null;
  unit_of_measure: string;
  is_active?: boolean;
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
  timezone?: string;
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
  branches?: Array<{
    branch_id: string;
    branch_name: string;
    sale_count: number;
    total_sales: string;
    gross_profit?: string;
  }>;
  setup?: Array<{ key: string; label: string; done: boolean; action_url: string | null }>;
  setup_complete?: boolean;
};

export type CreditTransaction = {
  id: string;
  reference: string;
  kind: string;
  status: string;
  cancel_reason?: string | null;
  branch_id: string | null;
  customer_id: string | null;
  supplier_id: string | null;
  sale_id: string | null;
  purchase_id: string | null;
  counterparty_name: string | null;
  original_amount: string;
  amount_paid: string;
  balance: string;
  currency: string;
  issued_on: string;
  due_date: string | null;
  agreement_note?: string | null;
  is_overdue: boolean;
  days_overdue: number | null;
};

export type Payment = {
  id: string;
  method: string;
  amount: string;
  paid_at: string;
  reference: string | null;
  note: string | null;
  is_reversed: boolean;
  reversal_reason?: string | null;
};

export type FollowUp = {
  id: string;
  kind: string;
  occurred_at: string;
  note: string | null;
  promised_amount: string | null;
  promised_date: string | null;
  outcome: string | null;
};

export type SaleLine = {
  id: string;
  product_id: string;
  variant_id: string;
  description: string;
  quantity: string;
  unit_price: string;
  discount_amount: string;
  tax_rate: string;
  tax_amount: string;
  line_total: string;
  unit_cost?: string | null;
};

export type Sale = {
  id: string;
  number: string;
  branch_id: string;
  customer_id: string | null;
  salesperson_id: string | null;
  sold_at: string;
  status: string;
  subtotal: string;
  discount_total: string;
  tax_total: string;
  total_amount: string;
  amount_paid: string;
  balance_due: string;
  currency: string;
  note: string | null;
  lines: SaleLine[];
  payments: Payment[];
  cost_total?: string | null;
  gross_profit?: string | null;
};

export type SaleResponse = {
  sale: Sale;
  credit_transaction_id: string | null;
  warnings: string[];
};

export type Receipt = {
  business: { name: string; phone: string | null; address: string | null; tin: string | null };
  branch: { name: string | null };
  sale: {
    number: string;
    sold_at: string;
    status: string;
    currency: string;
    subtotal: string;
    discount_total: string;
    tax_total: string;
    total_amount: string;
    amount_paid: string;
    balance_due: string;
  };
  customer: { name: string; phone: string | null } | null;
  lines: Array<{
    description: string;
    quantity: string;
    unit_price: string;
    discount_amount: string;
    line_total: string;
  }>;
  payments: Array<{ method: string; amount: string }>;
};

export type Customer = {
  id: string;
  name: string;
  phone: string | null;
  telegram_username?: string | null;
  email?: string | null;
  address?: string | null;
  company?: string | null;
  notes?: string | null;
  credit_limit?: string | null;
  credit_limit_behaviour?: string | null;
  is_active?: boolean;
  outstanding_balance: string | null;
};

export type Supplier = {
  id: string;
  name: string;
  phone: string | null;
  email?: string | null;
  contact_person?: string | null;
  address?: string | null;
  tin?: string | null;
  notes?: string | null;
  is_active?: boolean;
  outstanding_balance: string | null;
};

export type CustomerHistory = {
  customer: Customer;
  outstanding_balance: string | null;
  sales: Array<{ id: string; number: string; sold_at: string; total_amount: string; balance_due: string }>;
  credit_transactions: CreditTransaction[];
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

export type StockLocation = {
  id: string;
  name: string;
  branch_id: string;
  kind: string;
  is_default: boolean;
};

export type Movement = {
  id: string;
  product_id: string;
  variant_id: string;
  branch_id: string;
  location_id: string;
  quantity: string;
  balance_after: string;
  reason: string;
  note: string | null;
  occurred_at: string;
  source_type: string | null;
};

export type Transfer = {
  id: string;
  reference: string;
  from_location_id: string;
  to_location_id: string;
  status: string;
  dispatched_at: string | null;
  received_at: string | null;
  note: string | null;
  lines: Array<{
    id: string;
    product_id: string;
    variant_id: string;
    quantity_sent: string;
    quantity_received: string | null;
    note: string | null;
  }>;
};

export type Purchase = {
  id: string;
  number: string;
  supplier_id: string | null;
  branch_id: string;
  status: string;
  received_at: string;
  goods_total: string;
  transport_cost: string;
  other_costs: string;
  total_amount: string;
  amount_paid: string;
  balance_due: string;
  currency: string;
  cost_allocation_method: string;
  supplier_invoice_ref: string | null;
  note: string | null;
  lines: Array<{
    id: string;
    product_id: string;
    variant_id: string;
    description: string;
    quantity: string;
    unit_cost: string;
    allocated_cost: string;
    line_total: string;
  }>;
};

export type PurchaseResponse = {
  purchase: Purchase;
  credit_transaction_id: string | null;
  repriced_variant_ids: string[];
};

export type ImportUpload = {
  job_id: string;
  filename: string;
  total_rows: number;
  detected_headers: string[];
  suggested_mapping: Record<string, string>;
  available_fields: Array<{ field: string; label: string; required: boolean }>;
};

export type ImportPreview = {
  job_id: string;
  total_rows: number;
  valid_rows: number;
  error_rows: number;
  duplicate_rows: number;
  sample: Array<Record<string, string>>;
  issues: Array<{ row_number: number; column: string | null; code: string; message: string; value: string | null }>;
};

export type ImportResult = {
  job_id: string;
  status: string;
  total_rows: number;
  created_products: number;
  skipped_rows: number;
  error_rows: number;
};

export type Store = {
  id: string;
  slug: string;
  display_name: string;
  tagline: string | null;
  about: string | null;
  contact_phone: string | null;
  contact_email: string | null;
  telegram_username: string | null;
  address: string | null;
  is_published: boolean;
  show_prices: boolean;
  public_url: string | null;
};

export type Enquiry = {
  id: string;
  reference: string;
  status: string;
  contact_name: string;
  contact_phone: string;
  contact_email: string | null;
  company: string | null;
  delivery_location: string | null;
  message: string | null;
  wants_proforma: boolean;
  created_at: string;
  items: Array<{ product_id?: string | null; name?: string | null; quantity?: string }>;
};

export type QuotationLine = {
  id: string;
  product_id: string | null;
  variant_id: string | null;
  description: string;
  quantity: string;
  unit_price: string;
  discount_amount: string;
  tax_rate: string;
  tax_amount: string;
  line_total: string;
};

export type Quotation = {
  id: string;
  number: string;
  status: string;
  customer_id: string | null;
  customer_name: string;
  customer_phone: string | null;
  customer_email: string | null;
  customer_company: string | null;
  delivery_location: string | null;
  issued_on: string;
  valid_until: string | null;
  subtotal: string;
  discount_total: string;
  tax_total: string;
  delivery_charge: string;
  total_amount: string;
  currency: string;
  terms: string | null;
  note: string | null;
  lines: QuotationLine[];
  share: { url: string | null; telegram: string | null; mailto: string | null } | null;
  converted_sale_id: string | null;
};

export type Business = {
  id: string;
  name: string;
  phone: string | null;
  email: string | null;
  address: string | null;
  tin: string | null;
  business_type: string | null;
  currency: string;
  locale: string;
  timezone: string;
  allow_negative_stock: boolean;
  require_customer_for_credit: boolean;
  hide_out_of_stock_online: boolean;
  reminder_lead_days: number;
  default_tax_rate: string | null;
  status: string;
};

export type Membership = {
  id: string;
  user: User;
  role_name: string;
  status: string;
  has_all_branches: boolean;
  branch_ids: string[];
  /** Present while an invitation is pending, for the inviter to pass on. */
  invitation_url?: string | null;
};

export type Role = {
  id: string;
  name: string;
  label: string;
  description: string | null;
  permissions: string[];
};

export type PricingRule = {
  id: string;
  scope: string;
  basis: string;
  rate: string;
  category_id: string | null;
  product_id: string | null;
  rounding_increment: string | null;
  is_active: boolean;
};

export type Category = { id: string; name: string; parent_id: string | null; is_active: boolean };

export type Subscription = {
  tenant_status: string;
  subscription_status: string | null;
  trial_ends_on: string | null;
  days_remaining: number | null;
  read_only: boolean;
  message: string | null;
};

export type Notification = {
  id: string;
  kind: string;
  title: string;
  body: string | null;
  link: string | null;
  created_at: string;
  read: boolean;
};

export type NotificationPage = { total: number; unread: number; items: Notification[] };

export type SalesReport = {
  summary: {
    period: { start: string; end: string; timezone?: string };
    currency: string;
    sale_count: number;
    items_sold: string;
    gross_sales: string;
    discounts: string;
    tax: string;
    net_sales: string;
    cost_of_goods?: string;
    gross_profit?: string;
    profit_basis?: string;
  };
  by_day: Array<{ date: string; sale_count: number; total: string }>;
  by_payment_method: Array<{ method: string; count: number; total: string }>;
  basis: string;
};

export type ProductReport = {
  period: { start: string; end: string };
  currency: string;
  products: Array<{
    product_id: string;
    name: string;
    quantity_sold: string;
    revenue: string;
    cost?: string;
    gross_profit?: string;
  }>;
  categories: Array<{ category: string; quantity_sold: string; revenue: string }>;
  note: string;
};

export type BranchReport = {
  period: { start: string; end: string };
  currency: string;
  branches: Array<{
    branch_id: string;
    branch_name: string;
    sale_count: number;
    total_sales: string;
    gross_profit?: string;
  }>;
  note: string;
};

export type InventoryReport = {
  as_of: string;
  currency: string;
  total_quantity: string;
  product_count: number;
  value_at_cost: string | null;
  potential_sales_value: string | null;
  valuation_basis: string;
  low_stock_count: number;
};

export type CreditReport = {
  as_of: string;
  summary: CreditSummary;
  aging: Array<{ bucket: string; amount: string; as_of: string }>;
  basis: string;
};

export type ReportPeriod = "today" | "yesterday" | "7d" | "30d" | "month" | "year";

// --------------------------------------------------------------------------- //
// Endpoint helpers
// --------------------------------------------------------------------------- //

export const api = {
  // Auth
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
  acceptInvitation: (body: { token: string; password?: string; full_name?: string }) =>
    request<{ access_token: string }>("/auth/accept-invitation", {
      method: "POST",
      body,
      anonymous: true,
    }),
  requestPasswordReset: (email: string) =>
    request<{ message: string; detail: string | null }>("/auth/password-reset/request", {
      method: "POST",
      body: { email },
      anonymous: true,
    }),
  confirmPasswordReset: (token: string, password: string) =>
    request<{ message: string }>("/auth/password-reset/confirm", {
      method: "POST",
      body: { token, password },
      anonymous: true,
    }),
  session: () => request<Session>("/auth/session"),

  // Home
  dashboard: () => request<Dashboard>("/dashboard"),

  // Catalogue
  products: (params: { q?: string; limit?: number; offset?: number; include_inactive?: boolean } = {}) =>
    request<Page<Product>>(`/products${toQuery(params)}`),
  product: (id: string) => request<Product>(`/products/${id}`),
  createProduct: (body: Record<string, unknown>) =>
    request<Product>("/products", { method: "POST", body }),
  updateProduct: (id: string, body: Record<string, unknown>) =>
    request<Product>(`/products/${id}`, { method: "PATCH", body }),
  updateVariant: (id: string, body: Record<string, unknown>) =>
    request<Variant>(`/variants/${id}`, { method: "PATCH", body }),
  publishProduct: (id: string, published: boolean) =>
    request<Product>(`/products/${id}/publish?published=${published}`, { method: "POST" }),
  lookupBarcode: (barcode: string) =>
    request<Variant>(`/products/lookup/barcode/${encodeURIComponent(barcode)}`),
  categories: () => request<Category[]>("/categories"),
  pricingRules: () => request<PricingRule[]>("/pricing-rules"),
  savePricingRule: (body: Record<string, unknown>) =>
    request<PricingRule>("/pricing-rules", { method: "PUT", body }),
  suggestPrice: (cost: string, variantId?: string) =>
    request<{ suggested_price: string; explanation: string }>(
      `/pricing/suggest${toQuery({ cost, variant_id: variantId })}`,
    ),

  // Import
  importTemplate: () => download("/imports/template", "estock-product-template.xlsx"),
  importUpload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return upload<ImportUpload>("/imports", form);
  },
  importValidate: (jobId: string, mapping: Record<string, string>) =>
    request<ImportPreview>(`/imports/${jobId}/validate`, { method: "POST", body: { mapping } }),
  importCommit: (jobId: string, skipRowsWithErrors: boolean) =>
    request<ImportResult>(`/imports/${jobId}/commit`, {
      method: "POST",
      body: { skip_rows_with_errors: skipRowsWithErrors },
    }),

  // Stock
  stockLevels: (params: { branch_id?: string; q?: string; limit?: number } = {}) =>
    request<Page<StockLevel>>(`/stock/levels${toQuery(params)}`),
  lowStock: () => request<StockLevel[]>("/stock/low"),
  exportStock: () => download("/stock/levels/export", "estock-stock.csv"),
  movements: (params: { product_id?: string; branch_id?: string; limit?: number } = {}) =>
    request<Page<Movement>>(`/stock/movements${toQuery(params)}`),
  adjustStock: (body: Record<string, unknown>) =>
    request<Movement>("/stock/adjust", { method: "POST", body }),
  locations: () => request<StockLocation[]>("/locations"),
  transfers: () => request<Transfer[]>("/stock/transfers"),
  createTransfer: (body: Record<string, unknown>) =>
    request<Transfer>("/stock/transfers", { method: "POST", body }),
  dispatchTransfer: (id: string) =>
    request<Transfer>(`/stock/transfers/${id}/dispatch`, { method: "POST" }),
  receiveTransfer: (id: string, received: Record<string, string>) =>
    request<Transfer>(`/stock/transfers/${id}/receive`, { method: "POST", body: { received } }),

  // Purchasing
  purchases: (params: { limit?: number } = {}) =>
    request<Page<Purchase>>(`/purchases${toQuery(params)}`),
  receivePurchase: (body: Record<string, unknown>) =>
    request<PurchaseResponse>("/purchases", { method: "POST", body }),

  // Sales
  createSale: (body: Record<string, unknown>) =>
    request<SaleResponse>("/sales", { method: "POST", body }),
  sales: (params: { limit?: number; offset?: number; customer_id?: string; include_voided?: boolean } = {}) =>
    request<Page<Sale>>(`/sales${toQuery(params)}`),
  sale: (id: string) => request<Sale>(`/sales/${id}`),
  receipt: (id: string) => request<Receipt>(`/sales/${id}/receipt`),
  voidSale: (id: string, reason: string) =>
    request<Sale>(`/sales/${id}/void`, { method: "POST", body: { reason } }),

  // Contacts
  customers: (params: { q?: string; limit?: number } = {}) =>
    request<Page<Customer>>(`/customers${toQuery(params)}`),
  createCustomer: (body: Record<string, unknown>) =>
    request<Customer>("/customers", { method: "POST", body }),
  updateCustomer: (id: string, body: Record<string, unknown>) =>
    request<Customer>(`/customers/${id}`, { method: "PATCH", body }),
  customerHistory: (id: string) => request<CustomerHistory>(`/customers/${id}/history`),
  suppliers: (params: { q?: string; limit?: number } = {}) =>
    request<Page<Supplier>>(`/suppliers${toQuery(params)}`),
  createSupplier: (body: Record<string, unknown>) =>
    request<Supplier>("/suppliers", { method: "POST", body }),
  updateSupplier: (id: string, body: Record<string, unknown>) =>
    request<Supplier>(`/suppliers/${id}`, { method: "PATCH", body }),

  // Credit
  creditSummary: (kind: "receivable" | "payable") =>
    request<CreditSummary>(`/credit/summary?kind=${kind}`),
  creditTransactions: (params: { kind?: string; view?: string; limit?: number } = {}) =>
    request<Page<CreditTransaction>>(`/credit/transactions${toQuery(params)}`),
  creditTransaction: (id: string) => request<CreditTransaction>(`/credit/transactions/${id}`),
  creditPayments: (id: string) => request<Payment[]>(`/credit/transactions/${id}/payments`),
  creditActivities: (id: string) => request<FollowUp[]>(`/credit/transactions/${id}/activities`),
  recordCreditPayment: (
    id: string,
    body: { amount: string; method: string; reference?: string; note?: string; paid_on?: string },
  ) =>
    request<CreditTransaction>(`/credit/transactions/${id}/payments`, { method: "POST", body }),
  reversePayment: (paymentId: string, reason: string) =>
    request<Payment>(`/credit/payments/${paymentId}/reverse`, { method: "POST", body: { reason } }),
  changeDueDate: (id: string, body: { due_date?: string | null; due_date_preset?: string; note?: string }) =>
    request<CreditTransaction>(`/credit/transactions/${id}/due-date`, { method: "PATCH", body }),
  cancelCredit: (id: string, reason: string) =>
    request<CreditTransaction>(`/credit/transactions/${id}/cancel`, { method: "POST", body: { reason } }),
  addFollowUp: (id: string, body: Record<string, unknown>) =>
    request<FollowUp>(`/credit/transactions/${id}/activities`, { method: "POST", body }),
  exportCredit: (kind: string, view: string) =>
    download(`/credit/transactions/export?kind=${kind}&view=${view}`, `estock-${kind}s.csv`),

  // Online shop
  store: () => request<Store>("/shop/settings"),
  updateStore: (body: Record<string, unknown>) =>
    request<Store>("/shop/settings", { method: "PATCH", body }),
  enquiries: (params: { status?: string; limit?: number } = {}) =>
    request<Page<Enquiry>>(`/shop/enquiries${toQuery(params)}`),
  updateEnquiry: (id: string, status: string) =>
    request<Enquiry>(`/shop/enquiries/${id}?status=${status}`, { method: "PATCH" }),
  quotations: (params: { status?: string; limit?: number } = {}) =>
    request<Page<Quotation>>(`/shop/quotations${toQuery(params)}`),
  createQuotation: (body: Record<string, unknown>) =>
    request<Quotation>("/shop/quotations", { method: "POST", body }),
  sendQuotation: (id: string) =>
    request<Quotation>(`/shop/quotations/${id}/send`, { method: "POST" }),
  convertQuotation: (id: string, body: Record<string, unknown>) =>
    request<SaleResponse>(`/shop/quotations/${id}/convert`, { method: "POST", body }),

  // Business, branches, team
  business: () => request<Business>("/business"),
  updateBusiness: (body: Record<string, unknown>) =>
    request<Business>("/business", { method: "PATCH", body }),
  branches: () => request<Branch[]>("/branches"),
  createBranch: (body: Record<string, unknown>) =>
    request<Branch>("/branches", { method: "POST", body }),
  updateBranch: (id: string, body: Record<string, unknown>) =>
    request<Branch>(`/branches/${id}`, { method: "PATCH", body }),
  team: () => request<Membership[]>("/team"),
  invite: (body: Record<string, unknown>) =>
    request<Membership>("/team/invite", { method: "POST", body }),
  updateMembership: (id: string, body: Record<string, unknown>) =>
    request<Membership>(`/team/${id}`, { method: "PATCH", body }),
  roles: () => request<Role[]>("/roles"),
  subscription: () => request<Subscription>("/subscription"),

  // Notifications
  notifications: (params: { unread_only?: boolean; limit?: number } = {}) =>
    request<NotificationPage>(`/notifications${toQuery(params)}`),
  markNotificationRead: (id: string) =>
    request<{ ok: boolean }>(`/notifications/${id}/read`, { method: "POST" }),

  // Reports
  salesReport: (period: ReportPeriod, branchId?: string) =>
    request<SalesReport>(`/reports/sales${toQuery({ period, branch_id: branchId })}`),
  exportSalesReport: (period: ReportPeriod) =>
    download(`/reports/sales/export?period=${period}`, "estock-sales.csv"),
  productReport: (period: ReportPeriod) => request<ProductReport>(`/reports/products?period=${period}`),
  branchReport: (period: ReportPeriod) => request<BranchReport>(`/reports/branches?period=${period}`),
  inventoryReport: () => request<InventoryReport>("/reports/inventory"),
  creditReport: (kind: "receivable" | "payable") =>
    request<CreditReport>(`/reports/credit?kind=${kind}`),
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
