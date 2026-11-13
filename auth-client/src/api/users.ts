/** User administration. */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, call, type Schemas } from "./client";
import { qk, type UsersFilters } from "./keys";

export const USERS_PAGE_SIZE = 25;

export function useUsers(filters: UsersFilters) {
  return useQuery({
    queryKey: qk.users.list(filters),
    queryFn: () =>
      call(
        api.GET("/v1/admin/users", {
          params: {
            query: {
              limit: USERS_PAGE_SIZE,
              offset: filters.offset,
              q: filters.q || undefined,
              app: filters.app || undefined,
              active: filters.status === "active" ? true : filters.status === "disabled" ? false : undefined,
            },
          },
        }),
      ),
    placeholderData: keepPreviousData,
  });
}

export function useUser(id: string) {
  return useQuery({
    queryKey: qk.users.detail(id),
    queryFn: () => call(api.GET("/v1/admin/users/{public_id}", { params: { path: { public_id: id } } })),
  });
}

export function useUserSessions(id: string) {
  return useQuery({
    queryKey: qk.users.sessions(id),
    queryFn: () =>
      call(api.GET("/v1/admin/users/{public_id}/sessions", { params: { path: { public_id: id } } })),
  });
}

export function useUserFactors(id: string) {
  return useQuery({
    queryKey: qk.users.factors(id),
    queryFn: () => call(api.GET("/v1/admin/users/{public_id}/mfa", { params: { path: { public_id: id } } })),
  });
}

function useUsersInvalidation() {
  const queryClient = useQueryClient();
  return () => {
    queryClient.invalidateQueries({ queryKey: qk.users.all });
    queryClient.invalidateQueries({ queryKey: qk.stats });
  };
}

export function useCreateUser() {
  const invalidate = useUsersInvalidation();
  return useMutation({
    mutationFn: (body: Schemas["UserCreate"]) => call(api.POST("/v1/admin/users", { body })),
    onSuccess: invalidate,
  });
}

export function useUpdateUser(id: string) {
  const invalidate = useUsersInvalidation();
  return useMutation({
    mutationFn: (body: Schemas["UserUpdate"]) =>
      call(api.PATCH("/v1/admin/users/{public_id}", { params: { path: { public_id: id } }, body })),
    onSuccess: invalidate,
  });
}

export function useSetUserRoles(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["UserRolesSet"]) =>
      call(api.PUT("/v1/admin/users/{public_id}/roles", { params: { path: { public_id: id } }, body })),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: qk.users.all });
      queryClient.invalidateQueries({ queryKey: qk.apps.all });
    },
  });
}

export function useEndUserSessions(id: string) {
  const invalidate = useUsersInvalidation();
  return useMutation({
    mutationFn: () =>
      call(api.DELETE("/v1/admin/users/{public_id}/sessions", { params: { path: { public_id: id } } })),
    onSuccess: invalidate,
  });
}

export function useEndSession(userId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (sessionId: string) =>
      call(api.DELETE("/v1/admin/sessions/{session_id}", { params: { path: { session_id: sessionId } } })),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: qk.users.sessions(userId) });
      queryClient.invalidateQueries({ queryKey: qk.stats });
    },
  });
}

export function useResetPassword(id: string) {
  const invalidate = useUsersInvalidation();
  return useMutation({
    mutationFn: (newPassword: string) =>
      call(
        api.POST("/v1/admin/users/{public_id}/password", {
          params: { path: { public_id: id } },
          body: { new_password: newPassword },
        }),
      ),
    onSuccess: invalidate,
  });
}

export function useResetMfa(id: string) {
  const invalidate = useUsersInvalidation();
  return useMutation({
    mutationFn: () =>
      call(api.DELETE("/v1/admin/users/{public_id}/mfa", { params: { path: { public_id: id } } })),
    onSuccess: invalidate,
  });
}
