"""Map review document chunks to GNC review stages."""

from __future__ import annotations

from data_agent.parsing.schemas import ReviewDocumentChunk, StageDocumentContext

# Constants for Stage Mapping
AD_STAGE_KEYWORDS = {
    "ad_req_err": ["需求", "指标", "误差分解", "误差预算", "精度预算", "误差源"],
    "ad_timing": ["采集时序", "采样周期", "同步", "对时", "延迟", "时标"],
    "ad_algorithm": ["姿态确定算法", "滤波", "卡尔曼", "融合", "姿态解算", "估计"],
    "ad_install": ["安装指向", "安装矩阵", "测量单机安装", "视场", "安装误差"],
    "ad_simulation": ["数学仿真", "误差仿真", "结果分析", "蒙特卡洛", "收敛", "仿真场景"],
}

AC_STAGE_KEYWORDS = {
    "ac_thruster_layout": ["推力器布局", "推力器布置", "喷口布置", "推力方向", "推力分配"],
    "ac_other_actuator_layout": ["飞轮", "磁力矩器", "CMG", "执行机构布局", "执行机构配置"],
    "ac_control_law": ["控制律", "控制框图", "控制架构", "稳定性", "鲁棒性", "模式切换"],
    "ac_control_params": ["参数设计", "参数整定", "带宽", "增益", "限幅", "死区", "控制参数"],
    "ac_maneuver_law": ["操纵律", "机动律", "姿态机动", "指向控制", "机动控制"],
    "ac_unloading_law": ["卸载律", "动量卸载", "角动量管理", "卸载策略"],
    "ac_simulation": ["姿控仿真", "闭环仿真", "时域响应", "稳定性分析", "控制响应", "控制仿真"],
}


def map_chunks_to_review_stages(chunks: list[ReviewDocumentChunk], review_scope: str = "ad_ac") -> dict[str, StageDocumentContext]:
    """Map created chunks to specific review stages using keywords in title and body."""
    stage_map = {}
    
    target_stages = {}
    normalized_scope = (review_scope or "ad_ac").strip().lower()
    if normalized_scope in ("ad", "ad_only", "ad_ac"):
        target_stages.update(AD_STAGE_KEYWORDS)
    if normalized_scope in ("ac", "ac_only", "ad_ac"):
        target_stages.update(AC_STAGE_KEYWORDS)
        
    for stage_key, keywords in target_stages.items():
        ctx = StageDocumentContext(stage_key=stage_key)
        
        for chunk in chunks:
            matched = False
            
            # Title matching has higher weight conceptually (we'll just use it to match definitely)
            if any(kw in chunk.section_title for kw in keywords) or \
               any(kw in path for path in chunk.section_path for kw in keywords):
                matched = True
            
            # Body matching 
            if not matched:
                if any(kw in chunk.chunk_text for kw in keywords):
                    matched = True
                    
            if matched:
                if chunk.chunk_id not in ctx.matched_chunk_ids:
                    ctx.matched_chunk_ids.append(chunk.chunk_id)
                if chunk.section_title and chunk.section_title not in ctx.matched_section_titles:
                    ctx.matched_section_titles.append(chunk.section_title)
                    
        if not ctx.matched_chunk_ids:
            ctx.missing_expected_topics.append(f"No document section matched for {stage_key}")
            ctx.notes.append(f"Stage `{stage_key}` lacks direct evidence in the submitted materials.")
        else:
            ctx.coverage_score = 1.0 # Simple binary for now
            
        stage_map[stage_key] = ctx
        
    return stage_map
