import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/api', () => ({
  apiAuth: {
    login: vi.fn(),
    register: vi.fn(),
    getMe: vi.fn(),
  },
}))

import { useAuthStore } from '@/store/auth'

describe('auth store', () => {
  beforeEach(() => {
    window.localStorage.clear()
    setActivePinia(createPinia())
  })

  it('clears only the previous user watchlist cache on logout', async () => {
    const auth = useAuthStore()
    window.localStorage.setItem('stocktrade:watchlist:state:1', '{}')
    window.localStorage.setItem('stocktrade:watchlist:chart-cache:1', '{}')
    window.localStorage.setItem('stocktrade:watchlist:state:2', '{}')
    window.localStorage.setItem('stocktrade:watchlist:chart-cache:2', '{}')

    auth.user = { id: 1 } as any
    auth.logout()

    expect(window.localStorage.getItem('stocktrade:watchlist:state:1')).toBeNull()
    expect(window.localStorage.getItem('stocktrade:watchlist:chart-cache:1')).toBeNull()
    expect(window.localStorage.getItem('stocktrade:watchlist:state:2')).toBe('{}')
    expect(window.localStorage.getItem('stocktrade:watchlist:chart-cache:2')).toBe('{}')
  })
})
