"""Shared test helpers: import the skill's scripts and run the extractor on a fixture."""
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "skills" / "code-flow-report" / "scripts"
FIXTURES = REPO / "tests" / "fixtures"
sys.path.insert(0, str(SCRIPTS))

import common  # noqa: E402
import extract  # noqa: E402

CONFIG = {"scan": {"strip_prefixes": ["src"]},
          "conventions": {"param_types": {"cur": "db.cursor()"}, "gateways": ["run_write"]}}


def config(**over):
    return common.merge(common.merge(common.DEFAULT_CONFIG, CONFIG), over)


def code_map(fixture, **over):
    return extract.build(FIXTURES / fixture, config(**over))


def copy_fixture(fixture):
    """A throwaway copy, for tests that run the CLI or edit source."""
    tmp = Path(tempfile.mkdtemp(prefix="codeflow-"))
    shutil.copytree(FIXTURES / fixture, tmp / fixture)
    return tmp / fixture
