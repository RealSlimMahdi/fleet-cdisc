"""Fleet's version, read back from the installed distribution.

The number is stamped at build time from the git tag (``hatch-vcs``), so no
version literal is hand-maintained anywhere in the tree.  It is announced to
tooling as ``serverInfo.version`` in the language-server handshake.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("fleet-cdisc")
except PackageNotFoundError:  # a source tree that was never installed
    __version__ = "0+unknown"
