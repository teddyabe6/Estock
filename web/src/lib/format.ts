/** Formatting helpers for ETB amounts, quantities and dates (PRD 16). */

const AMOUNT_FORMATTER = new Intl.NumberFormat("en-ET", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const QUANTITY_FORMATTER = new Intl.NumberFormat("en-ET", {
  maximumFractionDigits: 3,
});

/** Format an amount the API returned as a decimal string. */
export function money(value: string | number | null | undefined, currency = "ETB"): string {
  if (value === null || value === undefined || value === "") return "—";
  const amount = Number(value);
  if (Number.isNaN(amount)) return "—";
  return `${AMOUNT_FORMATTER.format(amount)} ${currency}`;
}

/**
 * Amount without the currency suffix, for table cells where the column header
 * or the page already states the currency.
 */
export function amount(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const parsed = Number(value);
  if (Number.isNaN(parsed)) return "—";
  return AMOUNT_FORMATTER.format(parsed);
}

export function quantity(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const amount = Number(value);
  if (Number.isNaN(amount)) return "—";
  return QUANTITY_FORMATTER.format(amount);
}

export function shortDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

export function dateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * Plain-language due-date text. A balance with no due date is outstanding but
 * never overdue (PRD 11.3), so it must not read as late.
 */
export function dueLabel(dueDate: string | null, isOverdue: boolean, daysOverdue: number | null): string {
  if (!dueDate) return "No due date";
  if (isOverdue) {
    const days = daysOverdue ?? 0;
    return days === 1 ? "1 day overdue" : `${days} days overdue`;
  }
  const due = new Date(dueDate);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const days = Math.round((due.getTime() - today.getTime()) / 86_400_000);
  if (days === 0) return "Due today";
  if (days === 1) return "Due tomorrow";
  return `Due in ${days} days`;
}

/**
 * The worst shelf of a cross-branch row, rather than the business's total.
 *
 * The server judges a product against everything the business holds, which
 * is the right answer to "can we still sell this?" and the wrong one to
 * "does anybody need to go shopping?" — five branches holding 164 bags
 * between them reads as healthy while one of them is down to six.
 *
 * A branch that has never carried the line is left out: its nought means
 * "we do not sell it", not "we have run out", and counting it would turn
 * every satellite branch's catalogue into an emergency.
 */
export function worstBranchStatus(row: {
  quantities: Record<string, string>;
  stocked_at?: string[];
  min_stock: string | null;
  reorder_level: string | null;
}): string {
  const min = row.min_stock === null ? null : Number(row.min_stock);
  const reorder = row.reorder_level === null ? null : Number(row.reorder_level);
  const judge = (held: number) => {
    if (held <= 0) return "out_of_stock";
    if (min !== null && held <= min) return "critical";
    if (reorder !== null && held <= reorder) return "warning";
    return "ok";
  };
  const rank: Record<string, number> = {
    out_of_stock: 0,
    critical: 1,
    warning: 2,
    ok: 3,
  };
  const carried = row.stocked_at ?? [];
  let worst = "ok";
  for (const [branchId, held] of Object.entries(row.quantities)) {
    if (carried.length && !carried.includes(branchId)) continue;
    const here = judge(Number(held));
    if ((rank[here] ?? 3) < (rank[worst] ?? 3)) worst = here;
  }
  return worst;
}

export function statusTone(status: string): "ok" | "warn" | "danger" | "muted" {
  switch (status) {
    case "paid":
    case "completed":
    case "ok":
      return "ok";
    case "received":
      return "ok";
    case "overdue":
    case "out_of_stock":
    case "critical":
    case "rejected":
      return "danger";
    case "partially_paid":
    case "warning":
    case "outstanding":
    // Waiting on somebody: a request on its decision, an approval on the
    // branch that asked taking it up.
    case "requested":
    case "approved":
      return "warn";
    default:
      return "muted";
  }
}
