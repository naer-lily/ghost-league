import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryKey,
} from '@tanstack/react-query'
import { apiFetch, ApiError } from './client'
import type {
  HomeSnapshot,
  Profile,
  ShopItem,
  Standings,
  StarPurchaseResult,
  Status,
} from './types'

export const homeQueryKey: QueryKey = ['home', 'snapshot']
export const shopQueryKey: QueryKey = ['shop', 'catalog']

export interface PurchaseShopItemVariables {
  itemId: string
  requestId: string
}

export function createRequestId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`
}

export async function fetchHomeSnapshot(signal?: AbortSignal): Promise<HomeSnapshot> {
  const [profile, status, standings] = await Promise.all([
    apiFetch<Profile>('/v1/me/profile', signal ? { signal } : {}),
    apiFetch<Status>('/v1/me/status', signal ? { signal } : {}),
    apiFetch<Standings>('/v1/league/standings', signal ? { signal } : {}),
  ])
  return { profile, status, standings }
}

export function useHomeSnapshot() {
  return useQuery({
    queryKey: homeQueryKey,
    queryFn: ({ signal }) => fetchHomeSnapshot(signal),
    staleTime: 15_000,
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    retry: (count, error) =>
      !(error instanceof ApiError && error.status === 401) && count < 1,
  })
}

export function useShopCatalog() {
  return useQuery({
    queryKey: shopQueryKey,
    queryFn: ({ signal }) =>
      apiFetch<ShopItem[]>('/v1/shop', signal ? { signal } : {}),
    staleTime: 10_000,
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    retry: (count, error) =>
      !(error instanceof ApiError && error.status === 401) && count < 1,
  })
}

export function usePurchaseShopItem() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ itemId, requestId }: PurchaseShopItemVariables) =>
      apiFetch<StarPurchaseResult>('/v1/shop/purchase', {
        method: 'POST',
        body: { item_id: itemId, quantity: 1, request_id: requestId },
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: homeQueryKey }),
        queryClient.invalidateQueries({ queryKey: shopQueryKey }),
      ])
    },
  })
}

export function useUpdateIconTheme() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (iconTheme: string) =>
      apiFetch<Profile>('/v1/me/profile', {
        method: 'PATCH',
        body: { icon_theme: iconTheme },
      }),
    onSuccess: (profile) => {
      queryClient.setQueryData<HomeSnapshot>(homeQueryKey, (current) =>
        current ? { ...current, profile } : current,
      )
    },
  })
}
