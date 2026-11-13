/** OAuth clients. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, call, type Schemas } from "./client";
import { qk } from "./keys";

export function useClients(app?: string) {
  return useQuery({
    queryKey: qk.clients.list(app),
    queryFn: () => call(api.GET("/v1/admin/clients", { params: { query: { app: app || undefined } } })),
  });
}

export function useClient(clientId: string) {
  return useQuery({
    queryKey: qk.clients.detail(clientId),
    queryFn: () =>
      call(api.GET("/v1/admin/clients/{client_id}", { params: { path: { client_id: clientId } } })),
  });
}

function useClientsInvalidation() {
  const queryClient = useQueryClient();
  return () => {
    queryClient.invalidateQueries({ queryKey: qk.clients.all });
    queryClient.invalidateQueries({ queryKey: qk.stats });
  };
}

export function useCreateClient() {
  const invalidate = useClientsInvalidation();
  return useMutation({
    mutationFn: (body: Schemas["ClientCreate"]) => call(api.POST("/v1/admin/clients", { body })),
    onSuccess: invalidate,
  });
}

export function useUpdateClient(clientId: string) {
  const invalidate = useClientsInvalidation();
  return useMutation({
    mutationFn: (body: Schemas["ClientUpdate"]) =>
      call(api.PATCH("/v1/admin/clients/{client_id}", { params: { path: { client_id: clientId } }, body })),
    onSuccess: invalidate,
  });
}

export function useRotateClientSecret(clientId: string) {
  const invalidate = useClientsInvalidation();
  return useMutation({
    mutationFn: () =>
      call(
        api.POST("/v1/admin/clients/{client_id}/rotate-secret", {
          params: { path: { client_id: clientId } },
        }),
      ),
    onSuccess: invalidate,
  });
}
