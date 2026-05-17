import type { ECharts, EChartsCoreOption } from 'echarts/core'
import type { KLineData, SignalReturnBenchmark, SignalReturnEventPoint, SignalReturnItem } from '@/types'

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

type SignalReturnTooltipParam = {
  axisValue?: string
  componentType?: string
  dataIndex?: number
}

type SignalReturnChartOptionParams = {
  stock: SignalReturnItem
  benchmark?: SignalReturnBenchmark | null
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

function formatPercent(value: number | null | undefined) {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return '-'
  }
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
}

function formatSignalEventLabel(event: SignalReturnEventPoint) {
  if (event.key === 'max_return') return 'Max收'
  if (event.key === 'max_loss') return 'Max亏'
  if (event.key === 'fail') return 'Fail'
  if (event.key === 'fail_sell') return '卖点'
  return event.label
}

function getSignalEventColor(event: SignalReturnEventPoint) {
  if (event.key === 'max_return') return '#ef4444'
  if (event.key === 'max_loss') return '#16a34a'
  if (event.key === 'fail') return '#f59e0b'
  if (event.key === 'fail_sell') return '#7c3aed'
  return '#2563eb'
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

function buildSignalReturnTooltipFormatter(stock: SignalReturnItem, benchmarkLabel: string) {
  const eventMap = new Map<string, SignalReturnEventPoint[]>()
  for (const event of stock.events || []) {
    const existing = eventMap.get(event.trade_date) || []
    existing.push(event)
    eventMap.set(event.trade_date, existing)
  }

  return (params: SignalReturnTooltipParam[] | SignalReturnTooltipParam | undefined) => {
    const paramList = Array.isArray(params) ? params : params ? [params] : []
    if (paramList.length === 0) return ''

    const pointDate = paramList[0]?.axisValue
    if (!pointDate) return ''
    const point = stock.timeline.find((item) => item.trade_date === pointDate)
    if (!point) return ''

    let result = `<b>${point.trade_date}</b><br/>`
    result += `${stock.name || stock.code}: <span style="color:#d84b31">${formatPercent(point.return_pct)}</span>`
    if (typeof point.close_price === 'number') {
      result += ` / 收盘 ${point.close_price.toFixed(2)}`
    }
    result += '<br/>'

    if (typeof point.benchmark_return_pct === 'number') {
      result += `${benchmarkLabel}: <span style="color:#4463c2">${formatPercent(point.benchmark_return_pct)}</span>`
      if (typeof point.benchmark_close === 'number') {
        result += ` / 点位 ${point.benchmark_close.toFixed(2)}`
      }
      result += '<br/>'
    }

    const events = eventMap.get(point.trade_date) || []
    if (events.length > 0) {
      result += '<br/><b>关键点</b><br/>'
      result += events.map((event) => {
        const priceText = typeof event.price === 'number' ? event.price.toFixed(2) : '-'
        const returnText = formatPercent(event.return_pct)
        return `${event.label}: 价格 ${priceText} / 幅度 ${returnText}`
      }).join('<br/>')
    }

    return result
  }
}

export function buildSignalReturnChartOption({
  stock,
  benchmark,
}: SignalReturnChartOptionParams): EChartsCoreOption {
  const dates = stock.timeline.map((item) => item.trade_date)
  const stockReturns = stock.timeline.map((item) => item.return_pct)
  const benchmarkReturns = stock.timeline.map((item) => item.benchmark_return_pct)
  const benchmarkLabel = benchmark?.name || '大A基准'
  const hasBenchmark = benchmarkReturns.some((value) => typeof value === 'number' && !Number.isNaN(value))

  const yValues = [
    ...stockReturns,
    ...benchmarkReturns,
    ...(stock.events || []).map((item) => item.return_pct),
  ].filter((value): value is number => typeof value === 'number' && !Number.isNaN(value))
  const yMin = yValues.length > 0 ? Math.min(...yValues) : -5
  const yMax = yValues.length > 0 ? Math.max(...yValues) : 5
  const yPadding = Math.max((yMax - yMin) * 0.18, 2)

  const markPointData = (stock.events || [])
    .filter((event) => typeof event.return_pct === 'number' && !Number.isNaN(event.return_pct))
    .map((event) => ({
      name: event.label,
      coord: [event.trade_date, event.return_pct as number],
      value: event.return_pct,
      symbol: 'circle',
      symbolSize: 24,
      itemStyle: { color: getSignalEventColor(event) },
      label: {
        show: true,
        formatter: formatSignalEventLabel(event),
        color: '#1f2937',
        fontSize: 10,
        fontWeight: 600,
        lineHeight: 12,
      },
    }))

  return {
    animationDuration: 400,
    color: ['#d84b31', '#4463c2'],
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'line' },
      formatter: buildSignalReturnTooltipFormatter(stock, benchmarkLabel),
    },
    legend: {
      top: 8,
      data: [stock.name || stock.code, ...(hasBenchmark ? [benchmarkLabel] : [])],
    },
    grid: {
      left: 60,
      right: 24,
      top: 48,
      bottom: 54,
    },
    xAxis: {
      type: 'category',
      data: dates,
      boundaryGap: false,
      axisLabel: {
        color: '#6b7280',
        formatter: (value: string) => value.slice(5),
      },
      axisLine: {
        lineStyle: { color: '#d1d5db' },
      },
    },
    yAxis: {
      type: 'value',
      min: Math.floor((yMin - yPadding) * 100) / 100,
      max: Math.ceil((yMax + yPadding) * 100) / 100,
      axisLabel: {
        color: '#6b7280',
        formatter: (value: number) => `${value.toFixed(0)}%`,
      },
      splitLine: {
        lineStyle: { color: '#eef2f7' },
      },
    },
    series: [
      {
        name: stock.name || stock.code,
        type: 'line',
        data: stockReturns,
        smooth: false,
        symbol: 'circle',
        symbolSize: 7,
        connectNulls: false,
        lineStyle: {
          width: 3,
          color: '#d84b31',
        },
        itemStyle: {
          color: '#d84b31',
        },
        markPoint: {
          data: markPointData,
        },
      },
      ...(hasBenchmark
        ? [{
            name: benchmarkLabel,
            type: 'line' as const,
            data: benchmarkReturns,
            smooth: false,
            symbol: 'none',
            connectNulls: false,
            lineStyle: {
              width: 2,
              type: 'dashed' as const,
              color: '#4463c2',
            },
            itemStyle: {
              color: '#4463c2',
            },
          }]
        : []),
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
        components.MarkPointComponent,
        renderers.CanvasRenderer,
      ])

      return {
        initChart: (dom: HTMLElement) => init(dom, undefined, { renderer: 'canvas' }),
      }
    })()
  }

  return chartRuntimePromise
}
