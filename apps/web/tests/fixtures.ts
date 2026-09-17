import type { TechnicianDetail, Calendar } from "@hub/contracts";
export const technician: TechnicianDetail = {
  id: "11111111-1111-4111-8111-111111111111",
  first_name: "Demo",
  last_name: "Technician",
  photo_url: null,
  status: "ACTIVE",
  calendar: null,
  integrations: {
    telegram_private: "NOT_CONNECTED",
    telegram_group: "NOT_CONNECTED",
    gps_provider: "NONE",
    gps_status: "NOT_CONNECTED",
  },
  driver_license_id: null,
  ssn_last4: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};
export const calendar: Calendar = {
  id: "22222222-2222-4222-8222-222222222222",
  name: "DEMO - Calendar",
  assigned_technician: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};
