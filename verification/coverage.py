"""用例归属表：每条测试设计用例由哪一层执行。

这张表属于**项目**，不属于框架——换项目就换表。
实际内容在 `vision/projects/<名字>/python/coverage.py`，这里只做转发，
这样 `from verification.coverage import COVERAGE` 的老写法不用改。
"""
from __future__ import annotations

from verification.project import load_module

COVERAGE = load_module("python/coverage.py").COVERAGE
