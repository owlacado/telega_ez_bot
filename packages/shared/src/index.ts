export function initials(firstName: string, lastName: string): string {
  return `${Array.from(firstName)[0] ?? ""}${Array.from(lastName)[0] ?? ""}`.toUpperCase();
}
export function statusLabel(value: string): string {
  return value.toLowerCase().replaceAll("_", " ");
}
