"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { Alert, Empty, PageHead } from "@/components/ui";
import { api, type Notification } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { describeError } from "@/lib/session";

/**
 * In-app notifications: credit reminders, low-stock digests, new enquiries and
 * trial notices (PRD 9, 11.4, 17). A reminder here is internal — nothing has
 * been sent to a customer or supplier.
 */
export default function NotificationsPage() {
  return (
    <AppShell>
      <Notifications />
    </AppShell>
  );
}

function Notifications() {
  const [items, setItems] = useState<Notification[]>([]);
  const [unread, setUnread] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const page = await api.notifications({ limit: 100 });
      setItems(page.items);
      setUnread(page.unread);
      setError(null);
    } catch (cause) {
      setError(describeError(cause, "Could not load notifications"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function markRead(notification: Notification) {
    if (notification.read) return;
    try {
      await api.markNotificationRead(notification.id);
      setItems((all) => all.map((n) => (n.id === notification.id ? { ...n, read: true } : n)));
      setUnread((count) => Math.max(0, count - 1));
    } catch (cause) {
      setError(describeError(cause));
    }
  }

  async function markAllRead() {
    for (const notification of items.filter((n) => !n.read)) {
      await markRead(notification);
    }
  }

  return (
    <>
      <PageHead
        title="Notifications"
        subtitle={loading ? "Loading…" : unread ? `${unread} unread` : "Nothing unread"}
        actions={
          unread > 0 ? (
            <button type="button" className="secondary" onClick={() => void markAllRead()}>
              Mark all as read
            </button>
          ) : null
        }
      />
      <Alert>{error}</Alert>
      <div className="card">
        {items.length === 0 && !loading ? (
          <Empty title="No notifications yet">
            <p>Credit reminders, low-stock alerts and new enquiries appear here.</p>
          </Empty>
        ) : (
          <ul className="notice-list checklist">
            {items.map((notification) => (
              <li key={notification.id} className={notification.read ? undefined : "unread"}>
                <div style={{ width: "100%" }}>
                  <div className="row" style={{ justifyContent: "space-between" }}>
                    <span>{notification.title}</span>
                    <span className="muted" style={{ fontSize: "0.82rem", fontWeight: 400 }}>
                      {dateTime(notification.created_at)}
                    </span>
                  </div>
                  {notification.body && (
                    <p className="muted" style={{ margin: "4px 0", fontWeight: 400 }}>
                      {notification.body}
                    </p>
                  )}
                  <div className="row">
                    {notification.link && (
                      <Link href={notification.link} onClick={() => void markRead(notification)}>
                        Open →
                      </Link>
                    )}
                    {!notification.read && (
                      <button type="button" className="link" onClick={() => void markRead(notification)}>
                        Mark as read
                      </button>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}
