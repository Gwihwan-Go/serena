"""
Flow (flow-bin) language server adapter for JavaScript files with Flow type
annotations.

Why this exists: typescript-language-server cannot parse Flow-typed .js
(e.g. babel-parser's pre-TypeScript era sources) — documentSymbol comes back
empty/broken, so read_def/find_refs report "not in LSP index" for symbols
that plainly exist. Flow's own `flow lsp` speaks standard LSP (documentSymbol,
definition, references) and understands the syntax natively.

Binary discovery (in order):
  1. <repo>/node_modules/.bin/flow — the repo's own pinned flow-bin, always
     version-correct when present;
  2. $SERENA_FLOW_BIN — explicit override (the symcli harness points this at
     a vendored flow-bin matching the target era);
  3. `flow` on PATH.
No auto-install: Flow versions are repo-specific (.flowconfig options drift
across versions), so a silently installed "latest" would refuse era configs.
"""

import logging
import os
import pathlib
import shutil
import threading

from solidlsp.ls import (
    LanguageServerDependencyProvider,
    LanguageServerDependencyProviderSinglePath,
    SolidLanguageServer,
)
from solidlsp.ls_config import LanguageServerConfig
from solidlsp.lsp_protocol_handler.lsp_types import InitializeParams
from solidlsp.settings import SolidLSPSettings

log = logging.getLogger(__name__)


class FlowLanguageServer(SolidLanguageServer):
    """Flow-typed JavaScript support via `flow lsp` (flow-bin)."""

    def __init__(self, config: LanguageServerConfig, repository_root_path: str, solidlsp_settings: SolidLSPSettings):
        super().__init__(
            config,
            repository_root_path,
            None,
            "javascript_flow",
            solidlsp_settings,
        )
        self.server_ready = threading.Event()

    def _create_dependency_provider(self) -> LanguageServerDependencyProvider:
        return self.DependencyProvider(
            self._custom_settings, self._ls_resources_dir, repository_root_path=self.repository_root_path
        )

    class DependencyProvider(LanguageServerDependencyProviderSinglePath):
        def __init__(self, custom_settings, ls_resources_dir, repository_root_path: str = ""):
            super().__init__(custom_settings, ls_resources_dir)
            self._repository_root_path = repository_root_path

        def _get_or_install_core_dependency(self) -> str:
            candidates = []
            if self._repository_root_path:
                candidates.append(os.path.join(self._repository_root_path, "node_modules", ".bin", "flow"))
            env_bin = os.environ.get("SERENA_FLOW_BIN", "").strip()
            if env_bin:
                candidates.append(env_bin)
            which_bin = shutil.which("flow")
            if which_bin:
                candidates.append(which_bin)
            for path in candidates:
                if path and os.path.isfile(path) and os.access(path, os.X_OK):
                    return path
            raise RuntimeError(
                "flow (flow-bin) binary not found for Flow-typed JavaScript.\n"
                "Searched: repo node_modules/.bin/flow, $SERENA_FLOW_BIN, PATH.\n"
                "Install a version matching the repo era (npm install flow-bin@<ver>) "
                "and/or set SERENA_FLOW_BIN to its path."
            )

        def _create_launch_command(self, core_path: str) -> list[str]:
            return [core_path, "lsp"]

    @staticmethod
    def _get_initialize_params(repository_absolute_path: str) -> InitializeParams:
        root_uri = pathlib.Path(repository_absolute_path).as_uri()
        initialize_params = {
            "locale": "en",
            "capabilities": {
                "textDocument": {
                    "synchronization": {"didSave": True, "dynamicRegistration": True},
                    "definition": {"dynamicRegistration": True},
                    "references": {"dynamicRegistration": True},
                    "documentSymbol": {
                        "dynamicRegistration": True,
                        "hierarchicalDocumentSymbolSupport": True,
                        "symbolKind": {"valueSet": list(range(1, 27))},
                    },
                    "hover": {"dynamicRegistration": True, "contentFormat": ["markdown", "plaintext"]},
                },
                "workspace": {
                    "workspaceFolders": True,
                    "didChangeConfiguration": {"dynamicRegistration": True},
                    "symbol": {"dynamicRegistration": True},
                },
                # flow lsp uses window/showStatus to report typecheck progress
                "window": {"status": {"dynamicRegistration": False}},
            },
            "processId": os.getpid(),
            "rootPath": repository_absolute_path,
            "rootUri": root_uri,
            "workspaceFolders": [
                {
                    "uri": root_uri,
                    "name": os.path.basename(repository_absolute_path),
                }
            ],
        }
        return initialize_params  # type: ignore

    def _start_server(self) -> None:
        def do_nothing(params: dict) -> None:
            return

        def show_status_handler(params: dict):
            # flow lsp REQUESTS window/showStatus (an LSP extension) and waits
            # for an answer; reply with None so startup never deadlocks. The
            # "ready" transition shows up here once the flow server finishes
            # its initial check.
            msg = str(params.get("message", ""))
            if "ready" in msg.lower() or params.get("type") == 3:
                self.server_ready.set()
            return None

        self.server.on_request("window/showStatus", show_status_handler)
        self.server.on_request("window/showMessageRequest", lambda params: None)
        self.server.on_notification("window/logMessage", do_nothing)
        self.server.on_notification("window/showMessage", do_nothing)
        self.server.on_notification("telemetry/event", do_nothing)
        self.server.on_notification("textDocument/publishDiagnostics", do_nothing)
        self.server.on_notification("$/progress", do_nothing)

        log.info("Starting flow lsp process")
        self.server.start()
        initialize_params = self._get_initialize_params(self.repository_root_path)
        init_response = self.server.send.initialize(initialize_params)
        log.debug(f"flow lsp initialize response: {init_response}")
        self.server.notify.initialized({})

        # flow lsp queues requests until its server finishes the initial
        # typecheck, so proceeding early is safe — requests just take longer
        # on the very first call.
        if not self.server_ready.wait(timeout=10.0):
            log.info("flow lsp gave no explicit ready signal within 10s; proceeding (requests queue server-side)")
            self.server_ready.set()
