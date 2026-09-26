"use client";

/**
 * Business settings: profile and policies, branches, team, the default
 * pricing rule and the subscription (PRD 4, 5, 6, 8.2, 17).
 */

import { useCallback, useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { Alert, Badge, Empty, Field, PageHead, Toggle } from "@/components/ui";
import {
  api,
  type Branch,
  type Business,
  type Membership,
  type PricingRule,
  type Role,
  type Subscription,
} from "@/lib/api";
import { money, shortDate } from "@/lib/format";
import { describeError, useSession } from "@/lib/session";

export default function SettingsPage() {
  return (
    <AppShell>
      <Settings />
    </AppShell>
  );
}

function Settings() {
  const { can } = useSession();
  return (
    <>
      <PageHead title="Settings" subtitle="Your business, its branches, team and rules" />
      {can("business:view") && <BusinessSection />}
      {can("branch:view") && <BranchesSection />}
      {can("user:view") && <TeamSection />}
      {can("pricing:manage") && <PricingSection />}
      {can("business:view") && <SubscriptionSection />}
    </>
  );
}

// --------------------------------------------------------------------------- //
// Business profile and policies
// --------------------------------------------------------------------------- //

function BusinessSection() {
  const { can, canWrite, refresh } = useSession();
  const [business, setBusiness] = useState<Business | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const manage = canWrite && can("business:manage");

  useEffect(() => {
    api
      .business()
      .then((b) => {
        setBusiness(b);
        setForm({
          name: b.name,
          phone: b.phone ?? "",
          email: b.email ?? "",
          address: b.address ?? "",
          tin: b.tin ?? "",
          business_type: b.business_type ?? "",
          default_tax_rate: b.default_tax_rate ?? "",
          reminder_lead_days: String(b.reminder_lead_days),
        });
      })
      .catch((cause) => setError(describeError(cause, "Could not load the business")));
  }, []);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setSaved(false);
    setError(null);
    try {
      const updated = await api.updateBusiness({
        name: form.name,
        phone: form.phone || null,
        email: form.email || null,
        address: form.address || null,
        tin: form.tin || null,
        business_type: form.business_type || null,
        default_tax_rate: form.default_tax_rate || null,
        reminder_lead_days: Number(form.reminder_lead_days) || 0,
      });
      setBusiness(updated);
      setSaved(true);
      await refresh();
    } catch (cause) {
      setError(describeError(cause, "Could not save"));
    } finally {
      setBusy(false);
    }
  }

  async function setPolicy(key: keyof Business, value: boolean) {
    if (key === "allow_negative_stock" && value) {
      if (!window.confirm("Allow stock to go below zero? Every negative posting is audited. Most shops should leave this off.")) return;
    }
    try {
      setBusiness(await api.updateBusiness({ [key]: value }));
    } catch (cause) {
      setError(describeError(cause, "Could not save"));
    }
  }

  return (
    <section id="business" className="section-anchor">
      <form className="card" onSubmit={save}>
        <div className="card-title">Business details</div>
        <Alert>{error}</Alert>
        {saved && <Alert kind="ok">Saved.</Alert>}
        <div className="grid">
          <Field label="Business name">
            <input value={form.name ?? ""} onChange={(e) => setForm({ ...form, name: e.target.value })} required disabled={!manage} />
          </Field>
          <Field label="Phone">
            <input value={form.phone ?? ""} onChange={(e) => setForm({ ...form, phone: e.target.value })} inputMode="tel" disabled={!manage} />
          </Field>
          <Field label="Email">
            <input type="email" value={form.email ?? ""} onChange={(e) => setForm({ ...form, email: e.target.value })} disabled={!manage} />
          </Field>
          <Field label="Address">
            <input value={form.address ?? ""} onChange={(e) => setForm({ ...form, address: e.target.value })} disabled={!manage} />
          </Field>
          <Field label="TIN" hint="shown on receipts and proformas">
            <input value={form.tin ?? ""} onChange={(e) => setForm({ ...form, tin: e.target.value })} disabled={!manage} />
          </Field>
          <Field label="Type of business" hint="optional">
            <input value={form.business_type ?? ""} onChange={(e) => setForm({ ...form, business_type: e.target.value })} disabled={!manage} />
          </Field>
          <Field label="Default tax rate" hint="0.15 for 15%; blank for none">
            <input value={form.default_tax_rate ?? ""} onChange={(e) => setForm({ ...form, default_tax_rate: e.target.value })} inputMode="decimal" disabled={!manage} />
          </Field>
          <Field label="Remind staff (days before a due date)">
            <input value={form.reminder_lead_days ?? "3"} onChange={(e) => setForm({ ...form, reminder_lead_days: e.target.value })} inputMode="numeric" disabled={!manage} />
          </Field>
        </div>
        {business && (
          <p className="muted" style={{ fontSize: "0.85rem" }}>
            Currency {business.currency} · timezone {business.timezone} · status <Badge status={business.status} />
          </p>
        )}
        {manage && (
          <button type="submit" disabled={busy}>
            {busy ? "Saving…" : "Save details"}
          </button>
        )}
      </form>

      {business && manage && (
        <div className="card">
          <div className="card-title">Policies</div>
          <Toggle
            label="A credit sale must name a customer"
            hint="off allows anonymous credit, which cannot be chased"
            checked={business.require_customer_for_credit}
            onChange={(v) => void setPolicy("require_customer_for_credit", v)}
          />
          <Toggle
            label="Hide out-of-stock products in the online shop"
            hint="off shows them as out of stock"
            checked={business.hide_out_of_stock_online}
            onChange={(v) => void setPolicy("hide_out_of_stock_online", v)}
          />
          {can("settings:manage") && (
            <Toggle
              label="Allow stock to go negative"
              hint="refused by default; every negative posting is audited"
              checked={business.allow_negative_stock}
              onChange={(v) => void setPolicy("allow_negative_stock", v)}
            />
          )}
        </div>
      )}
    </section>
  );
}

// --------------------------------------------------------------------------- //
// Branches
// --------------------------------------------------------------------------- //

function BranchesSection() {
  const { can, canWrite, refresh } = useSession();
  const [branches, setBranches] = useState<Branch[]>([]);
  const [name, setName] = useState("");
  const [address, setAddress] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const manage = canWrite && can("branch:manage");

  const load = useCallback(() => api.branches().then(setBranches).catch((c) => setError(describeError(c))), []);

  useEffect(() => {
    void load();
  }, [load]);

  async function add(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await api.createBranch({ name, address: address || undefined });
      setName("");
      setAddress("");
      await load();
      await refresh();
    } catch (cause) {
      setError(describeError(cause, "Could not add the branch"));
    } finally {
      setBusy(false);
    }
  }

  async function setActive(branch: Branch, active: boolean) {
    try {
      await api.updateBranch(branch.id, { name: branch.name, is_active: active });
      await load();
    } catch (cause) {
      setError(describeError(cause, "Could not update the branch"));
    }
  }

  return (
    <section id="branches" className="section-anchor card">
      <div className="card-title">Branches</div>
      <Alert>{error}</Alert>
      <p className="muted" style={{ marginTop: 0, fontSize: "0.9rem" }}>
        Each branch has its own stock location. Staff can be given one branch, several, or all.
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Address</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {branches.map((branch) => (
              <tr key={branch.id}>
                <td>
                  {branch.name}
                  {branch.is_default && <span className="badge" style={{ marginLeft: 6 }}>main</span>}
                  {branch.is_active === false && <span className="badge warn" style={{ marginLeft: 6 }}>inactive</span>}
                </td>
                <td className="muted">{branch.address ?? "—"}</td>
                <td className="num">
                  {manage && !branch.is_default && (
                    <button type="button" className="link" onClick={() => void setActive(branch, branch.is_active === false)}>
                      {branch.is_active === false ? "Reactivate" : "Deactivate"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {manage && (
        <form onSubmit={add} className="grid" style={{ marginTop: 12, alignItems: "end" }}>
          <Field label="New branch">
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Bole Branch" required />
          </Field>
          <Field label="Address" hint="optional">
            <input value={address} onChange={(e) => setAddress(e.target.value)} />
          </Field>
          <div className="field">
            <button type="submit" disabled={busy || !name.trim()}>
              {busy ? "Adding…" : "Add branch"}
            </button>
          </div>
        </form>
      )}
    </section>
  );
}

// --------------------------------------------------------------------------- //
// Team
// --------------------------------------------------------------------------- //

function TeamSection() {
  const { session, can, canWrite } = useSession();
  const [team, setTeam] = useState<Membership[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [form, setForm] = useState({ email: "", full_name: "", role_name: "salesperson", all_branches: false, branch_ids: [] as string[] });
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ text: string; link?: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const manage = canWrite && can("user:manage");

  function copy(text: string) {
    void navigator.clipboard?.writeText(text);
    setNotice({ text: "Link copied. Send it to them by Telegram, WhatsApp or SMS.", link: text });
  }

  const load = useCallback(async () => {
    try {
      const [members, roleList, branchList] = await Promise.all([api.team(), api.roles(), api.branches()]);
      setTeam(members);
      setRoles(roleList);
      setBranches(branchList);
      if (branchList.length > 0 && form.branch_ids.length === 0) {
        setForm((f) => ({ ...f, branch_ids: [branchList.find((b) => b.is_default)?.id ?? branchList[0].id] }));
      }
      setError(null);
    } catch (cause) {
      setError(describeError(cause, "Could not load the team"));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function invite(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const created = await api.invite({
        email: form.email,
        full_name: form.full_name,
        role_name: form.role_name,
        all_branches: form.all_branches,
        branch_ids: form.all_branches ? [] : form.branch_ids,
      });
      setNotice({
        text: `${form.full_name} has been invited. Give them this link to finish setting up:`,
        link: created.invitation_url ?? undefined,
      });
      setForm((f) => ({ ...f, email: "", full_name: "" }));
      await load();
    } catch (cause) {
      setError(describeError(cause, "Could not invite"));
    } finally {
      setBusy(false);
    }
  }

  async function update(member: Membership, body: Record<string, unknown>) {
    try {
      await api.updateMembership(member.id, body);
      await load();
    } catch (cause) {
      setError(describeError(cause, "Could not update"));
    }
  }

  return (
    <section id="team" className="section-anchor card">
      <div className="card-title">Team</div>
      <Alert>{error}</Alert>
      {notice && (
        <Alert kind="ok">
          {notice.text}
          {notice.link && (
            <>
              {" "}
              <code style={{ wordBreak: "break-all" }}>{notice.link}</code>{" "}
              <button type="button" className="link" onClick={() => copy(notice.link!)}>
                Copy
              </button>
            </>
          )}
        </Alert>
      )}
      <p className="muted" style={{ marginTop: 0, fontSize: "0.9rem" }}>
        Roles are bundles of permissions. A salesperson sees no costs or profit; a stock user cannot sell.
        The server enforces this, not the screen.
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Person</th>
              <th>Role</th>
              <th>Branches</th>
              <th>Status</th>
              {manage && <th />}
            </tr>
          </thead>
          <tbody>
            {team.map((member) => {
              const isMe = member.user.id === session?.user.id;
              return (
                <tr key={member.id}>
                  <td>
                    {member.user.full_name}
                    <div className="muted" style={{ fontSize: "0.82rem" }}>{member.user.email}</div>
                  </td>
                  <td>
                    {manage && !isMe ? (
                      <select value={member.role_name} onChange={(e) => void update(member, { role_name: e.target.value })}>
                        {roles.map((role) => (
                          <option key={role.name} value={role.name}>{role.label}</option>
                        ))}
                      </select>
                    ) : (
                      member.role_name.replace("_", " ")
                    )}
                  </td>
                  <td className="muted">
                    {member.has_all_branches
                      ? "All branches"
                      : member.branch_ids.map((id) => branches.find((b) => b.id === id)?.name ?? "…").join(", ") || "—"}
                  </td>
                  <td className="nowrap">
                    <Badge status={member.status === "active" ? "ok" : member.status === "invited" ? "warning" : "muted"} label={member.status} />
                  </td>
                  {manage && (
                    <td className="num">
                      {member.invitation_url && (
                        <button type="button" className="link" onClick={() => copy(member.invitation_url!)}>
                          Copy invite link
                        </button>
                      )}{" "}
                      {!isMe && member.status !== "disabled" && (
                        <button type="button" className="link" onClick={() => { if (window.confirm(`Disable ${member.user.full_name}'s access?`)) void update(member, { status: "disabled" }); }}>
                          Disable
                        </button>
                      )}
                      {!isMe && member.status === "disabled" && (
                        <button type="button" className="link" onClick={() => void update(member, { status: "active" })}>
                          Reactivate
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {manage && (
        <form onSubmit={invite} style={{ marginTop: 14 }}>
          <div className="card-title">Invite someone</div>
          <div className="grid">
            <Field label="Name">
              <input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} required />
            </Field>
            <Field label="Email">
              <input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required />
            </Field>
            <Field label="Role">
              <select value={form.role_name} onChange={(e) => setForm({ ...form, role_name: e.target.value })}>
                {roles.map((role) => (
                  <option key={role.name} value={role.name}>{role.label} — {role.description}</option>
                ))}
              </select>
            </Field>
          </div>
          <Toggle label="Access to every branch, including ones added later" checked={form.all_branches} onChange={(v) => setForm({ ...form, all_branches: v })} />
          {!form.all_branches && branches.length > 1 && (
            <div className="row" style={{ marginBottom: 12 }}>
              {branches.map((branch) => (
                <label key={branch.id} className="row" style={{ gap: 4 }}>
                  <input
                    type="checkbox"
                    style={{ width: "auto" }}
                    checked={form.branch_ids.includes(branch.id)}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        branch_ids: e.target.checked ? [...form.branch_ids, branch.id] : form.branch_ids.filter((id) => id !== branch.id),
                      })
                    }
                  />
                  {branch.name}
                </label>
              ))}
            </div>
          )}
          <button type="submit" disabled={busy}>
            {busy ? "Inviting…" : "Send invitation"}
          </button>
        </form>
      )}
    </section>
  );
}

// --------------------------------------------------------------------------- //
// Pricing rule
// --------------------------------------------------------------------------- //

function PricingSection() {
  const { session, canWrite } = useSession();
  const currency = session?.currency ?? "ETB";
  const [rules, setRules] = useState<PricingRule[]>([]);
  const [basis, setBasis] = useState("markup");
  const [percent, setPercent] = useState("25");
  const [rounding, setRounding] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .pricingRules()
      .then((all) => {
        setRules(all);
        const business = all.find((r) => r.scope === "business" && r.is_active);
        if (business) {
          setBasis(business.basis);
          setPercent(String(Number(business.rate) * 100));
          setRounding(business.rounding_increment ?? "");
        }
      })
      .catch((cause) => setError(describeError(cause)));
  }, []);

  const rate = Number(percent) / 100;
  const example = basis === "markup" ? 100 * (1 + rate) : rate < 1 ? 100 / (1 - rate) : NaN;

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setSaved(false);
    setError(null);
    try {
      const rule = await api.savePricingRule({
        scope: "business",
        basis,
        rate: String(rate),
        rounding_increment: rounding || null,
      });
      setRules((all) => [...all.filter((r) => r.id !== rule.id), rule]);
      setSaved(true);
    } catch (cause) {
      setError(describeError(cause, "Could not save the rule"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section id="pricing" className="section-anchor">
      <form className="card" onSubmit={save}>
        <div className="card-title">Default pricing rule</div>
        <Alert>{error}</Alert>
        {saved && <Alert kind="ok">Saved. New receipts can update selling prices from this rule.</Alert>}
        <p className="muted" style={{ marginTop: 0, fontSize: "0.9rem" }}>
          The suggested selling price for a product comes from its landed cost and this rule. Markup and
          margin are different calculations: the same 25% gives {money(125, currency)} as markup and{" "}
          {money(133.33, currency)} as margin on a cost of {money(100, currency)}. A category or product
          rule overrides this one.
        </p>
        <div className="grid">
          <Field label="Target profit means">
            <select value={basis} onChange={(e) => setBasis(e.target.value)} disabled={!canWrite}>
              <option value="markup">Markup on cost</option>
              <option value="margin">Gross margin on the selling price</option>
            </select>
          </Field>
          <Field label="Percent">
            <input value={percent} onChange={(e) => setPercent(e.target.value)} inputMode="decimal" disabled={!canWrite} />
          </Field>
          <Field label="Round prices to" hint="optional, e.g. 1 or 5">
            <input value={rounding} onChange={(e) => setRounding(e.target.value)} inputMode="decimal" disabled={!canWrite} />
          </Field>
        </div>
        <p className="muted" style={{ fontSize: "0.9rem" }}>
          Example: a cost of {money(100, currency)} suggests{" "}
          {Number.isFinite(example) ? money(example, currency) : "— (margin must be below 100%)"}.
        </p>
        {canWrite && (
          <button type="submit" disabled={busy}>
            {busy ? "Saving…" : "Save rule"}
          </button>
        )}
        {rules.filter((r) => r.scope !== "business").length > 0 && (
          <p className="muted" style={{ fontSize: "0.85rem" }}>
            {rules.filter((r) => r.scope !== "business").length} category/product override(s) also apply.
          </p>
        )}
      </form>
    </section>
  );
}

// --------------------------------------------------------------------------- //
// Subscription
// --------------------------------------------------------------------------- //

function SubscriptionSection() {
  const [subscription, setSubscription] = useState<Subscription | null>(null);
  useEffect(() => {
    api.subscription().then(setSubscription).catch(() => undefined);
  }, []);
  if (!subscription) return null;
  return (
    <section id="subscription" className="section-anchor card">
      <div className="card-title">Subscription</div>
      {subscription.message ? <Alert kind={subscription.read_only ? "warn" : "ok"}>{subscription.message}</Alert> : null}
      <p className="muted" style={{ margin: 0 }}>
        Status: {subscription.tenant_status}
        {subscription.trial_ends_on ? ` · trial ends ${shortDate(subscription.trial_ends_on)}` : ""}
        {subscription.days_remaining !== null ? ` (${subscription.days_remaining} day(s) left)` : ""}.
        {subscription.read_only ? " Your data is safe and visible; posting is paused." : " When a trial ends, nothing is deleted — the account becomes read-only."}
      </p>
      {!subscription.trial_ends_on && <Empty title="No subscription record" />}
    </section>
  );
}
