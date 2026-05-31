from __future__ import annotations

import os
import struct
from pathlib import Path


def extract_tdms_metadata(file_path: str) -> dict:
    """读取 TDMS 文件基础元数据（无需 nptdms 时读文件头；有 nptdms 时读通道）。"""
    path = Path(file_path)
    meta: dict = {
        "file_name": path.name,
        "file_size_bytes": path.stat().st_size if path.exists() else 0,
        "format": "tdms",
    }

    if not path.exists():
        meta["parse_status"] = "failed"
        meta["error"] = "file not found"
        return meta

    try:
        with open(path, "rb") as f:
            header = f.read(4)
        if header == b"TDSm":
            meta["tdms_version_hint"] = "NI TDMS"
            meta["parse_status"] = "ok"
        else:
            meta["parse_status"] = "degraded"
            meta["warning"] = "unrecognized TDMS header"
    except OSError as exc:
        meta["parse_status"] = "failed"
        meta["error"] = str(exc)
        return meta

    try:
        import nptdms  # type: ignore

        from nptdms import TdmsFile

        with TdmsFile.read(path) as tdms:
            groups = []
            channel_count = 0
            for group in tdms.groups():
                channels = []
                for ch in group.channels():
                    channel_count += 1
                    channels.append({
                        "name": ch.name,
                        "length": len(ch),
                        "properties": {k: str(v)[:200] for k, v in list(ch.properties.items())[:5]},
                    })
                groups.append({"name": group.name, "channels": channels[:20]})
            meta["groups"] = groups[:10]
            meta["channel_count"] = channel_count
            meta["parser_name"] = "nptdms"
    except ImportError:
        meta["parser_name"] = "tdms_header_only"
        meta["warning"] = "安装 nptdms 可读取通道详情: pip install nptdms"
    except Exception as exc:
        meta["parser_name"] = "nptdms"
        meta["parse_status"] = "degraded"
        meta["warning"] = f"nptdms read partial: {exc}"

    return meta
