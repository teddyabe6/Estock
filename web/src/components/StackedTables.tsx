"use client";

/**
 * Tables that fold into cards when they will not fit (PRD 7, 16).
 *
 * Nearly every list in this app is a table, which is right on a desk and
 * wrong in a hand: six columns in 390 pixels means the figure a shopkeeper
 * opened the page for sits off the edge of a sideways scroll nobody
 * discovers. Where a table overflows, each row becomes a card and every cell
 * carries the name of the column it came from.
 *
 * Two decisions worth stating.
 *
 * It is done here, once, instead of writing the column name into each of the
 * app's several hundred cells: the name is already in the table's heading, so
 * it can be taken from there, and a table written tomorrow is handled without
 * anybody remembering to ask for it.
 *
 * And the test is whether a table actually overflows, not how narrow the
 * screen is. A three-column table reads better as a table even on a phone,
 * and one long product name can push a narrow table over the edge on a
 * tablet. Measuring answers both; a breakpoint guesses at both.
 *
 * A table that must keep its grid — a printed receipt — says so by sitting
 * inside `data-keep-grid`.
 */

import { useEffect } from "react";

/** Column names, one per column, with a span counted once per column. */
function headings(table: HTMLTableElement): string[] {
  const head = table.tHead?.rows[table.tHead.rows.length - 1];
  if (!head) return [];
  const names: string[] = [];
  for (const cell of Array.from(head.cells)) {
    const text = (cell.textContent ?? "").trim();
    for (let n = 0; n < Math.max(1, cell.colSpan); n += 1) names.push(text);
  }
  return names;
}

/**
 * Give every body cell the name of its column, and spell out the roles that
 * `display: block` would otherwise take away from the table.
 *
 * A cell spanning several columns belongs to no single one of them — an
 * "add the first one" line across an empty table — so it is left unlabelled
 * and stands on its own in the card.
 */
function prepare(table: HTMLTableElement) {
  table.setAttribute("role", "table");
  for (const group of Array.from(table.querySelectorAll("thead, tbody, tfoot"))) {
    group.setAttribute("role", "rowgroup");
  }
  for (const row of Array.from(table.rows)) row.setAttribute("role", "row");
  for (const cell of Array.from(table.querySelectorAll("th"))) {
    cell.setAttribute("role", cell.closest("thead") ? "columnheader" : "rowheader");
  }
  for (const cell of Array.from(table.querySelectorAll("td"))) {
    cell.setAttribute("role", "cell");
  }

  const names = headings(table);
  if (names.length === 0) return;
  for (const body of Array.from(table.tBodies)) {
    for (const row of Array.from(body.rows)) {
      let column = 0;
      for (const cell of Array.from(row.cells)) {
        const name = cell.colSpan > 1 ? "" : (names[column] ?? "");
        if (name) cell.setAttribute("data-label", name);
        else cell.removeAttribute("data-label");
        column += Math.max(1, cell.colSpan);
      }
    }
  }
}

/** Whether the table fits the width its parent can give it. */
function fits(table: HTMLTableElement): boolean {
  const parent = table.parentElement;
  if (!parent) return true;
  const style = getComputedStyle(parent);
  const available =
    parent.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
  // A table nobody can see has no width to judge; leave it as it is until it
  // is on screen and a later pass can measure it properly.
  if (available <= 0 || table.offsetWidth === 0) return true;
  return table.offsetWidth <= available + 1;
}

function arrange() {
  for (const table of Array.from(document.querySelectorAll("table"))) {
    if (table.closest("[data-keep-grid]")) continue;
    prepare(table);
    // Measured as a table, whatever it was a moment ago: reading the width
    // straight after clearing the flag is what makes the answer the real one.
    table.removeAttribute("data-stacked");
    if (!fits(table)) table.setAttribute("data-stacked", "");
  }
}

export function StackedTables() {
  useEffect(() => {
    let frame = 0;
    const schedule = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(arrange);
    };

    schedule();
    // Rows arrive from the API, forms open and close, and sections are shown
    // by a class. None of that is something this can be told about, so it
    // watches instead. It only ever writes data- and role attributes, and
    // only class, style and hidden are watched, so it cannot set itself off.
    const watcher = new MutationObserver(schedule);
    watcher.observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: ["class", "style", "hidden"],
    });
    window.addEventListener("resize", schedule);

    return () => {
      cancelAnimationFrame(frame);
      watcher.disconnect();
      window.removeEventListener("resize", schedule);
    };
  }, []);

  return null;
}
