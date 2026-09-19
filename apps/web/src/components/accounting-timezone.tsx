"use client";
import { useResource } from "@/lib/use-resource";
const common = [
  ["America/New_York", "Eastern — New York"],
  ["America/Chicago", "Central — Chicago"],
  ["America/Denver", "Mountain — Denver"],
  ["America/Los_Angeles", "Pacific — Los Angeles"],
  ["America/Phoenix", "Arizona — Phoenix (no DST)"],
  ["America/Anchorage", "Alaska — Anchorage"],
  ["Pacific/Honolulu", "Hawaii — Honolulu (no DST)"],
  ["UTC", "UTC"],
];
export function AccountingTimezone({ value }: { value?: string | null }) {
  const { data, error } = useResource<string[]>("/accounting-timezones");
  const zones = Array.isArray(data) ? data : [];
  const others = [...new Set([...(value ? [value] : []), ...zones])]
    .filter((zone) => !common.some(([id]) => id === zone))
    .sort();
  return (
    <label>
      Accounting timezone
      <select name="accounting_timezone" defaultValue={value ?? ""}>
        <option value="">Not configured — expenses unavailable</option>
        <optgroup label="Common US timezones">
          {common.map(([id, label]) => (
            <option key={id} value={id}>
              {label} ({id})
            </option>
          ))}
        </optgroup>
        <optgroup label="Other timezones">
          {others.map((zone) => (
            <option key={zone} value={zone}>
              {zone}
            </option>
          ))}
        </optgroup>
      </select>
      {error && (
        <span className="field-hint">
          Full timezone list unavailable. Common zones and the saved value are
          available.
        </span>
      )}
    </label>
  );
}
