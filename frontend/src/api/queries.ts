import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryKey,
} from '@tanstack/react-query'
import { apiFetch, ApiError } from './client'
import type {
  BetKind,
  BetsState,
  HomeSnapshot,
  PlaceBetResult,
  Profile,
  RivalCandidateList,
  RivalState,
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

export const rivalQueryKey: QueryKey = ['rival', 'state']
export const rivalCandidatesQueryKey: QueryKey = ['rival', 'candidates']
export const betsQueryKey: QueryKey = ['bets', 'state']

export interface SelectRivalVariables {
  rivalId: string
  requestId: string
}

export interface PlaceBetVariables {
  kind: BetKind
  stake?: number
  targetMargin?: number
  requestId: string
}

export function useRival() {
  return useQuery({
    queryKey: rivalQueryKey,
    queryFn: ({ signal }) =>
      apiFetch<RivalState>('/v1/me/rival', signal ? { signal } : {}),
    staleTime: 15_000,
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    retry: (count, error) =>
      !(error instanceof ApiError && error.status === 401) && count < 1,
  })
}

export function useRivalCandidates(enabled: boolean) {
  return useQuery({
    queryKey: rivalCandidatesQueryKey,
    queryFn: ({ signal }) =>
      apiFetch<RivalCandidateList>(
        '/v1/me/rival/candidates',
        signal ? { signal } : {},
      ),
    enabled,
    staleTime: 15_000,
    refetchInterval: enabled ? 30_000 : false,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    retry: (count, error) =>
      !(error instanceof ApiError && error.status === 401) && count < 1,
  })
}

export function useBets(enabled = true) {
  return useQuery({
    queryKey: betsQueryKey,
    queryFn: ({ signal }) =>
      apiFetch<BetsState>('/v1/me/bets', signal ? { signal } : {}),
    enabled,
    staleTime: 10_000,
    refetchInterval: enabled ? 30_000 : false,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    retry: (count, error) =>
      !(error instanceof ApiError && error.status === 401) && count < 1,
  })
}

export function useSelectRival() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ rivalId, requestId }: SelectRivalVariables) =>
      apiFetch<RivalState>('/v1/me/rival/select', {
        method: 'POST',
        body: { rival_id: rivalId, request_id: requestId },
      }),
    onSuccess: (state) => {
      queryClient.setQueryData<RivalState>(rivalQueryKey, state)
    },
    onSettled: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: rivalQueryKey }),
        queryClient.invalidateQueries({ queryKey: rivalCandidatesQueryKey }),
        queryClient.invalidateQueries({ queryKey: betsQueryKey }),
      ])
    },
  })
}

export function usePlaceBet() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ kind, stake, targetMargin, requestId }: PlaceBetVariables) =>
      apiFetch<PlaceBetResult>('/v1/me/bets', {
        method: 'POST',
        body:
          kind === 'daily'
            ? {
                kind,
                target_margin: targetMargin,
                request_id: requestId,
              }
            : { kind, stake, request_id: requestId },
      }),
    onSuccess: (result) => {
      const state = result.state
      queryClient.setQueryData<RivalState>(rivalQueryKey, state)
      queryClient.setQueryData<BetsState>(betsQueryKey, (current) =>
        current
          ? {
              ...current,
              server_now: state.server_now,
              weekly: state.bets.weekly,
              daily: state.bets.daily,
              group: state.bets.group,
              bets: state.bets,
              bet_windows: state.bet_windows,
            }
          : current,
      )
    },
    onSettled: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: rivalQueryKey }),
        queryClient.invalidateQueries({ queryKey: betsQueryKey }),
      ])
    },
  })
}
