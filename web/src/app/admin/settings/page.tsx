"use client";

/**
 * The switches that control the platform itself.
 *
 * Only switches something enforces are here. A toggle nothing reads is worse
 * than no toggle, because it looks like control and is not — which is exactly
 * what the feature-flag table was before these were wired up.
 */

import { useCallback, useEffect, useState } from "react";

import { AdminShell } from "@/components/AdminShell";
import { Alert, PageHead, Toggle } from "@/components/ui";
import { adminApi, type PlatformSwitch } from "@/lib/admin";
import { useAdmin, useAdminCall } from "@/lib/adminSession";

export default function AdminSettingsPage() {
  const { admin, signOut } = useAdmin();
  const describe = useAdminCall(signOut);

  const [switches, setSwitches] = useState<PlatformSwitch[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [jobs, setJobs] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setSwitches((await adminApi.settings()).settings);
      setError(null);
    } catch (cause) {
      setError(describe(cause, "Could not load the platform settings"));
    }
  }, [describe]);

  useEffect(() => {
    if (admin) void load();
  }, [admin, load]);

  async function turn(item: PlatformSwitch, enabled: boolean) {
    if (
      item.key === "registration_open" &&
      !enabled &&
      !window.confirm(
        "Closing registration means nobody new can sign themselves up. Shops that already exist are unaffected. Continue?",
      )
    ) {
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await adminApi.setSwitch(item.key, enabled);
      setNotice(`${item.key.replace(/_/g, " ")} is now ${enabled ? "on" : "off"}.`);
      await load();
    } catch (cause) {
      setError(describe(cause, "Could not change that setting"));
    } finally {
      setBusy(false);
    }
  }

  async function runJobs() {
    setBusy(true);
    setJobs(null);
    try {
      const result = await adminApi.runDailyJobs();
      setJobs(
        [
          `${result.invoices_raised ?? 0} invoice(s) raised`,
          `${result.subscriptions_lapsed ?? 0} subscription(s) lapsed`,
          `${result.trials_expired ?? 0} trial(s) expired`,
          `${result.trials_warned ?? 0} trial warning(s) sent`,
          `${result.low_stock_alerts ?? 0} low-stock alert(s)`,
        ].join(" · "),
      );
    } catch (cause) {
      setError(describe(cause, "Could not run the daily jobs"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AdminShell>
      <PageHead
        title="Platform settings"
        subtitle="Switches that apply across every shop"
      />

      <Alert>{error}</Alert>
      {notice && <Alert kind="ok">{notice}</Alert>}

      <section className="card">
        <div className="card-title">Switches</div>
        {switches.length === 0 ? (
          <p className="muted">Loading…</p>
        ) : (
          switches.map((item) => (
            <div key={item.key} style={{ marginBottom: 4 }}>
              <Toggle
                label={item.key.replace(/_/g, " ")}
                hint={item.description}
                checked={item.enabled}
                onChange={(value) => void turn(item, value)}
              />
              {!item.set_explicitly && (
                <p className="muted" style={{ margin: "0 0 12px", fontSize: "0.85rem" }}>
                  Never set, so it is the default ({item.default ? "on" : "off"}).
                </p>
              )}
            </div>
          ))
        )}
      </section>

      <section className="card">
        <div className="card-title">Scheduled work</div>
        <p className="muted" style={{ marginTop: 0 }}>
          The background worker runs this every day: it raises the next invoices,
          lapses subscriptions whose paid period has run out, expires trials, warns
          owners whose trial is ending and sends low-stock alerts. Running it here does
          the same thing now. It is safe to run twice.
        </p>
        <div className="row">
          <button type="button" className="secondary" onClick={() => void runJobs()} disabled={busy}>
            {busy ? "Running…" : "Run the daily jobs now"}
          </button>
          {jobs && <span className="muted">{jobs}</span>}
        </div>
      </section>
    </AdminShell>
  );
}
