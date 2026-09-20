import type { components } from "./schema";
export type WorkReportForm = components["schemas"]["FormRead"];
export type WorkReport = components["schemas"]["ReportRead"];
export type WorkReportList = components["schemas"]["ReportList"];
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

export type ScheduleRead = components["schemas"]["ScheduleRead"];

export type DeliveryRead = components["schemas"]["ScheduleDeliveryRead"];
export type DispatchRead = components["schemas"]["DispatchRead"];

export type ExpenseForm = components["schemas"]["ExpenseForm"];
export type ExpenseReceipt = components["schemas"]["ExpenseReceipt"];
export type ExpenseInput = components["schemas"]["ExpenseInput"];
export type ExpenseRead = components["schemas"]["ExpenseRead"];
export type ExpenseList = components["schemas"]["ExpenseList"];

export type DailyAccounting = components["schemas"]["DailyAccounting"];
export type WeeklyAccounting = components["schemas"]["WeeklyAccounting"];
export type CurrentAccounting = components["schemas"]["CurrentAccounting"];
export type AccountingTotals = components["schemas"]["AccountingTotals"];
export type AccountingMirrorStatus = components["schemas"]["MirrorStatusRead"];
export type OperationsHealth = components["schemas"]["OperationsHealth"];
