/**
 * The platform console: types and calls for the operator, not for a shop.
 *
 * This is a **separate identity** from a shop's session, and the separation is
 * the point (PRD 5.2). The operator signs in at a different endpoint, against
 * a different table, and the token is kept under its own key — so signing in
 * here does not take over a shop session open in the same browser, and signing
 * out of a shop does not sign the operator out.
 *
 * Nothing here can act *as* a shop. Looking inside one goes through support
 * access, which mints a short-lived, read-only, audited token the shop itself
 * can see in its log.
 */

import { request } from "@/lib/api";

const ADMIN_TOKEN_KEY = "estock.admin.token";

export function getAdminToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(ADMIN_TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setAdminToken(token: string | null): void {
  if (typeof window === "undefined") return;
  try {
    if (token) window.localStorage.setItem(ADMIN_TOKEN_KEY, token);
    else window.localStorage.removeItem(ADMIN_TOKEN_KEY);
  } catch {
    // Private mode: the console still works for this tab's lifetime.
  }
}

/** Every call below carries the operator's token, never the shop's. */
function call<T>(path: string, options: Parameters<typeof request>[1] = {}): Promise<T> {
  return request<T>(path, { ...options, token: getAdminToken() });
}

// --------------------------------------------------------------------------- //
// Types
// --------------------------------------------------------------------------- //

export type AdminUser = { id: string; email: string; full_name: string };

export type AdminLogin = {
  access_token: string;
  token_type: string;
  expires_in_minutes: number;
  admin: AdminUser;
};

export type ShopRow = {
  id: string;
  name: string;
  slug: string;
  status: string;
  created_at: string;
  trial_ends_on: string | null;
  subscription_status: string | null;
  user_count: number;
  product_count: number;
  sale_count: number;
};

export type Plan = {
  id: string;
  code: string;
  name: string;
  monthly_price: string;
  currency: string;
  max_branches: number | null;
  max_users: number | null;
  max_products: number | null;
  is_active: boolean;
};

export type PlanLimitRow = {
  name: string;
  used: number;
  allowed: number | null;
  remaining: number | null;
};

export type SubscriptionPaymentRow = {
  id: string;
  invoice_id: string;
  tenant_id: string;
  method: string;
  amount: string;
  currency: string;
  paid_on: string;
  reference: string | null;
  note: string | null;
  is_reversed: boolean;
  reversed_at: string | null;
  reversal_reason: string | null;
};

export type Invoice = {
  id: string;
  tenant_id: string;
  tenant_name?: string | null;
  number: string;
  status: string;
  plan_code: string | null;
  plan_name: string | null;
  period_start: string;
  period_end: string;
  amount: string;
  amount_paid: string;
  balance_due: string;
  currency: string;
  due_on: string | null;
  issued_at: string | null;
  voided_at: string | null;
  void_reason: string | null;
  note: string | null;
  payments?: SubscriptionPaymentRow[];
};

export type BillingSummary = {
  billed: string;
  collected: string;
  outstanding: string;
  overdue: string;
  overdue_count: number;
  paying_shops: number;
  shops_in_arrears: number;
  currency: string;
};

export type TenantBilling = {
  tenant_id: string;
  tenant_name: string;
  tenant_status: string;
  currency: string;
  /** The plan it is on now, or null if it is on none. */
  plan: Plan | null;
  subscription_status: string | null;
  trial_ends_on: string | null;
  usage: { users: number; products: number; sales: number };
  paid_until: string | null;
  balance_due: string;
  unpaid_count: number;
  total: number;
  limit: number;
  offset: number;
  invoices: Invoice[];
};

export type TenantSwitch = {
  key: string;
  description: string;
  enabled: boolean;
  /** Whether this shop has a setting of its own, or follows the platform. */
  set_for_shop: boolean;
  platform_default: boolean;
};

export type PlatformSwitch = {
  key: string;
  description: string;
  default: boolean;
  enabled: boolean;
  set_explicitly: boolean;
  per_tenant: boolean;
};

export type AuditRow = {
  id: string;
  created_at: string;
  tenant_id: string | null;
  action: string;
  summary: string | null;
  actor_label: string | null;
};

export type BillingRunResult = {
  invoices_raised: number;
  invoice_ids: string[];
  skipped_no_plan: number;
  skipped_already_billed: number;
};

/** What the shop statuses mean, in the operator's words. */
export const SHOP_STATUS_NOTE: Record<string, string> = {
  trial: "On a free trial. Can trade as normal.",
  active: "Paid up and trading.",
  restricted: "Read-only: the trial or the paid period ran out. Nothing was deleted.",
  suspended: "Shut out by you. Paying an invoice will not lift this.",
};

function qs(params: Record<string, string | number | undefined>): string {
  const pairs = Object.entries(params)
    .filter(([, value]) => value !== undefined && value !== "")
    .map(([key, value]) => `${key}=${encodeURIComponent(String(value))}`);
  return pairs.length ? `?${pairs.join("&")}` : "";
}

// --------------------------------------------------------------------------- //
// Calls
// --------------------------------------------------------------------------- //

export const adminApi = {
  /** Signing in does not use the shop's token, and does not set it. */
  signIn: (email: string, password: string) =>
    request<AdminLogin>("/platform/login", {
      method: "POST",
      anonymous: true,
      body: { email, password },
    }),

  shops: (params: { q?: string; status?: string; limit?: number; offset?: number } = {}) =>
    call<{ total: number; limit: number; offset: number; items: ShopRow[] }>(
      `/platform/tenants${qs(params)}`,
    ),

  setShopStatus: (tenantId: string, status: string, reason?: string) =>
    call<{ id: string; status: string }>(`/platform/tenants/${tenantId}/status`, {
      method: "PATCH",
      body: { status, reason },
    }),

  setTrial: (tenantId: string, trialDays: number, reason?: string) =>
    call<{ tenant_id: string; trial_ends_on: string; status: string }>(
      `/platform/tenants/${tenantId}/trial`,
      { method: "PATCH", body: { trial_days: trialDays, reason } },
    ),

  setPlan: (tenantId: string, planId: string, reason?: string) =>
    call<{ tenant_id: string; plan: Plan; limits: PlanLimitRow[] }>(
      `/platform/tenants/${tenantId}/plan`,
      { method: "PATCH", body: { plan_id: planId, reason } },
    ),

  plans: () => call<Plan[]>("/platform/plans"),

  createPlan: (body: Record<string, unknown>) =>
    call<{ id: string; code: string }>("/platform/plans", { method: "POST", body }),

  // -- billing ------------------------------------------------------------ //

  billingSummary: () => call<BillingSummary>("/platform/billing/summary"),

  invoices: (params: { tenant_id?: string; status?: string; limit?: number; offset?: number } = {}) =>
    call<{ total: number; limit: number; offset: number; items: Invoice[] }>(
      `/platform/invoices${qs(params)}`,
    ),

  invoice: (id: string) => call<Invoice>(`/platform/invoices/${id}`),

  raiseInvoice: (body: Record<string, unknown>) =>
    call<Invoice>("/platform/invoices", { method: "POST", body }),

  issueInvoice: (id: string) =>
    call<Invoice>(`/platform/invoices/${id}/issue`, { method: "POST" }),

  voidInvoice: (id: string, reason: string) =>
    call<Invoice>(`/platform/invoices/${id}/void`, { method: "POST", body: { reason } }),

  recordPayment: (invoiceId: string, body: Record<string, unknown>) =>
    call<{
      payment: SubscriptionPaymentRow;
      invoice: Invoice;
      renewed: boolean;
      tenant_status: string | null;
      warnings: string[];
    }>(`/platform/invoices/${invoiceId}/payments`, { method: "POST", body }),

  reversePayment: (paymentId: string, reason: string) =>
    call<{ payment: SubscriptionPaymentRow; invoice: Invoice | null }>(
      `/platform/payments/${paymentId}/reverse`,
      { method: "POST", body: { reason } },
    ),

  tenantBilling: (tenantId: string, params: { limit?: number; offset?: number } = {}) =>
    call<TenantBilling>(`/platform/tenants/${tenantId}/billing${qs(params)}`),

  runBilling: () => call<BillingRunResult>("/platform/billing/run", { method: "POST" }),

  // -- switches, support and the trail ------------------------------------ //

  settings: () => call<{ settings: PlatformSwitch[] }>("/platform/settings"),

  tenantSettings: (tenantId: string) =>
    call<{ settings: TenantSwitch[] }>(`/platform/tenants/${tenantId}/settings`),

  setSwitch: (key: string, enabled: boolean, opts: { tenant_id?: string; reason?: string } = {}) =>
    call<{ key: string; enabled: boolean; tenant_id: string | null }>("/platform/settings", {
      method: "PUT",
      body: { key, enabled, ...opts },
    }),

  supportAccess: (tenantId: string, reason: string, minutes?: number) =>
    call<{
      access_token: string;
      tenant_id: string;
      expires_in_minutes: number;
      notice: string;
    }>("/platform/support-access", {
      method: "POST",
      body: { tenant_id: tenantId, reason, minutes },
    }),

  auditEvents: (params: { tenant_id?: string; limit?: number } = {}) =>
    call<AuditRow[]>(`/platform/audit-events${qs(params)}`),

  runDailyJobs: () => call<Record<string, unknown>>("/platform/jobs/run-daily", { method: "POST" }),
};

/** The invoice statuses, in the order an operator cares about them. */
export const INVOICE_STATUSES = [
  "overdue",
  "open",
  "part_paid",
  "paid",
  "draft",
  "void",
] as const;

export const SHOP_STATUSES = ["trial", "active", "restricted", "suspended"] as const;

/** Ethiopian payment rails first, since that is what arrives. */
export const PAYMENT_METHODS = [
  "telebirr",
  "cbe_birr",
  "bank_transfer",
  "cash",
  "mobile_money",
  "cheque",
  "card",
  "other",
] as const;

export function methodLabel(method: string): string {
  switch (method) {
    case "telebirr":
      return "telebirr";
    case "cbe_birr":
      return "CBE Birr";
    case "bank_transfer":
      return "Bank transfer";
    case "mobile_money":
      return "Mobile money";
    default:
      return method.charAt(0).toUpperCase() + method.slice(1).replace(/_/g, " ");
  }
}
