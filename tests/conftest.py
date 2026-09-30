"""pytest 公共配置：始终从当前工作区的纯 Python 源码树导入。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 测试位于仓库根 tests/，正式源码位于 strixnova/src/。
_PY_SRC = Path(__file__).resolve().parents[1] / "strixnova" / "src"
if str(_PY_SRC) not in sys.path:
    sys.path.insert(0, str(_PY_SRC))

# Child source-test processes use this same checkout. Installed-state probes
# use isolated Python and deliberately ignore this source path.
os.environ["PYTHONPATH"] = str(_PY_SRC)

# Git for Windows may enable its built-in fsmonitor globally. Every temporary
# repository created by this suite would then detach a daemon, even though the
# repository is deleted seconds later. Keep product Git behavior untouched and
# override only child Git processes of pytest.
_git_config_count = int(os.environ.get("GIT_CONFIG_COUNT", "0"))
os.environ[f"GIT_CONFIG_KEY_{_git_config_count}"] = "core.fsmonitor"
os.environ[f"GIT_CONFIG_VALUE_{_git_config_count}"] = "false"
os.environ["GIT_CONFIG_COUNT"] = str(_git_config_count + 1)


import pytest


@pytest.fixture
def installed_python() -> Path:
    """Use an explicitly provided clean-wheel environment for installed probes.

    Source tests continue to use the repository interpreter and checkout.
    This fixture never installs anything or silently probes a global package.
    """
    value = os.environ.get("STRIXNOVA_TEST_INSTALLED_PYTHON")
    if not value:
        pytest.skip("Requires the candidate wheel's isolated interpreter via STRIXNOVA_TEST_INSTALLED_PYTHON")
    interpreter = Path(value).resolve()
    if not interpreter.is_file() or interpreter == Path(sys.executable).resolve():
        pytest.fail("The installed probe must use the candidate's separate existing interpreter")
    return interpreter
