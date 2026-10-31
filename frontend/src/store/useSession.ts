import { useCallback, useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { isUnauthorized } from '../lib/home'
import { useUiStore } from './useUiStore'

export function useSignOut(): () => void {
  const signOut = useUiStore((state) => state.signOut)
  const queryClient = useQueryClient()
  return useCallback(() => {
    signOut()
    queryClient.clear()
  }, [queryClient, signOut])
}

export function useUnauthorizedSignOut(error: unknown): void {
  const signOut = useSignOut()
  useEffect(() => {
    if (isUnauthorized(error)) signOut()
  }, [error, signOut])
}
