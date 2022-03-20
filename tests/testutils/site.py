import subprocess

from typing import Optional

from buildstream import utils, ProgramNotFoundError

GIT: Optional[str]
BZR: Optional[str]

try:
    GIT = utils.get_host_tool("git")
    HAVE_GIT = True

    out = str(subprocess.check_output(["git", "--version"]), "utf-8")
    # e.g. on Git for Windows we get "git version 2.21.0.windows.1".
    # e.g. on Mac via Homebrew we get "git version 2.19.0".
    version = tuple(int(x) for x in out.split(" ")[2].split(".")[:3])
    HAVE_OLD_GIT = version < (1, 8, 5)

    GIT_ENV = {
        "GIT_AUTHOR_DATE": "1320966000 +0200",
        "GIT_AUTHOR_NAME": "tomjon",
        "GIT_AUTHOR_EMAIL": "tom@jon.com",
        "GIT_COMMITTER_DATE": "1320966000 +0200",
        "GIT_COMMITTER_NAME": "tomjon",
        "GIT_COMMITTER_EMAIL": "tom@jon.com",
    }
except ProgramNotFoundError:
    GIT = None
    HAVE_GIT = False
    HAVE_OLD_GIT = False
    GIT_ENV = {}

try:
    BZR = utils.get_host_tool("bzr")
    HAVE_BZR = True
    # Breezy 3.0 supports `BRZ_EMAIL` but not `BZR_EMAIL`
    BZR_ENV = {
        "BZR_EMAIL": "Testy McTesterson <testy.mctesterson@example.com>",
        "BRZ_EMAIL": "Testy McTesterson <testy.mctesterson@example.com>",
    }
except ProgramNotFoundError:
    BZR = None
    HAVE_BZR = False
    BZR_ENV = {}
