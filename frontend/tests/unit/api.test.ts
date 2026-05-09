import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AxiosInstance } from 'axios'

vi.mock('axios', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  const mockPut = vi.fn()
  const mockDelete = vi.fn()
  const requestUse = vi.fn()
  const responseUse = vi.fn()
  const isCancel = vi.fn((error: unknown) => Boolean((error as { __CANCEL__?: boolean })?.__CANCEL__))

  const instance = {
    interceptors: {
      request: { use: requestUse },
      response: { use: responseUse },
    },
    get: mockGet,
    post: mockPost,
    put: mockPut,
    delete: mockDelete,
  } as unknown as AxiosInstance

  return {
    default: {
      create: vi.fn(() => instance),
      isCancel,
    },
    isCancel,
    __mockGet: mockGet,
    __mockPost: mockPost,
    __mockPut: mockPut,
    __mockDelete: mockDelete,
    __requestUse: requestUse,
    __responseUse: responseUse,
  }
})

import {
  apiAnalysis,
  apiStock,
  apiTasks,
  apiWatchlist,
  isRequestCanceled,
} from '@/api'

const axiosModule = await import('axios')
const mockGet = (axiosModule as any).__mockGet as ReturnType<typeof vi.fn>
const mockPost = (axiosModule as any).__mockPost as ReturnType<typeof vi.fn>
const mockPut = (axiosModule as any).__mockPut as ReturnType<typeof vi.fn>
const requestUse = (axiosModule as any).__requestUse as ReturnType<typeof vi.fn>
const responseUse = (axiosModule as any).__responseUse as ReturnType<typeof vi.fn>
const mockIsCancel = (axiosModule as any).isCancel as ReturnType<typeof vi.fn>

describe('api/index.ts', () => {
  beforeEach(() => {
    mockGet.mockReset()
    mockPost.mockReset()
    mockPut.mockReset()
    mockIsCancel.mockClear()
  })

  it('wraps normal response errors into user-facing Error objects', async () => {
    expect(requestUse).toHaveBeenCalledTimes(1)
    expect(responseUse).toHaveBeenCalledTimes(1)
    const rejectedHandler = responseUse.mock.calls[0][1] as (error: unknown) => Promise<unknown>
    await expect(rejectedHandler({
      response: { data: { detail: '后端异常' } },
      message: 'ignored',
    })).rejects.toThrow('后端异常')
  })

  it('preserves cancellation errors in the response interceptor', async () => {
    expect(responseUse).toHaveBeenCalledTimes(1)
    const rejectedHandler = responseUse.mock.calls[0][1] as (error: unknown) => Promise<unknown>
    const cancelError = { code: 'ERR_CANCELED' }
    await expect(rejectedHandler(cancelError)).rejects.toBe(cancelError)
  })

  it('converts timeout errors into recovery-oriented messages', async () => {
    expect(responseUse).toHaveBeenCalledTimes(1)
    const rejectedHandler = responseUse.mock.calls[0][1] as (error: unknown) => Promise<unknown>
    await expect(rejectedHandler({ code: 'ECONNABORTED', message: 'timeout' })).rejects.toThrow('请求超时')
  })

  it('detects request cancellations from axios cancel markers and error codes', () => {
    expect(isRequestCanceled({ __CANCEL__: true })).toBe(true)
    expect(isRequestCanceled({ code: 'ERR_CANCELED' })).toBe(true)
    expect(isRequestCanceled(new Error('boom'))).toBe(false)
    expect(mockIsCancel).toHaveBeenCalled()
  })

  it('passes optional request options to stock info and kline APIs', async () => {
    const signal = new AbortController().signal
    mockGet
      .mockResolvedValueOnce({ code: '600000' })
      .mockResolvedValueOnce({ items: [], total: 0 })
    mockPost.mockResolvedValue({ daily: [], weekly: [] })

    await apiStock.getInfo('600000', { signal })
    await apiStock.search('浦发银行', 5, { signal })
    await apiStock.getKline('600000', 60, false, { signal })

    expect(mockGet).toHaveBeenCalledWith('/v1/stock/600000', { signal, timeout: 10000 })
    expect(mockGet).toHaveBeenCalledWith('/v1/stock/search', {
      signal,
      timeout: 10000,
      params: { q: '浦发银行', limit: 5 },
    })
    expect(mockPost).toHaveBeenCalledWith(
      '/v1/stock/kline',
      { code: '600000', days: 60, include_weekly: false },
      { signal, timeout: 45000 },
    )
  })

  it('builds analysis requests with params and optional signals', async () => {
    const signal = new AbortController().signal
    mockGet.mockResolvedValue({ candidates: [], results: [] })
    mockPost.mockResolvedValue({ success: true })

    await apiAnalysis.getCandidates('2024-01-15', { signal })
    await apiAnalysis.getResults('2024-01-15', { signal })
    await apiAnalysis.getCurrentHotCandidates('2024-01-15', { signal })
    await apiAnalysis.getCurrentHotResults('2024-01-15', { signal })
    await apiAnalysis.getCurrentHotMiddayStatus({ signal })
    await apiAnalysis.getCurrentHotMiddayCurrent({ signal })
    await apiAnalysis.getDiagnosisHistory('600000', 20, 1, 10, false, { signal })
    await apiAnalysis.analyze('600000', { signal })
    await apiAnalysis.refreshHistory('600000', 30, 1, 10, false, { signal })
    await apiAnalysis.generateCurrentHotMidday()

    expect(mockGet).toHaveBeenNthCalledWith(1, '/v1/analysis/tomorrow-star/candidates', {
      signal,
      timeout: 20000,
      params: { date: '2024-01-15' },
    })
    expect(mockGet).toHaveBeenNthCalledWith(2, '/v1/analysis/tomorrow-star/results', {
      signal,
      timeout: 20000,
      params: { date: '2024-01-15' },
    })
    expect(mockGet).toHaveBeenNthCalledWith(3, '/v1/analysis/current-hot/candidates', {
      signal,
      timeout: 20000,
      params: { date: '2024-01-15' },
    })
    expect(mockGet).toHaveBeenNthCalledWith(4, '/v1/analysis/current-hot/results', {
      signal,
      timeout: 20000,
      params: { date: '2024-01-15' },
    })
    expect(mockGet).toHaveBeenNthCalledWith(5, '/v1/analysis/current-hot/intraday/status', {
      signal,
      timeout: 10000,
    })
    expect(mockGet).toHaveBeenNthCalledWith(6, '/v1/analysis/current-hot/intraday/data', {
      signal,
      timeout: 20000,
    })
    expect(mockGet).toHaveBeenNthCalledWith(7, '/v1/analysis/diagnosis/600000/history', {
      signal,
      timeout: 45000,
      params: { days: 20, page: 1, page_size: 10, refresh: false },
    })
    expect(mockPost).toHaveBeenNthCalledWith(1, '/v1/analysis/diagnosis/analyze', { code: '600000' }, { signal, timeout: 20000 })
    expect(mockPost).toHaveBeenNthCalledWith(
      2,
      '/v1/analysis/diagnosis/600000/generate-history',
      null,
      { signal, timeout: 45000, params: { days: 30, page: 1, page_size: 10, force: false } },
    )
    expect(mockPost).toHaveBeenNthCalledWith(
      3,
      '/v1/analysis/current-hot/intraday/generate',
      null,
      { timeout: 20000 },
    )
  })

  it('passes optional signals to watchlist read/write APIs', async () => {
    const signal = new AbortController().signal
    mockGet.mockResolvedValue({ items: [], analyses: [] })
    mockPost.mockResolvedValue({ success: true })

    await apiWatchlist.getAll({ signal })
    await apiWatchlist.getAnalysis(7, { signal })
    await apiWatchlist.analyze(7, { signal })

    expect(mockGet).toHaveBeenNthCalledWith(1, '/v1/watchlist/', { signal, timeout: 20000 })
    expect(mockGet).toHaveBeenNthCalledWith(2, '/v1/watchlist/7/analysis', { signal, timeout: 20000 })
    expect(mockPost).toHaveBeenCalledWith('/v1/watchlist/7/analyze', null, { signal, timeout: 45000 })
  })

  it('uses current task API signatures, diagnostics endpoint, and timeout policies', async () => {
    const signal = new AbortController().signal
    mockPost.mockResolvedValue({ task: { id: 1 } })
    mockGet.mockResolvedValue({ running: false })
    mockPut.mockResolvedValue({ key: 'x', value: 'y' })

    await apiTasks.startUpdate('quant', true, 3)
    await apiTasks.getIncrementalStatus({ signal })
    await apiTasks.getDiagnostics()

    expect(mockPost).toHaveBeenCalledWith(
      '/v1/tasks/start',
      {
        reviewer: 'quant',
        skip_fetch: true,
        start_from: 3,
        reset_derived_state: false,
      },
      { timeout: 10000 },
    )
    expect(mockGet).toHaveBeenNthCalledWith(1, '/v1/tasks/incremental-status', { signal, timeout: 10000 })
    expect(mockGet).toHaveBeenNthCalledWith(2, '/v1/tasks/diagnostics', { timeout: 10000 })
  })
})
