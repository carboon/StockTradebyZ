import { describe, expect, it } from 'vitest'
import { buildKLineChartOption } from '@/utils/klineChart'
import type { KLineData } from '@/types'

function buildKline(days: number): KLineData {
  return {
    code: '000001',
    name: '平安银行',
    daily: Array.from({ length: days }, (_, index) => ({
      date: `2024-01-${String((index % 30) + 1).padStart(2, '0')}`,
      open: 10 + index * 0.12,
      close: 10.15 + index * 0.12,
      low: 9.9 + index * 0.12,
      high: 10.35 + index * 0.12,
      volume: 100000 + index * 500,
      ma5: 10 + index * 0.11,
      ma10: 9.95 + index * 0.11,
      ma20: 9.9 + index * 0.1,
      ma60: 9.7 + index * 0.08,
    })),
    weekly: [],
  }
}

describe('klineChart tooltip alignment', () => {
  it('reads advanced indicator values from the displayed slice instead of the full-data origin', () => {
    const fullData = buildKline(180)
    const displayData = {
      ...fullData,
      daily: fullData.daily.slice(-30),
    }

    const option = buildKLineChartOption({
      data: displayData,
      fullData,
      movingAverages: ['ma5', 'ma10', 'ma20', 'ma60'],
      showAdvancedIndicators: true,
      showTrendBoundary: true,
      showMomentumLine: true,
      showVolume: true,
    }) as any

    const formatter = option.tooltip?.formatter as ((params: Array<{ dataIndex: number }>) => string)
    const series = option.series as Array<{ name: string; data: number[] }>
    const trendBoundarySeries = series.find((item) => item.name === '趋势分界')
    const momentumSeries = series.find((item) => item.name === '短期动能')

    expect(typeof formatter).toBe('function')
    expect(trendBoundarySeries?.data?.[0]).not.toBeNaN()
    expect(momentumSeries?.data?.[0]).not.toBeNaN()

    const html = formatter([{ dataIndex: 0 }])

    expect(html).toContain(`趋势分界: ${trendBoundarySeries?.data?.[0].toFixed(2)}`)
    expect(html).toContain(`短期动能: ${momentumSeries?.data?.[0].toFixed(2)}`)
  })
})
