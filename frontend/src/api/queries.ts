import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryKey,
} from '@tanstack/react-query'
import { apiFetch, ApiError } from './client'
import type { HomeSnapshot, Profile, Standings, Status } from './types'

export const homeQueryKey: QueryKey = ['home', 'snapshot']

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
