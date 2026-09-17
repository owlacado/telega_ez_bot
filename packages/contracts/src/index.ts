import type { components } from "./schema";
export type Technician = components["schemas"]["TechnicianSummary"];
export type TechnicianDetail = components["schemas"]["TechnicianDetail"];
export type Calendar = components["schemas"]["CalendarRead"];
export type TechnicianCreate = components["schemas"]["TechnicianCreate"];
export type TechnicianUpdate = components["schemas"]["TechnicianUpdate"];
export type LocationState =
  "ACTIVE_TRIP" | "LAST_KNOWN_STOP" | "NO_DATA" | "UNKNOWN";
