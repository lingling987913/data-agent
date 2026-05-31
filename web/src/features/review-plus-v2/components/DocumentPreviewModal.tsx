'use client'

/**
 * 文档内容预览弹窗
 *
 * 功能:
 *  - 默认渲染 Markdown（prose 样式）
 *  - 双击 → 切换到原文模式（等宽字体）
 *  - 顶部 Tab 也可切换："渲染" / "原文"
 *  - ESC 或点遮罩关闭
 */

import { useState, useEffect, useCallback, useMemo } from 'react'
import MarkdownRenderer from '@aqua/ui-core/typography/MarkdownRenderer'
import { normalizeMaterialPreviewMarkdown } from '@/features/review-plus-shared/utils/materialPreviewMarkdown'

interface DocumentPreviewModalProps {
    /** 文档名称 */
    title: string
    /** 解析后的文本内容 (markdown 或 plain text) */
    content: string
    /** 关闭回调 */
    onClose: () => void
}

export default function DocumentPreviewModal({
    title,
    content,
    onClose,
}: DocumentPreviewModalProps) {
    const [mode, setMode] = useState<'rendered' | 'raw'>('rendered')
    const renderedContent = useMemo(
        () => normalizeMaterialPreviewMarkdown(content),
        [content],
    )

    // ESC 关闭
    const handleKey = useCallback(
        (e: KeyboardEvent) => {
            if (e.key === 'Escape') onClose()
        },
        [onClose],
    )

    useEffect(() => {
        document.addEventListener('keydown', handleKey)
        document.body.style.overflow = 'hidden'
        return () => {
            document.removeEventListener('keydown', handleKey)
            document.body.style.overflow = ''
        }
    }, [handleKey])

    return (
        <div
            className="fixed inset-0 z-[100] flex items-center justify-center"
            onClick={onClose}
        >
            {/* 遮罩 */}
            <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" />

            {/* 弹窗主体 */}
            <div
                className="relative w-[90vw] max-w-4xl max-h-[85vh] flex flex-col rounded-2xl bg-background border border-border/20 shadow-2xl overflow-hidden"
                onClick={(e) => e.stopPropagation()}
            >
                {/* 顶栏 */}
                <div className="flex items-center justify-between px-5 py-3 border-b border-border/15 bg-background/80 backdrop-blur-sm shrink-0">
                    <div className="flex items-center gap-3 min-w-0">
                        <span className="text-base">📄</span>
                        <h3 className="text-[13px] font-semibold text-primary truncate">
                            {title}
                        </h3>
                        <span className="text-[9px] text-muted/40 shrink-0">
                            {content.length.toLocaleString()} 字
                        </span>
                    </div>
                    <div className="flex items-center gap-3 shrink-0">
                        {/* 模式切换 */}
                        <div className="flex rounded-lg border border-border/20 overflow-hidden">
                            <button
                                onClick={() => setMode('rendered')}
                                className={`px-3 py-1 text-[10px] font-medium transition-colors ${
                                    mode === 'rendered'
                                        ? 'bg-primaryAccent/10 text-primaryAccent'
                                        : 'text-muted/60 hover:text-primary/70'
                                }`}
                            >
                                Markdown
                            </button>
                            <button
                                onClick={() => setMode('raw')}
                                className={`px-3 py-1 text-[10px] font-medium transition-colors border-l border-border/20 ${
                                    mode === 'raw'
                                        ? 'bg-primaryAccent/10 text-primaryAccent'
                                        : 'text-muted/60 hover:text-primary/70'
                                }`}
                            >
                                原文
                            </button>
                        </div>
                        <button
                            onClick={onClose}
                            className="w-7 h-7 flex items-center justify-center rounded-lg text-muted/50 hover:text-primary hover:bg-muted/10 transition-colors"
                        >
                            ✕
                        </button>
                    </div>
                </div>

                {/* 提示条 */}
                <div className="px-5 py-1.5 border-b border-border/8 bg-primaryAccent/3 shrink-0">
                    <p className="text-[9px] text-muted/50">
                        {mode === 'rendered'
                            ? '当前为 Markdown 渲染视图 · 双击内容区域切换到原文视图'
                            : '当前为原文视图 · 双击内容区域切换到 Markdown 渲染视图'}
                    </p>
                </div>

                {/* 内容区域 */}
                <div
                    className="flex-1 overflow-auto px-6 py-5"
                    onDoubleClick={() =>
                        setMode(mode === 'rendered' ? 'raw' : 'rendered')
                    }
                >
                    {mode === 'rendered' ? (
                        <div className="max-w-none">
                            <MarkdownRenderer classname="prose-sm prose-headings:text-primary prose-p:text-primary/80 prose-li:text-primary/80 prose-code:text-primaryAccent prose-code:bg-primaryAccent/5 prose-code:rounded prose-code:px-1 prose-table:w-full max-w-none">
                                {renderedContent}
                            </MarkdownRenderer>
                        </div>
                    ) : (
                        <pre className="text-[11px] text-primary/70 font-mono whitespace-pre-wrap break-words leading-relaxed select-all">
                            {content}
                        </pre>
                    )}
                </div>

                {/* 底栏 */}
                <div className="px-5 py-2.5 border-t border-border/15 bg-background/80 flex items-center justify-between shrink-0">
                    <p className="text-[9px] text-muted/40">
                        双击内容区域可切换 Markdown 渲染 / 原文视图
                    </p>
                    <button
                        onClick={onClose}
                        className="px-4 py-1.5 text-[10px] font-medium rounded-lg bg-muted/8 text-primary/70 hover:bg-muted/15 transition-colors"
                    >
                        关闭
                    </button>
                </div>
            </div>
        </div>
    )
}
