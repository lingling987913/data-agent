/**
 * 共享 ECharts 懒初始化模块
 *
 * 统一所有 ECharts 组件注册，避免重复初始化和 Turbopack chunk 冲突。
 * 使用方式: const echarts = await getECharts()
 */

let registered = false
let echartsModule: typeof import('echarts/core') | null = null
let echartsInitPromise: Promise<typeof import('echarts/core')> | null = null

const AQUA_ECHARTS_THEMES = ['tech-blue', 'tech-dark', 'aero-dark', 'aero-ops', 'gov-red', 'gov-warm', 'warm-minimal'] as const

function registerAquaThemes(echarts: typeof import('echarts/core')) {
    const sharedAxis = {
        axisLine: { lineStyle: { color: 'rgba(148, 163, 184, 0.22)' } },
        axisLabel: { color: '#7c8798' },
        splitLine: { lineStyle: { color: 'rgba(148, 163, 184, 0.14)' } },
        axisTick: { show: false },
    }

    const sharedTheme = {
        color: ['#c48968', '#3b82f6', '#608e73', '#c45a4a', '#1e3a5f', '#d6a27a'],
        backgroundColor: 'transparent',
        textStyle: { color: '#5a4a3e' },
        title: { textStyle: { color: '#5a4a3e', fontWeight: 600 } },
        legend: { textStyle: { color: '#857467' } },
        tooltip: {
            backgroundColor: 'rgba(255, 250, 244, 0.96)',
            borderColor: 'rgba(196, 182, 170, 0.22)',
            borderWidth: 1,
            textStyle: { color: '#5a4a3e' },
        },
        categoryAxis: sharedAxis,
        valueAxis: sharedAxis,
    }

    echarts.registerTheme('warm-minimal', sharedTheme)
    echarts.registerTheme('tech-blue', {
        ...sharedTheme,
        color: ['#3b82f6', '#0ea5e9', '#34c759', '#ef4444', '#1e3a5f', '#60a5fa'],
        textStyle: { color: '#1e3a5f' },
        title: { textStyle: { color: '#1e3a5f', fontWeight: 600 } },
        legend: { textStyle: { color: '#64748b' } },
        tooltip: {
            ...sharedTheme.tooltip,
            backgroundColor: 'rgba(255,255,255,0.96)',
            textStyle: { color: '#1e3a5f' },
        },
    })
    echarts.registerTheme('tech-dark', {
        ...sharedTheme,
        color: ['#60a5fa', '#38bdf8', '#4ade80', '#f87171', '#fbbf24', '#a78bfa'],
        textStyle: { color: '#fafafa' },
        title: { textStyle: { color: '#fafafa', fontWeight: 600 } },
        legend: { textStyle: { color: '#a1a1aa' } },
        tooltip: {
            backgroundColor: 'rgba(24, 24, 27, 0.96)',
            borderColor: 'rgba(63, 63, 70, 0.6)',
            borderWidth: 1,
            textStyle: { color: '#fafafa' },
        },
        categoryAxis: {
            ...sharedAxis,
            axisLine: { lineStyle: { color: 'rgba(161, 161, 170, 0.28)' } },
            axisLabel: { color: '#a1a1aa' },
            splitLine: { lineStyle: { color: 'rgba(63, 63, 70, 0.28)' } },
        },
        valueAxis: {
            ...sharedAxis,
            axisLine: { lineStyle: { color: 'rgba(161, 161, 170, 0.28)' } },
            axisLabel: { color: '#a1a1aa' },
            splitLine: { lineStyle: { color: 'rgba(63, 63, 70, 0.28)' } },
        },
    })
    echarts.registerTheme('aero-dark', {
        ...sharedTheme,
        color: ['#4f8ff7', '#b8c0cc', '#2ea043', '#38bdf8', '#f87171', '#f0b429', '#a78bfa'],
        textStyle: { color: '#ffffff' },
        title: { textStyle: { color: '#ffffff', fontWeight: 600 } },
        legend: { textStyle: { color: '#b8c0cc' } },
        tooltip: {
            backgroundColor: 'rgba(10, 10, 10, 0.96)',
            borderColor: 'rgba(42, 45, 51, 0.72)',
            borderWidth: 1,
            textStyle: { color: '#ffffff' },
        },
        categoryAxis: {
            ...sharedAxis,
            axisLine: { lineStyle: { color: 'rgba(184, 192, 204, 0.28)' } },
            axisLabel: { color: '#b8c0cc' },
            splitLine: { lineStyle: { color: 'rgba(42, 45, 51, 0.45)' } },
        },
        valueAxis: {
            ...sharedAxis,
            axisLine: { lineStyle: { color: 'rgba(184, 192, 204, 0.28)' } },
            axisLabel: { color: '#b8c0cc' },
            splitLine: { lineStyle: { color: 'rgba(42, 45, 51, 0.45)' } },
        },
    })
    echarts.registerTheme('aero-ops', {
        ...sharedTheme,
        color: ['#6b8fb5', '#7aa9c4', '#9ca8b4', '#8aa888', '#f0b429', '#e03c3c'],
        textStyle: { color: '#e2e5ea' },
        title: { textStyle: { color: '#e2e5ea', fontWeight: 600 } },
        legend: { textStyle: { color: '#a0a4ab' } },
        tooltip: {
            backgroundColor: 'rgba(45, 48, 54, 0.96)',
            borderColor: 'rgba(74, 77, 84, 0.72)',
            borderWidth: 1,
            textStyle: { color: '#e2e5ea' },
        },
        categoryAxis: {
            ...sharedAxis,
            axisLine: { lineStyle: { color: 'rgba(160, 164, 171, 0.32)' } },
            axisLabel: { color: '#a0a4ab' },
            splitLine: { lineStyle: { color: 'rgba(74, 77, 84, 0.45)' } },
        },
        valueAxis: {
            ...sharedAxis,
            axisLine: { lineStyle: { color: 'rgba(160, 164, 171, 0.32)' } },
            axisLabel: { color: '#a0a4ab' },
            splitLine: { lineStyle: { color: 'rgba(74, 77, 84, 0.45)' } },
        },
    })
    echarts.registerTheme('gov-red', {
        ...sharedTheme,
        color: ['#b41e1e', '#ca8a04', '#3b82f6', '#22c55e', '#7f1d1d', '#f97316'],
        textStyle: { color: '#1f2937' },
        title: { textStyle: { color: '#1f2937', fontWeight: 600 } },
        legend: { textStyle: { color: '#6b7280' } },
        tooltip: {
            backgroundColor: 'rgba(255, 255, 255, 0.97)',
            borderColor: 'rgba(209, 213, 219, 0.8)',
            borderWidth: 1,
            textStyle: { color: '#1f2937' },
        },
    })
    echarts.registerTheme('gov-warm', {
        ...sharedTheme,
        color: ['#667db5', '#a85f55', '#5d9589', '#aa7a3a', '#7e766d', '#d4756e'],
        textStyle: { color: '#24211e' },
        title: { textStyle: { color: '#24211e', fontWeight: 600 } },
        legend: { textStyle: { color: '#7e766d' } },
        tooltip: {
            backgroundColor: 'rgba(255, 253, 250, 0.97)',
            borderColor: 'rgba(83, 70, 55, 0.16)',
            borderWidth: 1,
            textStyle: { color: '#24211e' },
        },
    })
}

export function resolveEChartsTheme(preferredTheme?: string): string | undefined {
    if (preferredTheme && (AQUA_ECHARTS_THEMES as readonly string[]).includes(preferredTheme)) {
        return preferredTheme
    }

    if (typeof document === 'undefined') {
        return undefined
    }

    const pageTheme = document.documentElement.getAttribute('data-theme')
        || document.body.getAttribute('data-theme')

    if (pageTheme && (AQUA_ECHARTS_THEMES as readonly string[]).includes(pageTheme)) {
        return pageTheme
    }

    return undefined
}

export async function initThemedChart(
    container: HTMLDivElement,
    preferredTheme?: string,
    opts?: { renderer?: 'canvas' | 'svg' },
) {
    const echarts = await getECharts()
    const theme = resolveEChartsTheme(preferredTheme)
    return echarts.init(container, theme, opts)
}

/**
 * 懒加载 ECharts core 并按需注册所有常用图表类型和组件。
 * 多次调用安全（只注册一次）。
 */
export async function getECharts() {
    if (registered && echartsModule) {
        return echartsModule
    }

    if (!echartsInitPromise) {
        echartsInitPromise = (async () => {
            if (!echartsModule) {
                echartsModule = await import('echarts/core')
            }

            const [
                { CanvasRenderer },
                {
                    CandlestickChart,
                    BarChart,
                    LineChart,
                    PieChart,
                    ScatterChart,
                    RadarChart,
                    GaugeChart,
                },
                {
                    GridComponent,
                    TooltipComponent,
                    LegendComponent,
                    DataZoomComponent,
                    ToolboxComponent,
                    AxisPointerComponent,
                    MarkLineComponent,
                    MarkPointComponent,
                    TitleComponent,
                    VisualMapComponent,
                },
            ] = await Promise.all([
                import('echarts/renderers'),
                import('echarts/charts'),
                import('echarts/components'),
            ])

            if (!registered) {
                echartsModule.use([
                    CanvasRenderer,
                    CandlestickChart,
                    BarChart,
                    LineChart,
                    PieChart,
                    ScatterChart,
                    RadarChart,
                    GaugeChart,
                    GridComponent,
                    TooltipComponent,
                    LegendComponent,
                    DataZoomComponent,
                    ToolboxComponent,
                    AxisPointerComponent,
                    MarkLineComponent,
                    MarkPointComponent,
                    TitleComponent,
                    VisualMapComponent,
                ])

                registerAquaThemes(echartsModule)

                registered = true
            }

            return echartsModule
        })().catch(error => {
            echartsInitPromise = null
            throw error
        })
    }

    return echartsInitPromise
}
