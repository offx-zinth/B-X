// Deduplicated fetch layer with TanStack-Query-compatible semantics.
// useQuery({queryKey, queryFn, staleTime}) dedupes waterfalls and caches per
// tenant; swap the internals for @tanstack/react-query without changing call
// sites when the app grows (staleTime default 30s matches graph routes).
"use client";
import { useEffect, useRef, useState } from "react";

const CACHE = new Map<string, { at: number; data: any }>();
const INFLIGHT = new Map<string, Promise<any>>();

export async function query<T>(key: string, fn: () => Promise<T>, staleTime = 30_000): Promise<T> {
  const hit = CACHE.get(key);
  if (hit && Date.now() - hit.at < staleTime) return hit.data as T;
  const ongoing = INFLIGHT.get(key);
  if (ongoing) return ongoing as Promise<T>;
  const p = fn().then(d => {
    CACHE.set(key, { at: Date.now(), data: d });
    INFLIGHT.delete(key);
    return d;
  }).catch(e => { INFLIGHT.delete(key); throw e; });
  INFLIGHT.set(key, p);
  return p;
}

export function useQuery<T>({ queryKey, queryFn, staleTime = 30_000 }: {
  queryKey: (string | number)[]; queryFn: () => Promise<T>; staleTime?: number;
}) {
  const key = queryKey.join(":");
  const [data, setData] = useState<T | undefined>(CACHE.get(key)?.data);
  const [isLoading, setLoading] = useState(data === undefined);
  const [error, setError] = useState<any>(null);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    setLoading(data === undefined);
    query<T>(key, queryFn, staleTime).then(
      d => { if (alive.current) { setData(d); setLoading(false); } },
      e => { if (alive.current) { setError(e); setLoading(false); } },
    );
    return () => { alive.current = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return { data, isLoading, error, refetch: () => query<T>(key, queryFn, 0).then(setData) };
}

export function invalidate(prefix: string) {
  for (const k of [...CACHE.keys()]) if (k.startsWith(prefix)) CACHE.delete(k);
}
