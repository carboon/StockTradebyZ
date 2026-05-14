import type { ECharts, EChartsCoreOption } from 'echarts/core'
import type { KLineData } from '@/types'

type MovingAverageKey = 'ma5' | 'ma10' | 'ma20' | 'ma60'

type TooltipParam = {
  dataIndex?: number
}

type KLineChartOptionParams = {
  data: KLineData
  highlightedDates?: Iterable<string>
  movingAverages?: MovingAverageKey[]
  extraLegendLabels?: string[]
}

const MOVING_AVERAGE_LABELS: Record<MovingAverageKey, string> = {
  ma5: 'MA5',
  ma10: 'MA10',
  ma20: 'MA20',
  ma60: 'MA60',
}

let chartRuntimePromise: Promise<{ initChart: (dom: HTMLElement) => ECharts }> | null = null

function formatChartNumber(value: number | null | undefined) {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return '-'
  }
  return value.toFixed(2)
}

function buildTooltipFormatter(data: KLineData, movingAverages: MovingAverageKey[]) {
  return (params: TooltipParam[] | undefined) => {
    if (!params || params.length === 0) return ''
    const dataIndex = params[0]?.dataIndex
    if (typeof dataIndex !== 'number') return ''

    const rowData = data.daily[dataIndex]
    if (!rowData) return ''

    let result = `<b>${rowData.date}</b><br/>`
    result += `开盘: ${formatChartNumber(rowData.open)}<br/>`
    result += `收盘: ${formatChartNumber(rowData.close)}<br/>`
    result += `最低: ${formatChartNumber(rowData.low)}<br/>`
    result += `最高: ${formatChartNumber(rowData.high)}<br/>`

    if (typeof rowData.open === 'number' && !Number.isNaN(rowData.open) && rowData.open !== 0
      && typeof rowData.close === 'number' && !Number.isNaN(rowData.close)
    ) {
      const change = ((rowData.close - rowData.open) / rowData.open) * 100
      const changeText = change >= 0 ? '+' : ''
      const changeColor = change >= 0 ? '#ef5350' : '#26a69a'
      result += `涨跌: <span style="color:${changeColor}">${changeText}${change.toFixed(2)}%</span><br/>`
    }

    for (const key of movingAverages) {
      const value = rowData[key]
      if (typeof value === 'number' && !Number.isNaN(value)) {
        result += `${MOVING_AVERAGE_LABELS[key]}: ${value.toFixed(2)}<br/>`
      }
    }

    if (typeof rowData.volume === 'number' && !Number.isNaN(rowData.volume)) {
      result += `成交量: ${(rowData.volume / 10000).toFixed(2)}万`
    }

    return result
  }
}

export function buildKLineChartOption({
  data,
  highlightedDates = [],
  movingAverages = ['ma5', 'ma10', 'ma20'],
  extraLegendLabels = [],
}: KLineChartOptionParams): EChartsCoreOption {
  const dates = data.daily.map((item) => item.date)
  const values = data.daily.map((item) => [item.open, item.close, item.low, item.high])
  const highlightedDateSet = new Set(highlightedDates)
  const volumeBars = data.daily.map((item) => ({
    value: item.volume,
    itemStyle: { color: highlightedDateSet.has(item.date) ? '#ef5350' : '#778899' },
  }))

  const movingAverageSeries = movingAverages.map((key) => ({
    name: MOVING_AVERAGE_LABELS[key],
    type: 'line' as const,
    data: data.daily.map((item) => item[key]),
    smooth: true,
    lineStyle: { width: 1 },
    symbol: 'none',
  }))

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      formatter: buildTooltipFormatter(data, movingAverages),
    },
    legend: {
      data: ['K线', ...movingAverages.map((key) => MOVING_AVERAGE_LABELS[key]), ...extraLegendLabels, '成交量'],
      top: 10,
    },
    grid: [
      { left: '10%', right: '8%', top: '15%', height: '55%' },
      { left: '10%', right: '8%', top: '75%', height: '15%' },
    ],
    xAxis: [
      {
        type: 'category',
        data: dates,
        gridIndex: 0,
        axisLabel: { show: false },
      },
      {
        type: 'category',
        data: dates,
        gridIndex: 1,
        axisLabel: { fontSize: 10 },
      },
    ],
    yAxis: [
      {
        scale: true,
        gridIndex: 0,
        splitLine: { show: true, lineStyle: { color: '#f0f0f0' } },
      },
      {
        scale: true,
        gridIndex: 1,
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: 'K线',
        type: 'candlestick',
        data: values,
        itemStyle: {
          color: '#ef5350',
          color0: '#26a69a',
          borderColor: '#ef5350',
          borderColor0: '#26a69a',
        },
      },
      ...movingAverageSeries,
      {
        name: '成交量',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: volumeBars,
      },
    ],
  }
}

export async function loadKLineChartRuntime() {
  if (!chartRuntimePromise) {
    chartRuntimePromise = (async () => {
      const [{ use, init }, charts, components, renderers] = await Promise.all([
        import('echarts/core'),
        import('echarts/charts'),
        import('echarts/components'),
        import('echarts/renderers'),
      ])

      use([
        charts.BarChart,
        charts.CandlestickChart,
        charts.LineChart,
        components.TooltipComponent,
        components.LegendComponent,
        components.GridComponent,
        renderers.CanvasRenderer,
      ])

      return {
        initChart: (dom: HTMLElement) => init(dom, undefined, { renderer: 'canvas' }),
      }
    })()
  }

  return chartRuntimePromise
}
