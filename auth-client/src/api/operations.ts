/** Dashboard counts, signing keys, downstream sync and the audit log. */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, call } from "./client";
import { qk, type AuditFilters } from "./keys";

export const AUDIT_PAGE_SIZE = 50;

export function useStats() {
  return useQuery({ queryKey: qk.stats, queryFn: () => call(api.GET("/v1/admin/stats")), staleTime: 30_000 });
}

export function useSigningKeys() {
  return useQuery({ queryKey: qk.signingKeys, queryFn: () => call(api.GET("/v1/admin/keys")) });
}

export function useRotateKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => call(api.POST("/v1/admin/keys/rotate")),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: qk.signingKeys }),
  });
}

export function useRevokeKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (kid: string) => call(api.DELETE("/v1/admin/keys/{kid}", { params: { path: { kid } } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: qk.signingKeys }),
  });
}

/** Refreshed every 10 seconds while a page shows it. */
export function useDownstream() {
  return useQuery({
    queryKey: qk.downstream,
    queryFn: () => call(api.GET("/v1/admin/downstream")),
    refetchInterval: 10_000,
  });
}

export function useAudit(filters: AuditFilters, limit = AUDIT_PAGE_SIZE) {
  return useQuery({
    queryKey: [...qk.audit.list(filters), limit],
    queryFn: () =>
      call(
        api.GET("/v1/admin/audit", {
          params: {
            query: {
              limit,
              offset: filters.offset,
              actor: filters.actor || undefined,
              action: filters.action || undefined,
              app: filters.app || undefined,
            },
          },
        }),
      ),
    placeholderData: keepPreviousData,
  });
}
