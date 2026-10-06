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
  PENDING: "Waiting for technician",
  LINK_ISSUED: "Waiting for technician",
  CLAIMED: "Connected",
  AWAITING_APPROVAL: "Waiting for manager approval",
  CONNECTED: "Connected",
  EXPIRED: "Invitation expired",
  ERROR: "Setup needs attention",
  REVOKED: "Invitation revoked",
  REJECTED: "Candidate rejected",
};
const setup: Record<string, string> = {
  BOT_CANNOT_SEND:
    "Add the bot as a member and allow it to send messages, then generate a new invitation.",
  IDENTITY_IN_USE:
    "This Telegram identity is already linked. Disconnect it from its current technician before generating a new invitation.",
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
  purpose === "PRIVATE_TELEGRAM" ? "Private account" : "Work group";
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
  const [now, setNow] = useState(() => Date.now());
  const [retry, setRetry] = useState(0);
  const [confirm, setConfirm] = useState<Confirmation | null>(null);
  const alive = useRef(true);
  const submitting = useRef(false);
  const sequence = useRef(0);
  const endpoint = `/technicians/${technicianId}/telegram`;
  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      const request = ++sequence.current;
      try {
        const value = await api<TelegramState>(endpoint, { signal });
        if (alive.current && !signal?.aborted && request === sequence.current) {
          setData(value);
          setIssued((credential) => {
            if (!credential) return null;
            const state =
              credential.invitation.purpose === "PRIVATE_TELEGRAM"
                ? value.private
                : value.group;
            return state.invitation?.id === credential.invitation.id &&
              ["PENDING", "LINK_ISSUED"].includes(state.invitation.state) &&
              Date.parse(credential.invitation.expires_at) > Date.now()
              ? credential
              : null;
          });
          setError("");
        }
        return value;
      } catch (failure) {
        if (alive.current && !signal?.aborted && request === sequence.current) {
          setError(errorMessage(failure));
          setIssued(null);
        }
        return null;
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
      if (!document.hidden && !submitting.current) {
        const result = await refresh(controller.signal);
        if (dialog) {
          const selected =
            dialog === "PRIVATE_TELEGRAM" ? result?.private : result?.group;
          if (
            !selected?.invitation ||
            !["PENDING", "LINK_ISSUED", "AWAITING_APPROVAL"].includes(
              selected.invitation.state,
            )
          )
            return;
        }
      }
      if (!stopped) timer = setTimeout(poll, dialog ? 2000 : 15000);
    };
    void poll();
    return () => {
      stopped = true;
      alive.current = false;
      clearTimeout(timer);
      controller.abort();
    };
  }, [refresh, dialog, active, retry]);
  useEffect(() => {
    if (!dialog) return;
    const timer = setInterval(() => {
      const time = Date.now();
      setNow(time);
      setIssued((credential) =>
        credential && Date.parse(credential.invitation.expires_at) <= time
          ? null
          : credential,
      );
    }, 1000);
    return () => clearInterval(timer);
  }, [dialog]);
  const connection = (purpose: TelegramPurpose) =>
    purpose === "PRIVATE_TELEGRAM" ? data!.private : data!.group;
  const perform = async (operation: () => Promise<void>) => {
    if (submitting.current) return;
    submitting.current = true;
    sequence.current += 1;
    setBusy(true);
    setError("");
    try {
      await operation();
      if (alive.current) await refresh();
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      submitting.current = false;
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
    if (!alive.current) return;
    setData((value) =>
      value
        ? {
            ...value,
            [purpose === "PRIVATE_TELEGRAM" ? "private" : "group"]: {
              ...(purpose === "PRIVATE_TELEGRAM" ? value.private : value.group),
              invitation: result.invitation,
              state: result.invitation.state,
            },
          }
        : value,
    );
    setIssued(result);
    setCopied(false);
    setDialog(purpose);
    setRetry((value) => value + 1);
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
  const seconds = pending
    ? Math.max(0, Math.ceil((Date.parse(pending.expires_at) - now) / 1000))
    : 0;
  const pendingState =
    pending &&
    seconds === 0 &&
    ["PENDING", "LINK_ISSUED"].includes(pending.state)
      ? "EXPIRED"
      : pending?.state;
  const open =
    pending &&
    ["PENDING", "LINK_ISSUED", "AWAITING_APPROVAL", "ERROR"].includes(
      pendingState ?? "",
    );
  const configured =
    data && !["DISABLED", "NOT_CONFIGURED"].includes(data.runtime.state);
  const shownLink =
    issued &&
    pending?.id === issued.invitation.id &&
    ["PENDING", "LINK_ISSUED"].includes(pendingState ?? "")
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
        (["PRIVATE_TELEGRAM", "WORK_GROUP"] as const).map((purpose) => {
          const value = connection(purpose);
          return (
            <div
              className="telegram-destination"
              key={purpose}
              data-testid={purpose}
            >
              <div className="connection-row">
                <span>
                  {purpose === "PRIVATE_TELEGRAM" ? (
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
                  {value.username
                    ? `@${value.username}`
                    : value.display_name || title(purpose)}
                  {value.availability !== "AVAILABLE" &&
                    ` · ${value.availability.replaceAll("_", " ")}`}
                </p>
              )}
              {value.telegram_id && (
                <details className="field-hint">
                  <summary>Technical details</summary>Telegram ID:{" "}
                  {value.telegram_id}
                </details>
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
                    if (!value.approved && !value.invitation) generate(purpose);
                  }}
                >
                  {value.approved
                    ? `Manage ${title(purpose).toLowerCase()}`
                    : purpose === "PRIVATE_TELEGRAM"
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
      <ErrorNotice
        message={error}
        retry={() => setRetry((value) => value + 1)}
      />
      {data && data.deliveries.length > 0 && (
        <details className="delivery-results">
          <summary>Recent Telegram activity</summary>
          <p className="field-hint">
            Sent means Telegram accepted the message, not that it was read.
            Unknown outcomes are not automatically retried.
          </p>
          <ul>
            {data.deliveries.map((job) => (
              <li key={job.id}>
                {job.destination === "PRIVATE_TELEGRAM" ? "Private" : "Group"} ·{" "}
                {job.kind === "VERIFY_GROUP"
                  ? "Membership check"
                  : job.kind === "TEST"
                    ? "Test message"
                    : job.kind === "WORK_REPORT"
                      ? "Work report"
                      : job.kind === "EXPENSE"
                        ? "Expense"
                        : "Connection message"}
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
              <span role="status">
                {dialog === "PRIVATE_TELEGRAM"
                  ? "Telegram connected"
                  : "Work group connected"}
              </span>{" "}
              {current.username
                ? `@${current.username}`
                : current.display_name || title(dialog)}
              . A replacement connects when its new invitation is claimed.
            </p>
          )}
          {dialog === "WORK_GROUP" && (
            <p className="field-hint">
              Select an existing group or create one in Telegram. A group member
              using this technician&apos;s linked Telegram account must send the
              Start command. The bot needs membership and permission to send
              messages, not administrator privileges. If a group administrator
              must add the bot, the technician must then use the fallback
              command.
            </p>
          )}
          {pending && (
            <p className="field-hint">
              {dialog === "WORK_GROUP" && pendingState === "PENDING"
                ? "Waiting for Telegram group"
                : (labels[pendingState ?? ""] ?? pendingState)}{" "}
              /{" "}
              {seconds > 0
                ? `Invitation expires in ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`
                : "Invitation expired"}
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
                  {dialog === "WORK_GROUP"
                    ? "Add Bot to Group"
                    : "Open Telegram"}
                </a>
                <button
                  className="button secondary"
                  onClick={() =>
                    void navigator.clipboard
                      .writeText(
                        dialog === "PRIVATE_TELEGRAM"
                          ? `Connect ${technicianName} to Technician Hub: open ${shownLink.link} and press Start using the technician's Telegram account. This private invitation expires shortly; do not forward it.`
                          : `Connect ${technicianName}'s work group: use the technician's already-linked Telegram account to open ${shownLink.link}. Add the bot as a member with permission to send messages. If it is already present, send ${shownLink.fallback_command} in that group from the linked account. This invitation expires shortly; do not forward it.`,
                      )
                      .then(() => setCopied(true))
                      .catch(() =>
                        setError("Copy failed. Copy the link manually."),
                      )
                  }
                >
                  Copy setup instructions
                </button>
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
          {open && !pending.automatic && pending.candidate_user_id && (
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
                  {dialog === "PRIVATE_TELEGRAM"
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
          {pending?.automatic && pending.setup_error && (
            <p role="alert">
              {pending.setup_error === "ACCESS_DENIED" ||
              pending.setup_error === "CHAT_UNAVAILABLE"
                ? "Restore the bot's group access and permission to send messages, then generate a new invitation."
                : pending.setup_error === "NETWORK_UNCERTAIN"
                  ? "Telegram verification could not be confirmed. Generate a new invitation when connectivity returns."
                  : (setup[pending.setup_error] ??
                    "Connection could not be verified. Generate a new invitation and try again.")}
            </p>
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
                ? "Generate a replacement invitation? The current identity remains connected until the new invitation is claimed. Replacing the private account suspends group delivery until revalidation."
                : confirm.purpose === "PRIVATE_TELEGRAM"
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
