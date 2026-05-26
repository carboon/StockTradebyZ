import type { ECharts, EChartsCoreOption } from 'echarts/core'
import type { KLineData, SignalReturnBenchmark, SignalReturnEventPoint, SignalReturnItem } from '@/types'

type MovingAverageKey = 'ma5' | 'ma10' | 'ma20' | 'ma60'

type TooltipParam = {
  dataIndex?: number
}

type KLineChartOptionParams = {
  data: KLineData  // 显示的数据
  fullData?: KLineData  // 完整数据（用于计算高级指标）
  highlightedDates?: Iterable<string>
  movingAverages?: MovingAverageKey[]
  extraLegendLabels?: string[]
  showAdvancedIndicators?: boolean  // 是否显示高级指标（趋势分界线、动能线）
  showTrendBoundary?: boolean  // 是否显示趋势分界线
  showMomentumLine?: boolean  // 是否显示短期动能线
  showVolume?: boolean  // 是否显示成交量
}

type AdvancedIndicators = {
  trendBoundaryLine: number[]  // 趋势分界线（大哥黄线）
  momentumLine: number[]        // 短期动能线（白线）
  crossPoints: Array<{ date: string; index: number; type: 'golden' | 'death' }>  // 金叉死叉点
  yellowDeviation: number       // 黄线偏离率%
  whiteDeviation: number        // 白线偏离率%
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

const MOVING_AVERAGE_COLORS: Record<MovingAverageKey, string> = {
  ma5: '#ffffff',
  ma10: '#ffe066',
  ma20: '#9333ea',
  ma60: '#60a5fa',
}

let chartRuntimePromise: Promise<{ initChart: (dom: HTMLElement) => ECharts }> | null = null

/**
 * 计算简单移动平均线 (SMA)
 */
function calculateSMA(data: number[], period: number): number[] {
  const result: number[] = []
  for (let i = 0; i < data.length; i++) {
    if (i < period - 1) {
      result.push(NaN)
    } else {
      let sum = 0
      for (let j = 0; j < period; j++) {
        sum += data[i - j]
      }
      result.push(sum / period)
    }
  }
  return result
}

/**
 * 计算指数移动平均线 (EMA)
 */
function calculateEMA(data: number[], period: number): number[] {
  const result: number[] = []
  const multiplier = 2 / (period + 1)

  if (data.length === 0) return result

  // 第一个值使用SMA
  result.push(data[0])

  for (let i = 1; i < data.length; i++) {
    const ema = (data[i] - result[i - 1]) * multiplier + result[i - 1]
    result.push(ema)
  }
  return result
}

/**
 * 计算趋势分界线（大哥黄线）= (MA14 + MA28 + MA57 + MA114) / 4
 */
function calculateTrendBoundaryLine(closePrices: number[]): number[] {
  const ma14 = calculateSMA(closePrices, 14)
  const ma28 = calculateSMA(closePrices, 28)
  const ma57 = calculateSMA(closePrices, 57)
  const ma114 = calculateSMA(closePrices, 114)

  const result: number[] = []
  for (let i = 0; i < closePrices.length; i++) {
    const values = [ma14[i], ma28[i], ma57[i], ma114[i]].filter(
      (v): v is number => typeof v === 'number' && !Number.isNaN(v)
    )
    if (values.length === 4) {
      result.push((values[0] + values[1] + values[2] + values[3]) / 4)
    } else {
      result.push(NaN)
    }
  }
  return result
}

/**
 * 计算短期动能线（白线）= EMA(EMA(Close, 10), 10)
 */
function calculateMomentumLine(closePrices: number[]): number[] {
  const firstEMA = calculateEMA(closePrices, 10)
  return calculateEMA(firstEMA, 10)
}

/**
 * 检测金叉死叉点
 */
function detectCrossPoints(
  momentumLine: number[],
  trendBoundaryLine: number[],
  dates: string[]
): Array<{ date: string; index: number; type: 'golden' | 'death' }> {
  const crossPoints: Array<{ date: string; index: number; type: 'golden' | 'death' }> = []

  for (let i = 1; i < dates.length; i++) {
    const prevMomentum = momentumLine[i - 1]
    const currMomentum = momentumLine[i]
    const prevBoundary = trendBoundaryLine[i - 1]
    const currBoundary = trendBoundaryLine[i]

    // 检查数据有效性
    if (
      typeof prevMomentum !== 'number' || typeof currMomentum !== 'number' ||
      typeof prevBoundary !== 'number' || typeof currBoundary !== 'number' ||
      Number.isNaN(prevMomentum) || Number.isNaN(currMomentum) ||
      Number.isNaN(prevBoundary) || Number.isNaN(currBoundary)
    ) {
      continue
    }

    // 金叉：白线上穿黄线
    if (prevMomentum <= prevBoundary && currMomentum > currBoundary) {
      crossPoints.push({ date: dates[i], index: i, type: 'golden' })
    }
    // 死叉：白线下穿黄线
    else if (prevMomentum >= prevBoundary && currMomentum < currBoundary) {
      crossPoints.push({ date: dates[i], index: i, type: 'death' })
    }
  }

  return crossPoints
}

/**
 * 计算高级指标
 */
function calculateAdvancedIndicators(data: KLineData): AdvancedIndicators {
  const closePrices = data.daily.map((item) => item.close).filter(
    (v): v is number => typeof v === 'number' && !Number.isNaN(v)
  )

  if (closePrices.length < 114) {
    // 数据不足，返回空指标
    return {
      trendBoundaryLine: new Array(data.daily.length).fill(NaN),
      momentumLine: new Array(data.daily.length).fill(NaN),
      crossPoints: [],
      yellowDeviation: NaN,
      whiteDeviation: NaN,
    }
  }

  const trendBoundaryLine = calculateTrendBoundaryLine(closePrices)
  const momentumLine = calculateMomentumLine(closePrices)
  const dates = data.daily.map((item) => item.date)

  const crossPoints = detectCrossPoints(momentumLine, trendBoundaryLine, dates)

  // 计算最新日的偏离率
  const lastValidIndex = data.daily.length - 1
  const lastClose = closePrices[lastValidIndex]
  const lastTrendBoundary = trendBoundaryLine[lastValidIndex]
  const lastMomentum = momentumLine[lastValidIndex]

  const yellowDeviation =
    typeof lastTrendBoundary === 'number' && !Number.isNaN(lastTrendBoundary) && lastTrendBoundary !== 0
      ? ((lastClose - lastTrendBoundary) / lastTrendBoundary) * 100
      : NaN

  const whiteDeviation =
    typeof lastMomentum === 'number' && !Number.isNaN(lastMomentum) && lastMomentum !== 0
      ? ((lastClose - lastMomentum) / lastMomentum) * 100
      : NaN

  return {
    trendBoundaryLine,
    momentumLine,
    crossPoints,
    yellowDeviation,
    whiteDeviation,
  }
}

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

function buildTooltipFormatter(
  data: KLineData,
  movingAverages: MovingAverageKey[],
  advancedIndicators: AdvancedIndicators | null = null,
  advancedIndicatorOffset = 0,
) {
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

    // 添加高级指标到tooltip
    if (advancedIndicators) {
      const indicatorIndex = dataIndex + advancedIndicatorOffset
      const trendBoundary = advancedIndicators.trendBoundaryLine[indicatorIndex]
      const momentum = advancedIndicators.momentumLine[indicatorIndex]

      if (typeof trendBoundary === 'number' && !Number.isNaN(trendBoundary)) {
        result += `<span style="color:#FFD700">●</span> 趋势分界: ${trendBoundary.toFixed(2)}<br/>`
      }
      if (typeof momentum === 'number' && !Number.isNaN(momentum)) {
        result += `<span style="color:#FFFFFF">●</span> 短期动能: ${momentum.toFixed(2)}<br/>`
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
  fullData,
  highlightedDates = [],
  movingAverages = ['ma5', 'ma10', 'ma20'],
  extraLegendLabels = [],
  showAdvancedIndicators = false,
  showTrendBoundary = true,
  showMomentumLine = true,
  showVolume = true,
}: KLineChartOptionParams): EChartsCoreOption {
  // 使用完整数据计算高级指标（如果提供）
  const dataForIndicators = fullData || data
  const advancedIndicatorOffset = Math.max(dataForIndicators.daily.length - data.daily.length, 0)
  const dates = data.daily.map((item) => item.date)
  const values = data.daily.map((item) => [item.open, item.close, item.low, item.high])
  const highlightedDateSet = new Set(highlightedDates)
  const volumeBars = data.daily.map((item) => ({
    value: item.volume,
    itemStyle: { color: highlightedDateSet.has(item.date) ? '#ff4d4d' : '#555' },
  }))

  const movingAverageSeries = movingAverages.map((key) => ({
    name: MOVING_AVERAGE_LABELS[key],
    type: 'line' as const,
    data: data.daily.map((item) => item[key]),
    smooth: true,
    lineStyle: { width: 1, color: MOVING_AVERAGE_COLORS[key] },
    symbol: 'none',
  }))

  // 计算高级指标
  let advancedIndicators: AdvancedIndicators | null = null
  let advancedSeries: Array<any> = []
  let crossMarkPoints: Array<any> = []

  if (showAdvancedIndicators && (showTrendBoundary || showMomentumLine)) {
    advancedIndicators = calculateAdvancedIndicators(dataForIndicators)

    // 趋势分界线需要 MA114，所以前 113 天是 NaN
    // 为了让趋势分界线显示尽可能长的有效数据，从有效数据开始的位置截取
    const displayCount = data.daily.length
    const totalCount = dataForIndicators.daily.length
    const startIndex = totalCount - displayCount

    // 找到趋势分界线的第一个有效值位置（需要跳过前 113 个 NaN）
    const trendLineValidStart = 114  // MA114 后开始有值

    // 计算实际应该从哪里开始切片：取 startIndex 和 trendLineValidStart 的最大值
    // 但为了让趋势分界线显示更早的数据，我们从有效数据开始的位置切片
    const actualStartIndex = Math.max(startIndex, trendLineValidStart)

    const slicedTrendLine = advancedIndicators.trendBoundaryLine.slice(actualStartIndex)
    const slicedMomentumLine = advancedIndicators.momentumLine.slice(actualStartIndex)

    // 计算需要填充的前导 NaN 数量（让指标与 displayData 对齐）
    const leadingNaNs = actualStartIndex - startIndex

    // 趋势分界线（大哥黄线）
    if (showTrendBoundary) {
      const trendLineData = new Array(leadingNaNs).fill(NaN).concat(slicedTrendLine)
      advancedSeries.push({
        name: '趋势分界',
        type: 'line',
        data: trendLineData,
        smooth: true,
        lineStyle: { width: 2, color: '#FFD700' },
        symbol: 'none',
        z: 10,
      })
    }

    // 短期动能线（白线）
    if (showMomentumLine) {
      const momentumLineData = new Array(leadingNaNs).fill(NaN).concat(slicedMomentumLine)
      advancedSeries.push({
        name: '短期动能',
        type: 'line',
        data: momentumLineData,
        smooth: true,
        lineStyle: { width: 2, color: '#FFFFFF' },
        symbol: 'none',
        z: 11,
      })
    }

    // 金叉死叉标记点 - 只显示在显示范围内的（仅当两条线都显示时）
    if (showTrendBoundary && showMomentumLine) {
      crossMarkPoints = advancedIndicators.crossPoints
        .filter((point) => point.index >= actualStartIndex)
        .map((point) => {
          const value = slicedMomentumLine[point.index - actualStartIndex]
          return {
            name: point.type === 'golden' ? '金叉' : '死叉',
            coord: [point.date, value],
            value: point.type === 'golden' ? '金' : '死',
            symbol: 'circle',
            symbolSize: 28,
            itemStyle: {
              color: point.type === 'golden' ? '#FFD700' : '#9932CC',
              borderColor: point.type === 'golden' ? '#FFA500' : '#8B008B',
              borderWidth: 2,
            },
            label: {
              show: true,
              fontSize: 11,
              fontWeight: 'bold',
              color: point.type === 'golden' ? '#8B4500' : '#FFFFFF',
              formatter: '{c}',
            },
            z: 20,
          }
        })
    }
  }

  // 构建图例数据
  const legendData = [
    'K线',
    ...movingAverages.map((key) => MOVING_AVERAGE_LABELS[key]),
    ...(showTrendBoundary ? ['趋势分界'] : []),
    ...(showMomentumLine ? ['短期动能'] : []),
    ...extraLegendLabels,
    ...(showVolume ? ['成交量'] : []),
  ]

  // 构建系列数据
  const seriesData = [
    {
      name: 'K线',
      type: 'candlestick',
      data: values,
      itemStyle: {
        color: '#ff4d4d',
        color0: '#2ecc71',
        borderColor: '#ff4d4d',
        borderColor0: '#2ecc71',
      },
      markPoint: crossMarkPoints.length > 0 ? { data: crossMarkPoints } : undefined,
    },
    ...movingAverageSeries,
    ...advancedSeries,
  ]

  // 成交量系列
  if (showVolume) {
    seriesData.push({
      name: '成交量',
      type: 'bar',
      xAxisIndex: 1,
      yAxisIndex: 1,
      data: volumeBars,
      itemStyle: {
        color: '#666',
      },
    })
  }

  return {
    backgroundColor: '#1a1a1a',
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      formatter: buildTooltipFormatter(data, movingAverages, advancedIndicators, advancedIndicatorOffset),
      backgroundColor: 'rgba(30, 30, 30, 0.9)',
      borderColor: '#444',
      textStyle: { color: '#ddd' },
    },
    legend: {
      data: legendData,
      top: 10,
      textStyle: { color: '#ccc' },
    },
    grid: [
      { left: '10%', right: '8%', top: '15%', height: '55%', backgroundColor: 'transparent' },
      { left: '10%', right: '8%', top: '75%', height: '15%', backgroundColor: 'transparent' },
    ],
    xAxis: [
      {
        type: 'category',
        data: dates,
        gridIndex: 0,
        axisLabel: { show: false },
        axisLine: { lineStyle: { color: '#444' } },
      },
      {
        type: 'category',
        data: dates,
        gridIndex: 1,
        axisLabel: { fontSize: 10, color: '#999' },
        axisLine: { lineStyle: { color: '#444' } },
      },
    ],
    yAxis: [
      {
        scale: true,
        gridIndex: 0,
        splitLine: { show: true, lineStyle: { color: '#333' } },
        axisLabel: { color: '#999' },
        axisLine: { lineStyle: { color: '#444' } },
      },
      {
        scale: true,
        gridIndex: 1,
        splitLine: { show: false },
        axisLabel: { color: '#999' },
        axisLine: { lineStyle: { color: '#444' } },
      },
    ],
    series: seriesData,
  }
}

/**
 * 获取高级指标数据（用于显示偏离率）
 */
export function getAdvancedIndicators(data: KLineData): AdvancedIndicators | null {
  const closePrices = data.daily.map((item) => item.close).filter(
    (v): v is number => typeof v === 'number' && !Number.isNaN(v)
  )

  if (closePrices.length < 114) {
    return null
  }

  return calculateAdvancedIndicators(data)
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
