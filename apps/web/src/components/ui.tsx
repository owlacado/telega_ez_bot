/* eslint-disable @next/next/no-img-element -- Explicit profile URLs are browser-loaded; the API never fetches remote images. */
"use client";
import { useState, type ReactNode } from "react";
import { initials, statusLabel } from "@hub/shared";
import { AlertCircle, LoaderCircle } from "lucide-react";

export function Avatar({
  firstName,
  lastName,
  url,
  large = false,
}: {
  firstName: string;
  lastName: string;
  url?: string | null;
  large?: boolean;
}) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  return (
    <div className={`avatar ${large ? "avatar-large" : ""}`}>
      {url && failedUrl !== url ? (
        <img
          src={url}
          alt={`${firstName} ${lastName}`}
          referrerPolicy="no-referrer"
          onError={() => setFailedUrl(url)}
        />
      ) : (
        <span>{initials(firstName, lastName)}</span>
      )}
    </div>
  );
}
export function Status({ value }: { value: string }) {
  return (
    <span
      className={`status ${value === "ACTIVE" || value === "CONNECTED" ? "status-green" : "status-neutral"}`}
    >
      <i />
      {statusLabel(value)}
    </span>
  );
}
export function ErrorNotice({
  message,
  retry,
}: {
  message: string;
  retry?: () => void;
}) {
  if (!message) return null;
  return (
    <div className="error-notice" role="alert">
      <AlertCircle size={18} />
      <span>{message}</span>
      {retry && (
        <button className="text-button" onClick={retry}>
          Try again
        </button>
      )}
    </div>
  );
}
export function Loading() {
  return (
    <div className="loading" role="status">
      <LoaderCircle className="spin" size={20} /> Loading workspace…
    </div>
  );
}
export function EmptyState({
  icon,
  title,
  children,
}: {
  icon: ReactNode;
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-icon">{icon}</div>
      <h3>{title}</h3>
      <div className="muted">{children}</div>
    </div>
  );
}
export function DisabledAction({
  children,
  reason,
  className = "button secondary",
}: {
  children: ReactNode;
  reason: string;
  className?: string;
}) {
  return (
    <span
      className="disabled-wrap"
      tabIndex={0}
      title={reason}
      aria-label={reason}
    >
      <button type="button" className={className} disabled>
        {children}
      </button>
      <span className="tooltip" role="tooltip">
        {reason}
      </span>
    </span>
  );
}
