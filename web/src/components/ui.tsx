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
