/**
 * Auth Store
 * 用户认证状态管理
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { apiAuth } from '@/api'
import type { UserInfo, LoginResponse } from '@/types'

const TOKEN_KEY = 'stocktrade_token'

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
      const res: LoginResponse = await apiAuth.login(username, password)
      token.value = res.access_token
      user.value = res.user
      localStorage.setItem(TOKEN_KEY, res.access_token)
    } finally {
      loading.value = false
    }
  }

  async function register(username: string, password: string, adminWechat: string, displayName?: string): Promise<void> {
    loading.value = true
    try {
      const res: LoginResponse = await apiAuth.register(username, password, adminWechat, displayName)
      token.value = res.access_token
      user.value = res.user
      localStorage.setItem(TOKEN_KEY, res.access_token)
    } finally {
      loading.value = false
    }
  }

  function logout(): void {
    token.value = null
    user.value = null
    localStorage.removeItem(TOKEN_KEY)
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
  }
})
