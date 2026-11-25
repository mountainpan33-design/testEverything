"""断言结果记录：所有判定的唯一出口，报告从这里生成。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Check:
    case: str
    rule: str
    status: str  # pass / fail / skip
    layer: str = ""
    expected: str = ""
    actual: str = ""
    message: str = ""


CHECKS: list[Check] = []
_CURRENT = {"case": "<未指定>"}


def set_case(name: str) -> None:
    _CURRENT["case"] = name


def current_case() -> str:
    return _CURRENT["case"]


def record(
    rule: str,
    status: str,
    layer: str = "",
    expected: str = "",
    actual: str = "",
    message: str = "",
) -> None:
    CHECKS.append(
        Check(
            case=current_case(),
            rule=rule,
            status=status,
            layer=layer,
            expected=expected,
            actual=actual,
            message=message,
        )
    )


def reset() -> None:
    CHECKS.clear()


def summary() -> dict:
    total = len(CHECKS)
    passed = sum(1 for c in CHECKS if c.status == "pass")
    failed = sum(1 for c in CHECKS if c.status == "fail")
    skipped = sum(1 for c in CHECKS if c.status == "skip")
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "verdict": "FAIL" if failed else "PASS",
    }
