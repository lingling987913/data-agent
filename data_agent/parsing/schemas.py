"""
文档解析数据模型

包含两代数据结构:
- 第一代 (保留, deprecated): ReviewDocumentChunk, StageDocumentContext — 基于固定长度切块
- 第二代 (新增): DocumentSection, DocumentEvidence, ReviewEvidence — 基于章节树 + 证据池
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


# ══════════════════════════════════════════════
#  基础解析块
# ══════════════════════════════════════════════


class ParsedDocumentBlock(BaseModel):
    block_id: str
    block_type: str  # heading / paragraph / table / list / figure_caption / page_break / formula / figure / table_row
    text: str = ""
    level: int | None = None
    page_hint: int | None = None
    order_index: int
    # --- MinerU 扩展字段 (Phase 1 新增, 全部可选 + 默认值, 向后兼容) ---
    confidence: float | None = None      # 解析置信度 0.0-1.0
    bbox: list[float] | None = None      # 边界框 [x0, y0, x1, y1]
    angle: int | None = None             # MinerU 块旋转角度 (0/90/180/270)
    children: list["ParsedDocumentBlock"] = Field(default_factory=list)  # 子块 (表格行等)
    formula_latex: str | None = None     # 公式 LaTeX 表达式
    table_markdown: str | None = None    # 表格 Markdown 原文
    caption: str | None = None           # 图表标题
    image_ref: str | None = None         # 裁剪图或 MinerU 图本地路径
    vision_description: str | None = None  # VLM 生成的图片描述
    # --- 结构化自愈元数据 (Task 1, 全部 Optional + 默认值) ---
    format_damage_types: list[str] = Field(default_factory=list)
    self_healed: bool = False


# Pydantic V2 自引用字段需要 model_rebuild
ParsedDocumentBlock.model_rebuild()


class ParseCalibrationRecord(BaseModel):
    """解析合理性校准记录。

    仅用于标记可疑解析结果和建议修正，不直接改写原始 block 文本。
    """

    block_id: str
    page_hint: int | None = None
    issue_type: Literal[
        "numeric_outlier",
        "symbol_confusion",
        "unit_mismatch",
        "context_conflict",
        "other",
    ] = "other"
    severity: Literal["info", "warning", "critical"] = "warning"
    original_text: str = ""
    suggested_text: str = ""
    reason: str = ""
    evidence: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    status: Literal["needs_review", "suggested", "dismissed"] = "needs_review"
    model_id: str = ""
    latency_ms: int = 0


class ParsedDocument(BaseModel):
    document_id: str
    file_name: str
    file_type: str
    parser_name: str
    parse_status: str  # ok / degraded / failed
    blocks: list[ParsedDocumentBlock] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    structuring_mode: str | None = None
    structuring_warnings: list[str] = Field(default_factory=list)
    parser_fallback_logs: list[dict] = Field(default_factory=list)
    self_healing_records: list[dict] = Field(default_factory=list)
    calibration_records: list[ParseCalibrationRecord] = Field(default_factory=list)
    chapter_tree: list[dict] = Field(default_factory=list)  # 章节树 {title, level, block_ids, children}
    enhancement_log: list[dict] = Field(default_factory=list)  # LLM 增强步骤日志


# ══════════════════════════════════════════════
#  第一代: 固定长度切块 (deprecated, 保留向后兼容)
# ══════════════════════════════════════════════


class ReviewDocumentChunk(BaseModel):
    """[DEPRECATED] 固定长度文档切块 — 被 DocumentSection 替代。
    保留以兼容现有 AD/AC 子工作流和 stage_context_map 路径。
    """
    chunk_id: str
    document_id: str
    source_file_name: str
    section_title: str = ""
    section_path: list[str] = Field(default_factory=list)
    chunk_text: str
    order_index: int
    page_start: int | None = None
    page_end: int | None = None
    block_ids: list[str] = Field(default_factory=list)


class StageDocumentContext(BaseModel):
    """[DEPRECATED] 阶段级文档匹配上下文 — 保留向后兼容。"""
    stage_key: str
    matched_chunk_ids: list[str] = Field(default_factory=list)
    matched_section_titles: list[str] = Field(default_factory=list)
    coverage_score: float = 0.0
    missing_expected_topics: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


# ══════════════════════════════════════════════
#  第二代: 章节树 + 证据池
# ══════════════════════════════════════════════


class DocumentSection(BaseModel):
    """章节树节点 — 替代 ReviewDocumentChunk 作为审查单元的定位基础。

    支持两种标题识别方式:
      1. Word Heading 样式 (Heading 1 / Heading 2 / Heading 3)
      2. 编号标题 (1, 1.1, 3.2.4 等)

    text 字段包含该章节下所有段落和表格的拼接全文(不含子章节)。
    """
    section_id: str
    title: str
    level: int                                  # 1=一级标题, 2=二级标题, ...
    number: str = ""                            # 编号, 如 "3.2.1"
    parent_section_id: str | None = None
    start_block_index: int
    end_block_index: int
    text: str = ""                              # 本章节直属段落/表格的全文拼接
    source_file_name: str = ""                  # 该切片归属的原始文档名
    children_ids: list[str] = Field(default_factory=list)
    page_hint_start: int | None = None
    page_hint_end: int | None = None


class DocumentTocEntry(BaseModel):
    """目录项元数据。

    目录文本本身不参与正文证据抽取，但可作为章节识别的辅助索引。
    """
    entry_id: str
    title: str
    raw_text: str = ""
    number: str = ""
    level: int = 1
    page_number: int | None = None
    source_file_name: str = ""
    matched_section_id: str | None = None


class DocumentEvidence(BaseModel):
    """文档主证据 — 从章节中提取, evidence_layer 固定为 primary。

    source_type 取值:
      - section_summary: 章节摘要
      - paragraph_excerpt: 段落摘录
      - table_text: 表格文字 + 前后上下文
    """
    evidence_id: str
    evidence_layer: str = "primary"
    source_type: str                            # section_summary / paragraph_excerpt / table_text
    section_id: str
    block_ids: list[str] = Field(default_factory=list)
    source_file_name: str = ""
    excerpt: str = ""
    summary: str = ""
    matched_keywords: list[str] = Field(default_factory=list)


class ReviewEvidence(BaseModel):
    """统一证据模型 — 合并主证据(primary)和旁证(supporting)。

    evidence_layer:
      - primary: 来自上传文档本身 (DocumentEvidence 转换而来)
      - supporting: 来自 RAGFlow / 知识库 API / Neo4j

    source_type:
      - document_section / paragraph / table (主证据)
      - ragflow / knowledge_api / neo4j (旁证)
    """
    evidence_id: str
    evidence_layer: str                         # primary / supporting
    evidence_role: str = "claim"               # claim / normative_basis / validation_support
    source_type: str
    source_ref: str = ""
    unit_key: str = ""
    section_id: str = ""
    block_ids: list[str] = Field(default_factory=list)
    excerpt: str = ""
    summary: str = ""
    matched_keywords: list[str] = Field(default_factory=list)


class TemplateGatekeepingResult(BaseModel):
    """单个审查单元的模板结构准入结果。

    status:
      - pass: 章节存在且正文充足
      - pass_with_note: 标题不标准但关键词命中等价内容
      - soft_fail: 有章节但正文过短 / 缺少子章节
      - hard_fail: 缺失一级主章节
    """
    unit_key: str
    unit_name: str = ""
    status: str = "pass"
    matched_section_ids: list[str] = Field(default_factory=list)
    total_text_length: int = 0
    issues: list[str] = Field(default_factory=list)
    summary: str = ""


class ExtractedParameter(BaseModel):
    """从送审文档中抽取的工程参数。"""
    parameter_id: str = ""
    name: str = ""
    normalized_name: str = ""
    value: float | None = None
    raw_value: str = ""
    unit: str = ""
    comparator: str = ""
    source_section_id: str = ""
    source_evidence_id: str = ""
    block_ids: list[str] = Field(default_factory=list)
    source_text: str = ""
    confidence: float = 0.0
    # 审查断点2：上下文标签用于工况/阶段匹配，如 ["稳态", "机动", "太阳敏感器", "星敏感器"]
    context_tags: list[str] = Field(default_factory=list)


class ExtractedTechnicalObject(BaseModel):
    """从送审文档中抽取的技术对象候选。"""
    object_id: str = ""
    name: str = ""
    normalized_name: str = ""
    object_type: str = ""
    source_section_id: str = ""
    source_evidence_id: str = ""
    block_ids: list[str] = Field(default_factory=list)
    source_text: str = ""
    confidence: float = 0.0


class TraceLinkCandidate(BaseModel):
    """需求、设计、验证之间的轻量追踪候选。"""
    link_id: str = ""
    source_id: str = ""
    target_id: str = ""
    link_type: str = ""
    source_section_id: str = ""
    source_evidence_id: str = ""
    block_ids: list[str] = Field(default_factory=list)
    source_text: str = ""
    confidence: float = 0.0


class RequirementItem(BaseModel):
    """需求候选项。"""
    requirement_id: str = ""
    title: str = ""
    text: str = ""
    normalized_metric: str = ""
    source_section_id: str = ""
    source_evidence_id: str = ""
    block_ids: list[str] = Field(default_factory=list)
    source_text: str = ""
    confidence: float = 0.0


class DesignElement(BaseModel):
    """设计项候选。"""
    design_id: str = ""
    name: str = ""
    design_type: str = ""
    normalized_name: str = ""
    source_section_id: str = ""
    source_evidence_id: str = ""
    block_ids: list[str] = Field(default_factory=list)
    source_text: str = ""
    confidence: float = 0.0


class VerificationItem(BaseModel):
    """验证项候选。"""
    verification_id: str = ""
    title: str = ""
    # 审查断点6：验证项显式记录方法、用例、状态和结果。
    method: Literal["simulation", "test", "analysis", "inspection"] = "analysis"
    test_case_id: str = ""
    status: Literal["planned", "in_progress", "completed"] = "planned"
    pass_fail: Literal["pass", "fail", "partial", "waived"] = "partial"
    normalized_metric: str = ""
    source_section_id: str = ""
    source_evidence_id: str = ""
    block_ids: list[str] = Field(default_factory=list)
    source_text: str = ""
    confidence: float = 0.0

    @field_validator("method", mode="before")
    @classmethod
    def _normalize_method(cls, value):
        mapping = {
            "仿真": "simulation",
            "试验": "test",
            "测试": "test",
            "分析": "analysis",
            "校核": "inspection",
            "检查": "inspection",
        }
        return mapping.get(value, value or "analysis")

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, value):
        return value or "planned"

    @field_validator("pass_fail", mode="before")
    @classmethod
    def _normalize_pass_fail(cls, value):
        return value or "partial"


class TraceLink(BaseModel):
    """需求、设计、验证之间的轻量追踪链接。"""
    link_id: str = ""
    source_id: str = ""
    target_id: str = ""
    link_type: str = ""  # requirement_to_design / requirement_to_verification / design_to_verification
    status: str = "candidate"
    # 审查断点6：候选 RTM 链接支持人工确认/驳回追踪。
    confirmed: bool = False
    confirmed_by: str = ""
    confirmed_at: datetime | None = None
    rejection_reason: str = ""
    source_section_id: str = ""
    source_evidence_id: str = ""
    block_ids: list[str] = Field(default_factory=list)
    source_text: str = ""
    confidence: float = 0.0


class TraceabilityMatrixSummary(BaseModel):
    """轻量 RTM 汇总与完整性检查结果。"""
    requirement_count: int = 0
    design_element_count: int = 0
    verification_item_count: int = 0
    link_count: int = 0
    confirmed_link_count: int = 0
    candidate_link_count: int = 0
    requirement_decomposition_coverage: float = 0.0
    verification_result_coverage: float = 0.0
    verification_pass_coverage: float = 0.0
    verification_completeness: dict = Field(default_factory=dict)
    uncovered_requirement_count: int = 0
    orphan_design_count: int = 0
    orphan_verification_count: int = 0
    no_verification_requirement_ids: list[str] = Field(default_factory=list)
    design_items_without_source_ids: list[str] = Field(default_factory=list)
    orphan_verification_ids: list[str] = Field(default_factory=list)
    metric_conflicts: list[dict] = Field(default_factory=list)


class DocumentAsset(BaseModel):
    asset_id: str = ""
    source_file_name: str = ""
    asset_type: str = "source_file"
    uri: str = ""
    mime_type: str = ""
    metadata: dict = Field(default_factory=dict)


class DocumentPage(BaseModel):
    page_id: str = ""
    source_file_name: str = ""
    page_number: int = 1
    page_type: str = "page"
    width: float | None = None
    height: float | None = None
    rotation: float = 0.0
    quality_score: float | None = None
    metadata: dict = Field(default_factory=dict)


class LayoutBlock(BaseModel):
    layout_block_id: str = ""
    source_block_id: str = ""
    source_file_name: str = ""
    page_id: str = ""
    block_type: str = "paragraph"
    text: str = ""
    reading_order: int = 0
    bbox: list[float] | None = None
    confidence: float | None = None
    parser_name: str = ""
    metadata: dict = Field(default_factory=dict)


class VisualElement(BaseModel):
    visual_id: str = ""
    source_file_name: str = ""
    source_block_id: str = ""
    visual_type: str = "figure"
    description: str = ""
    confidence: float = 0.0
    requires_human_confirmation: bool = True
    metadata: dict = Field(default_factory=dict)


class TableElement(BaseModel):
    table_id: str = ""
    source_file_name: str = ""
    source_block_id: str = ""
    markdown: str = ""
    confidence: float = 0.0
    metadata: dict = Field(default_factory=dict)


class GraphElement(BaseModel):
    graph_id: str = ""
    source_file_name: str = ""
    source_block_id: str = ""
    nodes: list[dict] = Field(default_factory=list)
    edges: list[dict] = Field(default_factory=list)
    confidence: float = 0.0
    unparsed_reason: str = ""


class ChartElement(BaseModel):
    chart_id: str = ""
    source_file_name: str = ""
    source_block_id: str = ""
    chart_type: str = "unknown"
    axes: list[dict] = Field(default_factory=list)
    series: list[dict] = Field(default_factory=list)
    confidence: float = 0.0
    unparsed_reason: str = ""


class DocumentIR(BaseModel):
    schema_version: str = "document_ir.v1"
    assets: list[DocumentAsset] = Field(default_factory=list)
    pages: list[DocumentPage] = Field(default_factory=list)
    layout_blocks: list[LayoutBlock] = Field(default_factory=list)
    visual_elements: list[VisualElement] = Field(default_factory=list)
    table_elements: list[TableElement] = Field(default_factory=list)
    graph_elements: list[GraphElement] = Field(default_factory=list)
    chart_elements: list[ChartElement] = Field(default_factory=list)


# ══════════════════════════════════════════════
#  容器类
# ══════════════════════════════════════════════


class DocumentSectionTree(BaseModel):
    """完整的章节树"""
    sections: list[DocumentSection] = Field(default_factory=list)
    root_section_ids: list[str] = Field(default_factory=list)
    toc_entries: list[DocumentTocEntry] = Field(default_factory=list)


class DocumentEvidencePool(BaseModel):
    """文档主证据池"""
    evidences: list[DocumentEvidence] = Field(default_factory=list)


class ReviewDocumentBundle(BaseModel):
    """文档解析总包。

    同时包含第一代 (chunks + stage_context_map) 和
    第二代 (section_tree + evidence_pool) 数据结构。
    """
    parsed_documents: list[ParsedDocument] = Field(default_factory=list)
    document_ir: DocumentIR = Field(default_factory=DocumentIR)
    # 第一代 (deprecated, 保留兼容)
    chunks: list[ReviewDocumentChunk] = Field(default_factory=list)
    stage_context_map: dict[str, StageDocumentContext] = Field(default_factory=dict)
    # 第二代
    section_tree: DocumentSectionTree = Field(default_factory=DocumentSectionTree)
    evidence_pool: DocumentEvidencePool = Field(default_factory=DocumentEvidencePool)
    extracted_parameters: list[ExtractedParameter] = Field(default_factory=list)
    extracted_objects: list[ExtractedTechnicalObject] = Field(default_factory=list)
    trace_link_candidates: list[TraceLinkCandidate] = Field(default_factory=list)
    requirements: list[RequirementItem] = Field(default_factory=list)
    design_elements: list[DesignElement] = Field(default_factory=list)
    verification_items: list[VerificationItem] = Field(default_factory=list)
    trace_links: list[TraceLink] = Field(default_factory=list)
    traceability_matrix_summary: TraceabilityMatrixSummary = Field(default_factory=TraceabilityMatrixSummary)
    warnings: list[str] = Field(default_factory=list)
