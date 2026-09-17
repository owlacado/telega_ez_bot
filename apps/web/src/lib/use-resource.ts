"use client";
import { useCallback, useEffect, useState, type SetStateAction } from "react";
import { api, errorMessage } from "./api";
export function useResource<T>(path: string) {
  const [result, setResult] = useState<{
    path: string;
    data: T | null;
    error: string;
  }>({ path, data: null, error: "" });
  const [version, setVersion] = useState(0);
  const reload = useCallback(() => setVersion((value) => value + 1), []);
  const setData = useCallback(
    (value: SetStateAction<T | null>) => {
      setResult((previous) =>
        previous.path !== path
          ? previous
          : {
              path,
              error: "",
              data:
                typeof value === "function"
                  ? (value as (old: T | null) => T | null)(
                      previous.path === path ? previous.data : null,
                    )
                  : value,
            },
      );
    },
    [path],
  );
  useEffect(() => {
    const controller = new AbortController();
    api<T>(path, { signal: controller.signal })
      .then((data) => {
        if (!controller.signal.aborted) setResult({ path, data, error: "" });
      })
      .catch((error) => {
        if (!controller.signal.aborted)
          setResult((previous) => ({
            path,
            data: previous.path === path ? previous.data : null,
            error: errorMessage(error),
          }));
      });
    return () => controller.abort();
  }, [path, version]);
  // Never expose another URL's identity, even during the render before effects run.
  return {
    data: result.path === path ? result.data : null,
    error: result.path === path ? result.error : "",
    reload,
    setData,
  };
}
