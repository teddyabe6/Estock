"use client";

/** Small presentational pieces shared across screens. */

import Link from "next/link";
import { useId, useState, type ReactNode } from "react";

import { statusTone } from "@/lib/format";

/**
 * One figure, and where it came from.
 *
 * With `href` the whole card is the way into the list behind the number —
 * a figure somebody is looking at is a question they are about to ask, and
 * the shortest answer is the rows it was added up from.  Without one it is
 * just a figure, and does not pretend otherwise.
 */
export function Stat({
  label,
  value,
  note,
  tone = "muted",
  href,
}: {
  label: string;
  value: ReactNode;
  note?: ReactNode;
  tone?: "ok" | "warn" | "danger" | "muted";
  href?: string;
}) {
  const cls =
    tone === "danger" ? "stat is-danger" : tone === "warn" ? "stat is-warn" : "stat";
  const inside = (
    <>
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {note ? <div className="note">{note}</div> : null}
    </>
  );
  if (!href) return <div className={cls}>{inside}</div>;
  return (
    <Link className={`${cls} is-link`} href={href}>
      {inside}
    </Link>
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

/**
 * The row of narrowing controls above a long list (PRD 9, 15).
 *
 * One place for the search box, the filters and the order, so every list in
 * the app is narrowed the same way and a control that does not apply — a
 * branch filter in a one-branch shop — can simply be left out.
 *
 * On a desk they sit in one row.  On a phone they do not: five controls
 * with their labels is three hundred pixels of chrome above a list, so the
 * screen is mostly the question and barely the answer.  There, `primary`
 * stays — the search box, which is what the hand reaches for — and the rest
 * folds behind one button that says how many of them are set, so a filter
 * left on cannot quietly explain a figure.
 */
export function FilterBar({
  primary,
  active = 0,
  children,
}: {
  primary?: ReactNode;
  /** How many of the folded controls are away from their default. */
  active?: number;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <div className="filter-bar" data-open={open ? "" : undefined}>
      {primary ? <div className="filter-primary">{primary}</div> : null}
      <button
        type="button"
        className={active > 0 ? "filter-toggle secondary is-on" : "filter-toggle secondary"}
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((was) => !was)}
      >
        {active > 0 ? `Filters (${active})` : "Filters"}
      </button>
      <div className="filter-rest" id={id}>
        {children}
      </div>
    </div>
  );
}

/** One labelled control inside a FilterBar. */
export function Picker({
  label,
  value,
  options,
  onChange,
  width,
}: {
  label: string;
  value: string;
  options: ReadonlyArray<{ value: string; label: string }>;
  onChange: (value: string) => void;
  width?: number;
}) {
  return (
    <label className="field filter" style={width ? { flexBasis: width } : undefined}>
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

/**
 * A column heading that reorders the list.
 *
 * The same state the order picker drives, so a mouse and a phone end up in
 * the same place.  On a phone the heading row is hidden — a folded table has
 * no columns to click — which is why the picker exists as well and not
 * instead.
 */
export function SortableHead<T extends string>({
  label,
  by,
  sort,
  direction,
  onSort,
  className,
}: {
  label: string;
  by: T;
  sort: T;
  direction: "asc" | "desc";
  onSort: (by: T) => void;
  className?: string;
}) {
  const active = sort === by;
  return (
    <th className={className} aria-sort={active ? (direction === "asc" ? "ascending" : "descending") : "none"}>
      <button type="button" className="sort" onClick={() => onSort(by)}>
        {label}
        <span aria-hidden className={active ? "arrow on" : "arrow"}>
          {active && direction === "desc" ? "↓" : "↑"}
        </span>
      </button>
    </th>
  );
}

/**
 * A heading row inside a list, for the rows that share a value.
 *
 * Drawn as the list is read rather than by collecting the rows into groups
 * first, so a group that runs past the end of a page simply carries on at
 * the top of the next one instead of appearing twice.
 */
export function GroupRow({ label, span }: { label: string; span: number }) {
  return (
    <tr className="group-row">
      <th colSpan={span} scope="colgroup">
        {label}
      </th>
    </tr>
  );
}

/** How far through a long list the reader is, and the way on. */
export function Pager({
  total,
  limit,
  offset,
  onOffset,
  noun = "rows",
}: {
  total: number;
  limit: number;
  offset: number;
  onOffset: (offset: number) => void;
  noun?: string;
}) {
  if (total <= limit && offset === 0) return null;
  const first = total === 0 ? 0 : offset + 1;
  const last = Math.min(offset + limit, total);
  return (
    <div className="pager">
      <button
        type="button"
        className="secondary"
        disabled={offset === 0}
        onClick={() => onOffset(Math.max(0, offset - limit))}
      >
        Previous
      </button>
      <span className="muted">
        {first}–{last} of {total} {noun}
      </span>
      <button
        type="button"
        className="secondary"
        disabled={last >= total}
        onClick={() => onOffset(offset + limit)}
      >
        Next
      </button>
    </div>
  );
}

/**
 * Results to choose one of, with what choosing does right beside the name.
 *
 * The whole row is the button, so there is nothing to aim at: on a wide
 * screen a name on the left and an action pinned to the right edge are a
 * hand's width apart, and the eye has to travel the gap on every row.
 */
export function PickList({ children }: { children: ReactNode }) {
  return <ul className="picks">{children}</ul>;
}

export function Pick({
  onPick,
  name,
  meta,
  action = "Add",
}: {
  onPick: () => void;
  name: ReactNode;
  meta?: ReactNode;
  action?: string;
}) {
  return (
    <li>
      <button type="button" className="pick" onClick={onPick}>
        <span className="pick-name">{name}</span>
        {meta ? <span className="pick-meta muted">{meta}</span> : null}
        <span className="pick-action">{action}</span>
      </button>
    </li>
  );
}
