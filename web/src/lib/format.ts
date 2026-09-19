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

export function statusTone(status: string): "ok" | "warn" | "danger" | "muted" {
  switch (status) {
    case "paid":
    case "completed":
    case "ok":
      return "ok";
    case "overdue":
    case "out_of_stock":
    case "critical":
      return "danger";
    case "partially_paid":
    case "warning":
    case "outstanding":
      return "warn";
    default:
      return "muted";
  }
}
