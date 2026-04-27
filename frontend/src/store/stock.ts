import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { Candidate, AnalysisResult, WatchlistItem, KLineData } from '@/types'
import { apiAnalysis, apiStock, apiWatchlist } from '@/api'

export const useStockStore = defineStore('stock', () => {
  // 明日之星
  const candidates = ref<Candidate[]>([])
  const analysisResults = ref<AnalysisResult[]>([])
  const availableDates = ref<string[]>([])
  const selectedDate = ref<string | null>(null)

  // 重点观察
  const watchlist = ref<WatchlistItem[]>([])

  // 加载日期列表
  async function loadDates() {
    try {
      const data = await apiAnalysis.getDates()
      availableDates.value = data.dates || []
      if (availableDates.value.length > 0 && !selectedDate.value) {
        selectedDate.value = availableDates.value[0]
      }
    } catch (error) {
      console.error('Failed to load dates:', error)
    }
  }

  // 加载候选列表
  async function loadCandidates(date?: string) {
    try {
      const data = await apiAnalysis.getCandidates(date)
      candidates.value = data.candidates || []
      if (data.pick_date) {
        selectedDate.value = data.pick_date
      }
    } catch (error) {
      console.error('Failed to load candidates:', error)
      candidates.value = []
    }
  }

  // 加载分析结果
  async function loadAnalysisResults(date?: string) {
    try {
      const data = await apiAnalysis.getResults(date)
      analysisResults.value = data.results || []
    } catch (error) {
      console.error('Failed to load analysis results:', error)
      analysisResults.value = []
    }
  }

  // 获取 K线数据
  async function getKlineData(code: string, days: number = 120): Promise<KLineData> {
    try {
      return await apiStock.getKline(code, days)
    } catch (error) {
      console.error('Failed to load kline data:', error)
      throw error
    }
  }

  // 加载观察列表
  async function loadWatchlist() {
    try {
      const data = await apiWatchlist.getAll()
      watchlist.value = data.items || []
    } catch (error) {
      console.error('Failed to load watchlist:', error)
      watchlist.value = []
    }
  }

  // 添加到观察列表
  async function addToWatchlist(code: string, reason?: string) {
    try {
      const item = await apiWatchlist.add(code, reason)
      watchlist.value.push(item)
      return item
    } catch (error) {
      console.error('Failed to add to watchlist:', error)
      throw error
    }
  }

  // 从观察列表移除
  async function removeFromWatchlist(id: number) {
    try {
      await apiWatchlist.delete(id)
      watchlist.value = watchlist.value.filter((item) => item.id !== id)
    } catch (error) {
      console.error('Failed to remove from watchlist:', error)
      throw error
    }
  }

  return {
    // 明日之星
    candidates,
    analysisResults,
    availableDates,
    selectedDate,
    loadDates,
    loadCandidates,
    loadAnalysisResults,
    getKlineData,
    // 重点观察
    watchlist,
    loadWatchlist,
    addToWatchlist,
    removeFromWatchlist,
  }
})
