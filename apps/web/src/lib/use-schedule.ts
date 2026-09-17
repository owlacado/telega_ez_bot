"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import type { ScheduleRead } from "@hub/contracts";
import { api } from "./api";

// One mounted reader per date window; no durable event cache. Abort and identity
// checks guard both successful and failed requests, even if transport ignores abort.
export function useSchedule(path: string | null, assignment: string = "") {
  const identity = `${path}:${assignment}`;
  const [version, setVersion] = useState(0);
  const [result, setResult] = useState<{
    identity: string;
    version: number;
    data: ScheduleRead | null;
    error: boolean;
  }>({ identity, version: -1, data: null, error: false });
  const pending = useRef(false);
  const refresh = useCallback(() => {
    if (pending.current) return;
    pending.current = true;
    setVersion((v) => v + 1);
  }, []);
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    pending.current = true;
    // Strict Mode setup/cleanup completes before dispatch, avoiding duplicate reads.
    queueMicrotask(() => {
      if (controller.signal.aborted) return;
      api<ScheduleRead>(path, { signal: controller.signal })
        .then((data) => {
          if (!controller.signal.aborted)
            setResult({ identity, version, data, error: false });
        })
        .catch(() => {
          if (!controller.signal.aborted)
            setResult({ identity, version, data: null, error: true });
        })
        .finally(() => {
          if (!controller.signal.aborted) pending.current = false;
        });
    });
    return () => {
      controller.abort();
      pending.current = false;
    };
  }, [path, identity, version]);
  const current = result.identity === identity && result.version === version;
  return {
    data: current ? result.data : null,
    error: current && result.error,
    loading: !!path && !current,
    refresh,
  };
}
