/** Applications, their permissions, roles and members. */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, call, type Schemas } from "./client";
import { qk } from "./keys";

export const PAGE_SIZE = 50;

export function useApplications(offset = 0) {
  return useQuery({
    queryKey: qk.apps.list(offset),
    queryFn: () =>
      call(api.GET("/v1/admin/applications", { params: { query: { limit: PAGE_SIZE, offset } } })),
    placeholderData: keepPreviousData,
  });
}

/** Every application key and name, for selects and filters. */
export function useApplicationOptions() {
  return useQuery({
    queryKey: qk.apps.options,
    queryFn: async () => {
      const page = await call(
        api.GET("/v1/admin/applications", { params: { query: { limit: 200, offset: 0 } } }),
      );
      return page.items;
    },
    staleTime: 60_000,
  });
}

export function useApplication(key: string) {
  return useQuery({
    queryKey: qk.apps.detail(key),
    queryFn: () => call(api.GET("/v1/admin/applications/{key}", { params: { path: { key } } })),
  });
}

export function useCreateApplication() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["ApplicationCreate"]) => call(api.POST("/v1/admin/applications", { body })),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: qk.apps.all });
      queryClient.invalidateQueries({ queryKey: qk.stats });
    },
  });
}

export function useUpdateApplication(key: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["ApplicationUpdate"]) =>
      call(api.PATCH("/v1/admin/applications/{key}", { params: { path: { key } }, body })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: qk.apps.all }),
  });
}

export function useMembers(key: string) {
  return useQuery({
    queryKey: qk.apps.members(key),
    queryFn: () => call(api.GET("/v1/admin/applications/{key}/members", { params: { path: { key } } })),
  });
}

// Permissions

export function usePermissions(key: string, includeRetired = false) {
  return useQuery({
    queryKey: qk.apps.permissions(key, includeRetired),
    queryFn: () =>
      call(
        api.GET("/v1/admin/applications/{key}/permissions", {
          params: { path: { key }, query: { include_retired: includeRetired } },
        }),
      ),
  });
}

function useAppInvalidation(key: string) {
  const queryClient = useQueryClient();
  return () => {
    queryClient.invalidateQueries({ queryKey: qk.apps.detail(key) });
    queryClient.invalidateQueries({ queryKey: qk.users.all });
  };
}

export function useCreatePermission(key: string) {
  const invalidate = useAppInvalidation(key);
  return useMutation({
    mutationFn: (body: Schemas["PermissionCreate"]) =>
      call(api.POST("/v1/admin/applications/{key}/permissions", { params: { path: { key } }, body })),
    onSuccess: invalidate,
  });
}

export function useUpdatePermission(key: string) {
  const invalidate = useAppInvalidation(key);
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number } & Schemas["PermissionUpdate"]) =>
      call(
        api.PATCH("/v1/admin/applications/{key}/permissions/{permission_id}", {
          params: { path: { key, permission_id: id } },
          body,
        }),
      ),
    onSuccess: invalidate,
  });
}

export function useRetirePermission(key: string) {
  const invalidate = useAppInvalidation(key);
  return useMutation({
    mutationFn: (id: number) =>
      call(
        api.DELETE("/v1/admin/applications/{key}/permissions/{permission_id}", {
          params: { path: { key, permission_id: id } },
        }),
      ),
    onSuccess: invalidate,
  });
}

// Roles

export function useRoles(key: string) {
  return useQuery({
    queryKey: qk.apps.roles(key),
    queryFn: () => call(api.GET("/v1/admin/applications/{key}/roles", { params: { path: { key } } })),
    enabled: !!key,
  });
}

export function useRole(key: string, id: number | null) {
  return useQuery({
    queryKey: qk.apps.role(key, id ?? 0),
    queryFn: () =>
      call(
        api.GET("/v1/admin/applications/{key}/roles/{role_id}", { params: { path: { key, role_id: id! } } }),
      ),
    enabled: id !== null,
  });
}

export function useCreateRole(key: string) {
  const invalidate = useAppInvalidation(key);
  return useMutation({
    mutationFn: (body: Schemas["RoleCreate"]) =>
      call(api.POST("/v1/admin/applications/{key}/roles", { params: { path: { key } }, body })),
    onSuccess: invalidate,
  });
}

export function useUpdateRole(key: string) {
  const invalidate = useAppInvalidation(key);
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number } & Schemas["RoleUpdate"]) =>
      call(
        api.PATCH("/v1/admin/applications/{key}/roles/{role_id}", {
          params: { path: { key, role_id: id } },
          body,
        }),
      ),
    onSuccess: invalidate,
  });
}

export function useDeleteRole(key: string) {
  const invalidate = useAppInvalidation(key);
  return useMutation({
    mutationFn: (id: number) =>
      call(
        api.DELETE("/v1/admin/applications/{key}/roles/{role_id}", {
          params: { path: { key, role_id: id } },
        }),
      ),
    onSuccess: invalidate,
  });
}

export function useSetRolePermissions(key: string) {
  const invalidate = useAppInvalidation(key);
  return useMutation({
    mutationFn: ({ id, permissionIds }: { id: number; permissionIds: number[] }) =>
      call(
        api.PUT("/v1/admin/applications/{key}/roles/{role_id}/permissions", {
          params: { path: { key, role_id: id } },
          body: { permission_ids: permissionIds },
        }),
      ),
    onSuccess: invalidate,
  });
}
