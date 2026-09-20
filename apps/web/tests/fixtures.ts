import type {
  Calendar,
  OperationsHealth,
  TechnicianDetail,
} from "@hub/contracts";
export const technician: TechnicianDetail = {
  id: "11111111-1111-4111-8111-111111111111",
  first_name: "Demo",
  last_name: "Technician",
  status: "ACTIVE",
  record_version: 1,
  calendar: null,
  integrations: {
    telegram_private: "NOT_CONNECTED",
    telegram_group: "NOT_CONNECTED",
    gps_provider: "NONE",
    gps_status: "NOT_CONNECTED",
  },
  pilot_readiness: {
    ready: false,
    blocking_count: 3,
    requirements: [
      {
        key: "profile",
        label: "Active profile",
        status: "READY",
        required: true,
        reason: "Technician profile is active.",
        action: null,
      },
      {
        key: "accounting_timezone",
        label: "Accounting timezone",
        status: "NEEDS_ACTION",
        required: true,
        reason: "Work Reports and Expenses require an explicit IANA timezone.",
        action: "Set the accounting timezone.",
      },
    ],
  },
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};
export const calendar: Calendar = {
  source: "LOCAL_DEMO",
  availability: "AVAILABLE",
  primary: false,
  id: "22222222-2222-4222-8222-222222222222",
  name: "DEMO - Calendar",
  assigned_technician: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

export const operationsHealth: OperationsHealth = {
  status: "PASS",
  app_version: "0.3.0",
  release_commit: "1234567890abcdef1234567890abcdef12345678",
  database: { state: "PASS", message: "PostgreSQL query succeeded." },
  migration: { state: "PASS", message: "Database schema is current." },
  telegram_worker: {
    state: "DISABLED",
    message: "Feature is intentionally disabled.",
  },
  schedule_worker: {
    state: "DISABLED",
    message: "Feature is intentionally disabled.",
  },
  mirror_worker: {
    state: "DISABLED",
    message: "Feature is intentionally disabled.",
  },
  google_configuration: {
    state: "DISABLED",
    message: "Google provider is intentionally disabled.",
  },
  queues: {
    telegram: { pending: 0, processing: 0, failed: 0, ambiguous: 0 },
    schedule: { pending: 0, processing: 0, failed: 0, ambiguous: 0 },
    mirror: { pending: 0, processing: 0, failed: 0, ambiguous: 0 },
  },
};
