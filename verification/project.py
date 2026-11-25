"""项目配置（Python 侧）。

和 `vision/src/project.ts` 对应：让框架知道「现在测的是哪个项目」。
选项目的方式一致——环境变量 `QA_PROJECT`，没设且只有一个项目时自动用它。

项目目录：`vision/projects/<名字>/`
    project.json   包名、App 源码位置、用例目录
    cases/         用例 YAML
    python/        项目专属模块（覆盖率表、产物校验）
    vision/        项目专属 TS 模块
"""
from __future__ import annotations

import json
import os
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent          # app-automation
PROJECTS = ROOT / "vision" / "projects"


def project_names() -> list[str]:
    if not PROJECTS.is_dir():
        return []
    return sorted(
        d.name for d in PROJECTS.iterdir() if (d / "project.json").is_file()
    )


def project_name() -> str:
    picked = (os.environ.get("QA_PROJECT") or "").strip()
    if picked:
        return picked
    names = project_names()
    if len(names) == 1:
        return names[0]
    if not names:
        raise SystemExit(f"{PROJECTS} 下没有项目（需要 <名字>/project.json）")
    raise SystemExit(f"有 {len(names)} 个项目（{'、'.join(names)}），用 QA_PROJECT 指定一个")


def project_dir() -> Path:
    return PROJECTS / project_name()


def config() -> dict:
    f = project_dir() / "project.json"
    if not f.is_file():
        raise SystemExit(f"找不到项目配置：{f}")
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(f"{f} 不是合法 JSON：{e}") from e


def _resolve(p: str | None, default: str | None = None) -> Path | None:
    v = (p or default or "").strip()
    if not v:
        return None
    path = Path(v)
    return path if path.is_absolute() else (project_dir() / path).resolve()


def cases_dir() -> Path:
    return _resolve(config().get("casesDir"), "cases") or (project_dir() / "cases")


def app_source() -> Path | None:
    """被测 App 的源码根目录。环境变量优先，其次是 project.json。"""
    env = (os.environ.get("QA_APP_SOURCE") or "").strip()
    if env:
        return Path(env).resolve()
    return _resolve(config().get("appSourceDir"))


def app_repo() -> Path:
    """App 仓库根：jest 在它下面跑。没配源码就退回框架的上一级。"""
    src = app_source()
    return src.parent if src else ROOT.parent


def load_module(rel: str) -> ModuleType:
    """按文件路径加载项目内的 python 模块（目录名可能带连字符，不能当包 import）。"""
    path = project_dir() / rel
    if not path.is_file():
        raise SystemExit(f"找不到项目模块：{path}")
    spec = spec_from_file_location(f"qa_project_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"无法加载：{path}")
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
