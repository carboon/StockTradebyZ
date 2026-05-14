/**
 * Auth Store
 * 用户认证状态管理
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { apiAuth } from '@/api'
import type { UserInfo, LoginResponse } from '@/types'

const TOKEN_KEY = 'stocktrade_token'
const WATCHLIST_STATE_KEY_PREFIX = 'stocktrade:watchlist:state'
const WATCHLIST_CHART_CACHE_KEY_PREFIX = 'stocktrade:watchlist:chart-cache:v2'

export const useAuthStore = defineStore('auth', () => {
  // --- State ---
  const token = ref<string | null>(localStorage.getItem(TOKEN_KEY))
  const user = ref<UserInfo | null>(null)
  const loading = ref(false)

  // --- Getters ---
  const isAuthenticated = computed(() => !!token.value && !!user.value)
  const isAdmin = computed(() => user.value?.role === 'admin')

  // --- Actions ---

  async function login(username: string, password: string): Promise<void> {
    loading.value = true
    try {
      const previousUserId = user.value?.id ?? null
      const res: LoginResponse = await apiAuth.login(username, password)
      token.value = res.access_token
      user.value = res.user
      localStorage.setItem(TOKEN_KEY, res.access_token)
      if (previousUserId !== null && previousUserId !== res.user.id) {
        clearScopedLocalStorage(previousUserId)
      }
    } finally {
      loading.value = false
    }
  }

  async function register(username: string, password: string, adminWechat: string, displayName?: string): Promise<void> {
    loading.value = true
    try {
      const previousUserId = user.value?.id ?? null
      const res: LoginResponse = await apiAuth.register(username, password, adminWechat, displayName)
      token.value = res.access_token
      user.value = res.user
      localStorage.setItem(TOKEN_KEY, res.access_token)
      if (previousUserId !== null && previousUserId !== res.user.id) {
        clearScopedLocalStorage(previousUserId)
      }
    } finally {
      loading.value = false
    }
  }

  function logout(): void {
    const previousUserId = user.value?.id ?? null
    token.value = null
    user.value = null
    localStorage.removeItem(TOKEN_KEY)
    if (previousUserId !== null) {
      clearScopedLocalStorage(previousUserId)
    }
  }

  async function fetchMe(): Promise<void> {
    if (!token.value) return
    try {
      user.value = await apiAuth.getMe()
    } catch {
      // token 无效，清除登录状态
      logout()
    }
  }

  function loadFromStorage(): void {
    const saved = localStorage.getItem(TOKEN_KEY)
    if (saved) {
      token.value = saved
    }
  }

  function clearScopedLocalStorage(userId?: number | null): void {
    if (typeof window === 'undefined' || typeof window.localStorage === 'undefined') return

    const keysToRemove: string[] = []
    const statePrefix = userId != null ? `${WATCHLIST_STATE_KEY_PREFIX}:${userId}` : `${WATCHLIST_STATE_KEY_PREFIX}:`
    const chartPrefix = userId != null ? `${WATCHLIST_CHART_CACHE_KEY_PREFIX}:${userId}` : `${WATCHLIST_CHART_CACHE_KEY_PREFIX}:`
    for (let index = 0; index < localStorage.length; index += 1) {
      const key = localStorage.key(index)
      if (!key) continue
      if (key.startsWith(statePrefix) || key.startsWith(chartPrefix)) {
        keysToRemove.push(key)
      }
    }

    keysToRemove.forEach((key) => localStorage.removeItem(key))
  }

  return {
    token,
    user,
    loading,
    isAuthenticated,
    isAdmin,
    login,
    register,
    logout,
    fetchMe,
    loadFromStorage,
    clearScopedLocalStorage,
  }
})
