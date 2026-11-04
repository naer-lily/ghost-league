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
  GroupMarket,
  Collection,
  FriendsStandings,
  HistoryFeed,
  HomeSnapshot,
  LeagueFeed,
  Loadout,
  LoadoutField,
  PlaceBetResult,
  Profile,
  RivalCandidateList,
  RivalState,
  ShopItem,
  Standings,
  StarPurchaseResult,
  Status,
  TaskChestResult,
  TaskCompleteResult,
  TaskDefinition,
  TaskDefinitionInput,
  TaskListResponse,
  UserSummary,
} from './types'
import { useUiStore } from '../store/useUiStore'

export const homeQueryKey: QueryKey = ['home', 'snapshot']
export const shopQueryKey: QueryKey = ['shop', 'catalog']
export const collectionQueryKey: QueryKey = ['collection']
export const friendsQueryKey: QueryKey = ['friends', 'standings']
export const historyQueryKey: QueryKey = ['history', 'timeline']
export const feedQueryKey: QueryKey = ['feed', 'league']
export const tasksQueryKey: QueryKey = ['tasks', 'list']
export const taskDefinitionsQueryKey: QueryKey = ['tasks', 'definitions']

export function userProfileQueryKey(userId: string): QueryKey {
  return ['user', userId]
}

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

export function useCollection(enabled = true) {
  return useQuery({
    queryKey: collectionQueryKey,
    queryFn: ({ signal }) =>
      apiFetch<Collection>('/v1/me/collection', signal ? { signal } : {}),
    enabled,
    staleTime: 30_000,
    refetchOnWindowFocus: true,
    retry: (count, error) =>
      !(error instanceof ApiError && error.status === 401) && count < 1,
  })
}

export function useFriendsStandings(enabled = true) {
  return useQuery({
    queryKey: friendsQueryKey,
    queryFn: ({ signal }) =>
      apiFetch<FriendsStandings>(
        '/v1/me/friends/standings',
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
        queryClient.invalidateQueries({ queryKey: collectionQueryKey }),
      ])
    },
  })
}

export interface UpdateLoadoutVariables {
  field: LoadoutField
  value: string | null
  name?: string
}

export function useUpdateLoadout() {
  const queryClient = useQueryClient()
  const notify = useUiStore((state) => state.notify)
  return useMutation<Loadout, Error, UpdateLoadoutVariables>({
    mutationFn: ({ field, value }: UpdateLoadoutVariables) =>
      apiFetch<Loadout>('/v1/me/loadout', {
        method: 'PATCH',
        body: { [field]: value },
      }),
    onSuccess: async (_loadout, variables) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: homeQueryKey }),
        queryClient.invalidateQueries({ queryKey: collectionQueryKey }),
      ])
      const name = variables.name ?? '物品'
      notify(
        variables.value === null ? `${name}已卸下。` : `${name}已装备。`,
      )
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
  paidStake: number
  targetMargin?: number
  market?: GroupMarket
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
    mutationFn: ({
      kind,
      paidStake,
      targetMargin,
      market,
      requestId,
    }: PlaceBetVariables) => {
      const body: Record<string, unknown> = {
        kind,
        paid_stake: paidStake,
        request_id: requestId,
      }
      if (kind === 'group') {
        if (market !== undefined) body.market = market
      } else if (targetMargin !== undefined) {
        body.target_margin = targetMargin
      }
      return apiFetch<PlaceBetResult>('/v1/me/bets', {
        method: 'POST',
        body,
      })
    },
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
              ...(state.bets.groups
                ? { groups: state.bets.groups }
                : {}),
              bets: state.bets,
              bet_options: state.bet_options,
              bet_windows: state.bet_windows,
            }
          : current,
      )
    },
    onSettled: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: rivalQueryKey }),
        queryClient.invalidateQueries({ queryKey: betsQueryKey }),
        queryClient.invalidateQueries({ queryKey: homeQueryKey }),
      ])
    },
  })
}

export function useHistory() {
  return useQuery({
    queryKey: historyQueryKey,
    queryFn: ({ signal }) =>
      apiFetch<HistoryFeed>('/v1/me/history?limit=100', signal ? { signal } : {}),
    staleTime: 15_000,
    refetchOnWindowFocus: true,
    retry: (count, error) =>
      !(error instanceof ApiError && error.status === 401) && count < 1,
  })
}

export function useLeagueFeed(enabled = true) {
  return useQuery({
    queryKey: feedQueryKey,
    queryFn: ({ signal }) =>
      apiFetch<LeagueFeed>(
        '/v1/league/feed?limit=20',
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

export function useUserProfile(userId: string | null) {
  return useQuery({
    queryKey: userProfileQueryKey(userId ?? ''),
    queryFn: ({ signal }) =>
      apiFetch<UserSummary>(
        `/v1/users/${encodeURIComponent(userId ?? '')}`,
        signal ? { signal } : {},
      ),
    enabled: Boolean(userId),
    staleTime: 15_000,
    refetchOnWindowFocus: true,
    retry: (count, error) =>
      !(error instanceof ApiError && error.status === 401) && count < 1,
  })
}

export interface SetFollowVariables {
  userId: string
  follow: boolean
}

export function useSetFollow() {
  const queryClient = useQueryClient()
  return useMutation<UserSummary | null, Error, SetFollowVariables>({
    mutationFn: ({ userId, follow }: SetFollowVariables) =>
      follow
        ? apiFetch<UserSummary>(
            `/v1/me/follows/${encodeURIComponent(userId)}`,
            { method: 'POST' },
          )
        : apiFetch<void>(`/v1/me/follows/${encodeURIComponent(userId)}`, {
            method: 'DELETE',
          }).then(() => null),
    onSuccess: (data, variables) => {
      if (data) {
        queryClient.setQueryData<UserSummary>(
          userProfileQueryKey(variables.userId),
          data,
        )
        return
      }
      queryClient.setQueryData<UserSummary>(
        userProfileQueryKey(variables.userId),
        (current) =>
          current
            ? {
                ...current,
                is_following: false,
                followers_count: Math.max(0, current.followers_count - 1),
              }
            : current,
      )
    },
    onSettled: async (_data, _error, variables) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: feedQueryKey }),
        queryClient.invalidateQueries({ queryKey: friendsQueryKey }),
        queryClient.invalidateQueries({
          queryKey: userProfileQueryKey(variables.userId),
        }),
      ])
    },
  })
}

export function useTasks(enabled = true) {
  return useQuery({
    queryKey: tasksQueryKey,
    queryFn: ({ signal }) =>
      apiFetch<TaskListResponse>('/v1/me/tasks', signal ? { signal } : {}),
    enabled,
    staleTime: 15_000,
    refetchInterval: enabled ? 30_000 : false,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    retry: (count, error) =>
      !(error instanceof ApiError && error.status === 401) && count < 1,
  })
}

export function useTaskDefinitions(enabled = true) {
  return useQuery({
    queryKey: taskDefinitionsQueryKey,
    queryFn: ({ signal }) =>
      apiFetch<TaskDefinition[]>(
        '/v1/me/task-definitions',
        signal ? { signal } : {},
      ),
    enabled,
    staleTime: 15_000,
    refetchOnWindowFocus: true,
    retry: (count, error) =>
      !(error instanceof ApiError && error.status === 401) && count < 1,
  })
}

export interface CompleteTaskVariables {
  taskId: string
  file: File
}

export function useCompleteTask() {
  const queryClient = useQueryClient()
  return useMutation<TaskCompleteResult, Error, CompleteTaskVariables>({
    mutationFn: ({ taskId, file }) => {
      const body = new FormData()
      body.append('file', file)
      return apiFetch<TaskCompleteResult>(
        `/v1/me/tasks/${encodeURIComponent(taskId)}/complete`,
        { method: 'POST', body },
      )
    },
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: tasksQueryKey })
    },
  })
}

export interface RepairTaskVariables {
  date: string
}

export function useRepairTask() {
  const queryClient = useQueryClient()
  return useMutation<unknown, Error, RepairTaskVariables>({
    mutationFn: ({ date }) =>
      apiFetch<unknown>('/v1/me/repair', {
        method: 'POST',
        body: { date, idempotency_key: createRequestId() },
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: tasksQueryKey }),
        queryClient.invalidateQueries({ queryKey: homeQueryKey }),
      ])
    },
  })
}

export function useClaimTaskChest() {
  const queryClient = useQueryClient()
  return useMutation<TaskChestResult, Error, string>({
    mutationFn: (taskId: string) =>
      apiFetch<TaskChestResult>(
        `/v1/me/tasks/${encodeURIComponent(taskId)}/chest`,
        { method: 'POST' },
      ),
    onSettled: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: tasksQueryKey }),
        queryClient.invalidateQueries({ queryKey: homeQueryKey }),
      ])
    },
  })
}

export function useCreateTaskDefinition() {
  const queryClient = useQueryClient()
  return useMutation<TaskDefinition, Error, TaskDefinitionInput>({
    mutationFn: (input: TaskDefinitionInput) =>
      apiFetch<TaskDefinition>('/v1/me/task-definitions', {
        method: 'POST',
        body: input,
      }),
    onSettled: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: taskDefinitionsQueryKey }),
        queryClient.invalidateQueries({ queryKey: tasksQueryKey }),
      ])
    },
  })
}

export interface UpdateTaskDefinitionVariables extends TaskDefinitionInput {
  id: string
}

export function useUpdateTaskDefinition() {
  const queryClient = useQueryClient()
  return useMutation<TaskDefinition, Error, UpdateTaskDefinitionVariables>({
    mutationFn: ({ id, ...input }: UpdateTaskDefinitionVariables) =>
      apiFetch<TaskDefinition>(
        `/v1/me/task-definitions/${encodeURIComponent(id)}`,
        { method: 'PATCH', body: input },
      ),
    onSettled: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: taskDefinitionsQueryKey }),
        queryClient.invalidateQueries({ queryKey: tasksQueryKey }),
      ])
    },
  })
}

export function useDeleteTaskDefinition() {
  const queryClient = useQueryClient()
  return useMutation<void, Error, string>({
    mutationFn: (id: string) =>
      apiFetch<void>(
        `/v1/me/task-definitions/${encodeURIComponent(id)}`,
        { method: 'DELETE' },
      ),
    onSettled: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: taskDefinitionsQueryKey }),
        queryClient.invalidateQueries({ queryKey: tasksQueryKey }),
      ])
    },
  })
}
