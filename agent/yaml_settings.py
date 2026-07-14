"""
从项目根目录加载统一 config.yaml / config.local.yaml。

文件合并顺序（后者覆盖前者）：
  config.yaml → config.local.yaml → （可选）CGAGENT_CONFIG / 显式 path

业务取值优先级：
  根目录 YAML（已合并） > 环境变量 / .env > 代码默认值
  即：YAML 配了就用 YAML；没配才用别的。
"""

from __future__ import annotations

import copy
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_YAML = _PROJECT_ROOT / "config.yaml"
_LOCAL_YAML = _PROJECT_ROOT / "config.local.yaml"

_lock = threading.Lock()
_raw_cache: Optional[Dict[str, Any]] = None
_cache_paths: list[str] = []


def project_root() -> Path:
    return _PROJECT_ROOT


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _load_yaml_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            logger.warning("Config file is not a mapping: %s", path)
            return {}
        return data
    except Exception as e:
        logger.error("Failed to load config %s: %s", path, e)
        return {}


def load_yaml_config(
    config_path: Optional[str] = None,
    *,
    force_reload: bool = False,
) -> Dict[str, Any]:
    """加载并合并 YAML 配置，结果缓存。"""
    global _raw_cache, _cache_paths

    env_path = os.getenv("CGAGENT_CONFIG")
    paths: list[Path] = []
    if config_path:
        paths.append(Path(config_path))
    elif env_path:
        paths.append(Path(env_path))
    else:
        if _DEFAULT_YAML.exists():
            paths.append(_DEFAULT_YAML)
        if _LOCAL_YAML.exists():
            paths.append(_LOCAL_YAML)

    path_keys = [str(p.resolve()) if p.exists() else str(p) for p in paths]
    with _lock:
        if not force_reload and _raw_cache is not None and _cache_paths == path_keys:
            return copy.deepcopy(_raw_cache)

        merged: Dict[str, Any] = {}
        for p in paths:
            merged = _deep_merge(merged, _load_yaml_file(p))

        _raw_cache = merged
        _cache_paths = path_keys
        logger.info("Loaded yaml config from: %s", path_keys or ["(empty)"])
        return copy.deepcopy(merged)


def get_section(name: str, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data = load_yaml_config()
    section = data.get(name)
    if isinstance(section, dict):
        return section
    return default if default is not None else {}


def get_value(*keys: str, default: Any = None) -> Any:
    """点路径取值，如 get_value('memory', 'enabled', default=True)。"""
    data: Any = load_yaml_config()
    for key in keys:
        if not isinstance(data, dict) or key not in data:
            return default
        data = data[key]
    return data


def resolve_path(path_str: str) -> Path:
    """相对路径相对项目根解析。"""
    p = Path(path_str)
    if p.is_absolute():
        return p
    return (_PROJECT_ROOT / p).resolve()


def reload_yaml_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    return load_yaml_config(config_path, force_reload=True)
