"use client";

/** Small presentational pieces shared across screens. */

import type { ReactNode } from "react";

import { statusTone } from "@/lib/format";

export function Stat({
  label,
  value,
  note,
  tone = "muted",
}: {
  label: string;
  value: ReactNode;
  note?: ReactNode;
  tone?: "ok" | "warn" | "danger" | "muted";
}) {
  const cls =
    tone === "danger" ? "stat is-danger" : tone === "warn" ? "stat is-warn" : "stat";
  return (
    <div className={cls}>
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {note ? <div className="note">{note}</div> : null}
    </div>
  );
}

export function Badge({ status, label }: { status: string; label?: string }) {
  const tone = statusTone(status);
  return (
    <span className={`badge ${tone}`}>
      {label ?? status.replace(/_/g, " ")}
    </span>
  );
}

export function Alert({
  kind = "error",
  children,
}: {
  kind?: "error" | "warn" | "ok";
  children: ReactNode;
}) {
  if (!children) return null;
  return (
    <div className={`alert ${kind}`} role={kind === "error" ? "alert" : "status"}>
      {children}
    </div>
  );
}

export function Empty({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty">
      <strong>{title}</strong>
      {children}
    </div>
  );
}

export function PageHead({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {subtitle ? <p>{subtitle}</p> : null}
      </div>
      {actions ? <div className="row">{actions}</div> : null}
    </div>
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="field">
      <span>
        {label} {hint ? <em className="hint">{hint}</em> : null}
      </span>
      {children}
    </label>
  );
}

/** A row of switchable views, e.g. the tabs at the top of a screen. */
export function Tabs<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: ReadonlyArray<{ value: T; label: string }>;
  onChange: (value: T) => void;
}) {
  return (
    <div className="tabs" role="tablist">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="tab"
          aria-selected={value === option.value}
          className={value === option.value ? "tab is-active" : "tab"}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/** A yes/no setting with its explanation beside it. */
export function Toggle({
  label,
  hint,
  checked,
  onChange,
  disabled,
}: {
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <label className="toggle">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span>
        {label}
        {hint ? <em className="hint"> {hint}</em> : null}
      </span>
    </label>
  );
}

/** A small side panel for details and forms that should not lose the list behind them. */
export function Drawer({
  title,
  onClose,
  children,
}: {
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <div className="drawer-backdrop" onClick={onClose} role="presentation">
      <aside
        className="drawer"
        role="dialog"
        aria-modal="true"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="drawer-head">
          <h2>{title}</h2>
          <button type="button" className="secondary" onClick={onClose} aria-label="Close">
            Close
          </button>
        </div>
        <div className="drawer-body">{children}</div>
      </aside>
    </div>
  );
}
