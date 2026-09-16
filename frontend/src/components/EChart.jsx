import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'

// One reusable ECharts wrapper for every chart in the platform.
//
// ECharts draws into a plain DOM element rather than into React's tree, so
// the pattern is always the same: give it a div, create the chart once, call
// setOption when the data changes, dispose when the component goes away.
//
// Sizing is the part that goes wrong in practice. A chart created while its
// grid cell is still 0px wide stays 0px wide, and a chart never learns that
// the sidebar collapsed or a neighbouring widget wrapped. So instead of only
// listening for the window resizing, this watches its *own container* with a
// ResizeObserver and resizes whenever that box changes for any reason.

// The palette comes from the project design tokens. Teal leads; the navies
// follow. Real values, because ECharts cannot read CSS variables.
const CHART_COLORS = ['#5BC0BE', '#3A506B', '#1C2541', '#8FD4D2', '#0B132B']
const AXIS_COLOR = '#3A506B'
const GRID_COLOR = '#E8EDF2'
const FONT = 'system-ui, -apple-system, Segoe UI, Arial, sans-serif'

function EChart({ option, height = 260 }) {
  const containerRef = useRef(null)
  const chartRef = useRef(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return undefined

    const chart = echarts.init(container)
    chartRef.current = chart

    // Resize with the container, not just the window.
    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(container)

    return () => {
      observer.disconnect()
      chart.dispose()
      chartRef.current = null
    }
  }, [])

  useEffect(() => {
    if (!chartRef.current || !option) return
    // notMerge: true, so switching screens never leaves old series behind.
    chartRef.current.setOption({ color: CHART_COLORS, ...option }, true)
  }, [option])

  // min-width: 0 lets the chart shrink inside a grid cell instead of forcing
  // the cell wider and pushing into its neighbours.
  return (
    <div
      ref={containerRef}
      className="echart"
      style={{ width: '100%', minWidth: 0, height: `${height}px` }}
    />
  )
}

/**
 * Build an ECharts option object from widget metadata.
 *
 * The single place that knows how our metadata shape maps onto ECharts. A
 * widget's config carries `categories` and `series` for bar/line charts, or
 * `series` of {name, value} for a pie.
 */
export function buildChartOption(widgetType, config) {
  const base = {
    textStyle: { fontFamily: FONT },
    tooltip: { trigger: widgetType === 'pie' ? 'item' : 'axis' },
  }

  if (widgetType === 'pie') {
    return {
      ...base,
      // A scrolling legend on the right never collides with the chart, however
      // many slices there are; the ring is nudged left to make room for it.
      legend: {
        type: 'scroll',
        orient: 'vertical',
        right: 0,
        top: 'middle',
        textStyle: { color: AXIS_COLOR, fontSize: 12 },
      },
      series: [
        {
          type: 'pie',
          radius: ['42%', '68%'],
          center: ['38%', '50%'],
          data: config.series ?? [],
          label: { show: false },
          emphasis: { label: { show: true, color: AXIS_COLOR } },
        },
      ],
    }
  }

  const axisStyle = {
    axisLine: { lineStyle: { color: GRID_COLOR } },
    axisLabel: { color: AXIS_COLOR, fontSize: 11 },
    splitLine: { lineStyle: { color: GRID_COLOR } },
  }

  return {
    ...base,
    // containLabel keeps long category names inside the box instead of
    // spilling under the neighbouring widget.
    grid: { left: 8, right: 12, top: 20, bottom: 8, containLabel: true },
    xAxis: {
      type: 'category',
      data: config.categories ?? [],
      ...axisStyle,
      // Tilt labels only when they would otherwise overlap.
      axisLabel: { ...axisStyle.axisLabel, interval: 0, rotate: (config.categories?.length ?? 0) > 6 ? 30 : 0 },
    },
    yAxis: { type: 'value', minInterval: 1, ...axisStyle },
    series: (config.series ?? []).map((s) => ({
      name: s.name,
      type: widgetType === 'line' ? 'line' : 'bar',
      data: s.data ?? [],
      smooth: widgetType === 'line',
      barMaxWidth: 36,
      areaStyle: widgetType === 'line' ? { opacity: 0.12 } : undefined,
    })),
  }
}

export default EChart
