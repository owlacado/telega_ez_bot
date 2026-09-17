import type { components } from "./schema";
export type Technician = components["schemas"]["TechnicianSummary"];
export type TechnicianDetail = components["schemas"]["TechnicianDetail"];
export type Calendar = components["schemas"]["CalendarRead"];
export type TechnicianCreate = components["schemas"]["TechnicianCreate"];
export type TechnicianUpdate = components["schemas"]["TechnicianUpdate"];
export type LocationState =
  "ACTIVE_TRIP" | "LAST_KNOWN_STOP" | "NO_DATA" | "UNKNOWN";

export type TelegramState = components["schemas"]["TelegramState"];
export type ConnectionRead = components["schemas"]["ConnectionRead"];
export type IssuedInvitation = components["schemas"]["IssuedInvitation"];
export type TelegramPurpose =
  components["schemas"]["IssueInvitation"]["purpose"];

export type ManagerSession = components["schemas"]["ManagerRead"];

export type GoogleConnection = components["schemas"]["GoogleConnectionRead"];
