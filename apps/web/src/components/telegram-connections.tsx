"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { MessageCircle, UsersRound } from "lucide-react";
import type {
  TelegramState,
  TelegramPurpose,
  IssuedInvitation,
  ConnectionRead,
} from "@hub/contracts";
import { api, errorMessage, json } from "@/lib/api";
import { ErrorNotice } from "./ui";
import { Modal } from "./modal";

const labels: Record<string, string> = {
  DISABLED: "Telegram disabled",
  NOT_CONFIGURED: "Bot not configured",
  WORKER_UNAVAILABLE: "Worker unavailable",
  RUNNING: "Worker running",
  STOPPED: "Worker stopped",
  RETRYING: "Worker retrying",
  FAILED: "Worker unavailable",
  NOT_CONNECTED: "Not connected",
  LINK_ISSUED: "Waiting for technician",
  AWAITING_APPROVAL: "Waiting for manager approval",
  CONNECTED: "Connected",
  EXPIRED: "Invitation expired",
  ERROR: "Setup needs attention",
  REVOKED: "Invitation revoked",
  REJECTED: "Candidate rejected",
};
const setup: Record<string, string> = {
  INITIATOR_NOT_ADMIN:
    "Ask a non-anonymous group owner or administrator to open a new group invitation.",
  BOT_ADMIN_REQUIRED:
    "Make the bot a group administrator so Telegram can reliably verify membership. No blanket moderation permissions are needed. Then retry checks.",
  TECHNICIAN_NOT_MEMBER:
    "Add the approved technician account to this group, then retry checks.",
  ACCESS_DENIED:
    "Restore the bot's group access and administrator role, then retry checks.",
  NETWORK_UNCERTAIN:
    "Telegram verification could not be confirmed. Retry checks when connectivity returns.",
};
const title = (purpose: TelegramPurpose) =>
  purpose === "PRIVATE_ACCOUNT" ? "Private account" : "Work group";
function connectionLabel(value: ConnectionRead) {
  return value.approved
    ? value.availability === "AVAILABLE"
      ? "Connected"
      : "Linked but unavailable"
    : (labels[value.state] ?? value.state);
}

type Confirmation = {
  kind: "replace" | "disconnect" | "test";
  purpose: TelegramPurpose;
  generation: number;
};
export function TelegramConnections({
  technicianId,
  technicianName,
  active,
}: {
  technicianId: string;
  technicianName: string;
  active: boolean;
}) {
  const [data, setData] = useState<TelegramState | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [dialog, setDialog] = useState<TelegramPurpose | null>(null);
  const [issued, setIssued] = useState<IssuedInvitation | null>(null);
  const [copied, setCopied] = useState(false);
  const [confirm, setConfirm] = useState<Confirmation | null>(null);
  const alive = useRef(true);
  const endpoint = `/technicians/${technicianId}/telegram`;
  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const value = await api<TelegramState>(endpoint, { signal });
        if (alive.current && !signal?.aborted) setData(value);
      } catch (failure) {
        if (alive.current && !signal?.aborted) setError(errorMessage(failure));
      }
    },
    [endpoint],
  );
  useEffect(() => {
    alive.current = true;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let stopped = false;
    const poll = async () => {
      if (!document.hidden) await refresh(controller.signal);
      if (!stopped) timer = setTimeout(poll, dialog ? 3000 : 15000);
    };
    void poll();
    return () => {
      stopped = true;
      alive.current = false;
      clearTimeout(timer);
      controller.abort();
    };
  }, [refresh, dialog, active]);
  const connection = (purpose: TelegramPurpose) =>
    purpose === "PRIVATE_ACCOUNT" ? data!.private : data!.group;
  const perform = async (operation: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await operation();
      await refresh();
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  };
  const issue = async (
    purpose: TelegramPurpose,
    generation: number,
    replace: boolean,
  ) => {
    const result = await api<IssuedInvitation>(`${endpoint}/invitations`, {
      method: "POST",
      body: json({
        purpose,
        replace,
        expected_generation: generation,
        confirmation: replace ? "REPLACE" : "CONNECT",
      }),
    });
    setIssued(result);
    setCopied(false);
    setDialog(purpose);
  };
  const generate = (purpose: TelegramPurpose) => {
    const value = connection(purpose);
    if (value.approved)
      setConfirm({ kind: "replace", purpose, generation: value.generation });
    else void perform(() => issue(purpose, value.generation, false));
  };
  const confirmed = () => {
    if (!confirm) return;
    const selection = confirm;
    setConfirm(null);
    void perform(async () => {
      if (selection.kind === "replace")
        await issue(selection.purpose, selection.generation, true);
      else
        await api(
          `${endpoint}/${selection.kind === "test" ? "test-message" : "disconnect"}`,
          {
            method: "POST",
            body: json(
              selection.kind === "test"
                ? {
                    destination: selection.purpose,
                    expected_generation: selection.generation,
                    confirmation: "SEND TEST",
                  }
                : {
                    purpose: selection.purpose,
                    expected_generation: selection.generation,
                    confirmation: "DISCONNECT",
                  },
            ),
          },
        );
    });
  };
  const close = () => {
    setDialog(null);
    setIssued(null);
    setCopied(false);
  };
  const current = dialog && data ? connection(dialog) : null;
  const pending = current?.invitation;
  const open =
    pending &&
    ["LINK_ISSUED", "AWAITING_APPROVAL", "ERROR"].includes(pending.state);
  const configured =
    data && !["DISABLED", "NOT_CONFIGURED"].includes(data.runtime.state);
  const shownLink =
    issued &&
    pending?.id === issued.invitation.id &&
    pending.state === "LINK_ISSUED"
      ? issued
      : null;
  const review = (decision: "APPROVE" | "REJECT") =>
    void perform(async () => {
      await api(`${endpoint}/invitations/${pending!.id}/review`, {
        method: "POST",
        body: json({ decision }),
      });
      setIssued(null);
    });
  return (
    <div className="connection-section telegram-section">
      <h3>TELEGRAM</h3>
      <p className="field-hint" role="status">
        {data
          ? (labels[data.runtime.state] ?? data.runtime.state)
          : "Loading Telegram state..."}
        {data?.runtime.bot_username ? ` · @${data.runtime.bot_username}` : ""}
      </p>
      {data?.runtime.error_code && (
        <p className="warning-text">
          {data.runtime.error_code.replaceAll("_", " ")}
        </p>
      )}
      {!active && (
        <p className="warning-text">
          Inactive technician: new connections and delivery are suspended.
        </p>
      )}
      {data &&
        (["PRIVATE_ACCOUNT", "WORK_GROUP"] as const).map((purpose) => {
          const value = connection(purpose);
          return (
            <div
              className="telegram-destination"
              key={purpose}
              data-testid={purpose}
            >
              <div className="connection-row">
                <span>
                  {purpose === "PRIVATE_ACCOUNT" ? (
                    <MessageCircle size={16} />
                  ) : (
                    <UsersRound size={16} />
                  )}{" "}
                  {title(purpose)}
                </span>
                <span
                  className={`connection-badge ${value.approved && value.availability === "AVAILABLE" ? "available" : ""}`}
                >
                  {connectionLabel(value)}
                </span>
              </div>
              {value.approved && (
                <p className="field-hint">
                  {value.display_name || title(purpose)} · ID{" "}
                  {value.telegram_id}
                  {value.availability !== "AVAILABLE" &&
                    ` · ${value.availability.replaceAll("_", " ")}`}
                </p>
              )}
              {value.replacement_pending && (
                <p className="warning-text">
                  Replacement pending. Current identity is preserved.
                </p>
              )}
              <div className="connection-actions">
                <button
                  className="button secondary"
                  disabled={
                    busy ||
                    (!value.approved &&
                      (!active ||
                        !configured ||
                        (purpose === "WORK_GROUP" && !data.private.approved)))
                  }
                  onClick={() => {
                    setIssued(null);
                    setDialog(purpose);
                  }}
                >
                  {value.approved
                    ? `Manage ${title(purpose).toLowerCase()}`
                    : purpose === "PRIVATE_ACCOUNT"
                      ? "Connect Telegram"
                      : "Connect Work Group"}
                </button>
                {value.approved && (
                  <button
                    className="button secondary"
                    disabled={
                      busy ||
                      !active ||
                      !configured ||
                      value.availability !== "AVAILABLE" ||
                      (purpose === "WORK_GROUP" &&
                        data.private.availability !== "AVAILABLE")
                    }
                    onClick={() =>
                      setConfirm({
                        kind: "test",
                        purpose,
                        generation: value.generation,
                      })
                    }
                  >
                    Test {title(purpose).toLowerCase()}
                  </button>
                )}
              </div>
            </div>
          );
        })}
      <ErrorNotice message={error} retry={() => void refresh()} />
      {data && data.deliveries.length > 0 && (
        <details className="delivery-results">
          <summary>Recent connection activity</summary>
          <p className="field-hint">
            Sent means Telegram accepted the message, not that it was read.
            Unknown outcomes are not automatically retried.
          </p>
          <ul>
            {data.deliveries.map((job) => (
              <li key={job.id}>
                {job.destination === "PRIVATE_ACCOUNT" ? "Private" : "Group"} ·{" "}
                {job.kind === "VERIFY_GROUP"
                  ? "Membership check"
                  : job.kind === "TEST"
                    ? "Test message"
                    : "Approval message"}
                : <strong>{job.state}</strong>
                {job.error_code && ` (${job.error_code.replaceAll("_", " ")})`}
              </li>
            ))}
          </ul>
        </details>
      )}
      {dialog && current && !confirm && (
        <Modal
          title={`${title(dialog)} connection`}
          onClose={close}
          busy={busy}
        >
          <p className="modal-description">
            Technician: <strong>{technicianName}</strong>.{" "}
            {connectionLabel(current)}.
          </p>
          {current.approved && (
            <p>
              Approved identity: {current.display_name || title(dialog)} ·{" "}
              {current.telegram_id}. A replacement stays pending until you
              approve it.
            </p>
          )}
          {dialog === "WORK_GROUP" && (
            <p className="field-hint">
              Select an existing group or create one in Telegram. A
              non-anonymous group administrator must open the invitation. Add
              the approved technician and make the bot an administrator for
              reliable membership checks. Broad moderation permissions are
              unnecessary.
            </p>
          )}
          {pending && (
            <p className="field-hint">
              {labels[pending.state] ?? pending.state} · Expires{" "}
              {new Date(pending.expires_at).toLocaleString()}
            </p>
          )}
          {shownLink && (
            <div className="invite-display">
              <label>
                Invitation link
                <input
                  aria-label="Invitation link"
                  readOnly
                  value={shownLink.link}
                />
              </label>
              <div className="connection-actions">
                <button
                  className="button secondary"
                  onClick={() =>
                    void navigator.clipboard
                      .writeText(shownLink.link)
                      .then(() => setCopied(true))
                      .catch(() =>
                        setError(
                          "Copy failed. Select and copy the link manually.",
                        ),
                      )
                  }
                >
                  {copied ? "Copied" : "Copy link"}
                </button>
                <a
                  className="button secondary"
                  href={shownLink.link}
                  target="_blank"
                  rel="noopener noreferrer"
                  referrerPolicy="no-referrer"
                >
                  Open Telegram
                </a>
              </div>
              <div className="invite-qr">
                <QRCodeSVG
                  value={shownLink.link}
                  size={172}
                  marginSize={4}
                  title="Telegram invitation QR code"
                />
              </div>
              <p className="field-hint">
                QR code is generated locally. Closing this dialog clears the
                displayed link; generate a new one if needed.
              </p>
              {shownLink.fallback_command && (
                <label>
                  If Telegram does not send Start in an existing group, paste
                  this command there:
                  <textarea
                    aria-label="Group fallback command"
                    readOnly
                    value={shownLink.fallback_command}
                  />
                </label>
              )}
            </div>
          )}
          {open && pending.candidate_user_id && (
            <div className="candidate-review">
              <h3>Review candidate for {technicianName}</h3>
              {dialog === "WORK_GROUP" && (
                <p>
                  <strong>
                    {pending.candidate_chat_title || "Untitled group"}
                  </strong>
                  <br />
                  Group ID: {pending.candidate_chat_id}
                </p>
              )}
              <p>
                {dialog === "WORK_GROUP"
                  ? "Initiating account: "
                  : "Telegram account: "}
                <strong>
                  {pending.candidate_display_name || "No display name"}
                </strong>
                {pending.candidate_username
                  ? ` (@${pending.candidate_username})`
                  : " (no username)"}
                <br />
                User ID: {pending.candidate_user_id}
              </p>
              {dialog === "WORK_GROUP" && (
                <ul className="check-results">
                  <li>
                    Initiator administrator:{" "}
                    {pending.initiator_admin ? "Verified" : "Needs attention"}
                  </li>
                  <li>
                    Bot administrator:{" "}
                    {pending.bot_admin ? "Verified" : "Needs attention"}
                  </li>
                  <li>
                    Technician membership:{" "}
                    {pending.technician_member ? "Verified" : "Needs attention"}
                  </li>
                </ul>
              )}
              {pending.setup_error && (
                <p role="alert">
                  {setup[pending.setup_error] ??
                    "Verification is unavailable. Check group membership and permissions, then retry checks."}
                </p>
              )}
              <div className="connection-actions">
                <button
                  className="button primary"
                  disabled={
                    busy || !active || pending.state !== "AWAITING_APPROVAL"
                  }
                  onClick={() => review("APPROVE")}
                >
                  {dialog === "PRIVATE_ACCOUNT"
                    ? "Approve account"
                    : "Approve group"}
                </button>
                <button
                  className="button secondary"
                  disabled={busy}
                  onClick={() => review("REJECT")}
                >
                  Reject candidate
                </button>
                {dialog === "WORK_GROUP" && (
                  <button
                    className="button secondary"
                    disabled={busy}
                    onClick={() =>
                      void perform(async () => {
                        await api(
                          `${endpoint}/invitations/${pending.id}/retry`,
                          { method: "POST" },
                        );
                      })
                    }
                  >
                    Retry checks
                  </button>
                )}
              </div>
            </div>
          )}
          <ErrorNotice message={error} />
          <div className="modal-actions telegram-modal-actions">
            {open && (
              <button
                className="button secondary"
                disabled={busy}
                onClick={() =>
                  void perform(async () => {
                    await api(`${endpoint}/invitations/${pending.id}/revoke`, {
                      method: "POST",
                    });
                    setIssued(null);
                  })
                }
              >
                Revoke invitation
              </button>
            )}
            <button
              className="button secondary"
              disabled={busy || !active || !configured}
              onClick={() => generate(dialog)}
            >
              {current.approved
                ? "Replace connection"
                : open
                  ? "Regenerate invitation"
                  : "Generate invitation"}
            </button>
            {current.approved && (
              <button
                className="button danger-outline"
                disabled={busy}
                onClick={() =>
                  setConfirm({
                    kind: "disconnect",
                    purpose: dialog,
                    generation: current.generation,
                  })
                }
              >
                Disconnect {title(dialog).toLowerCase()}
              </button>
            )}
          </div>
        </Modal>
      )}
      {confirm && (
        <Modal
          title={
            confirm.kind === "test"
              ? "Send connection test?"
              : confirm.kind === "replace"
                ? "Replace connection?"
                : "Disconnect connection?"
          }
          onClose={() => setConfirm(null)}
          busy={busy}
        >
          <p className="modal-description">
            <strong>
              {technicianName} · {title(confirm.purpose)}
            </strong>
          </p>
          <p>
            {confirm.kind === "test"
              ? "Send one connection-test message to this approved destination?"
              : confirm.kind === "replace"
                ? "Generate a replacement invitation? The current identity remains approved until the new candidate is approved. Replacing the private account suspends group delivery until revalidation."
                : confirm.purpose === "PRIVATE_ACCOUNT"
                  ? "Disconnect this private account and suspend group delivery? The group identity stays reserved until revalidated or disconnected."
                  : "Disconnect this work group? The private account remains connected."}
          </p>
          <div className="modal-actions">
            <button
              className="button secondary"
              onClick={() => setConfirm(null)}
            >
              Cancel
            </button>
            <button className="button primary" onClick={confirmed}>
              {confirm.kind === "test"
                ? "Send test message"
                : confirm.kind === "replace"
                  ? "Confirm replacement"
                  : "Confirm disconnect"}
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
