from dataclasses import dataclass

from serena.tools.tools_base import Tool, ToolMarkerDoesNotRequireActiveProject
from solidlsp.ls_config import Language
from solidlsp.ls_exceptions import SolidLSPException
from solidlsp.ls_process import LanguageServerTerminatedException


@dataclass
class _SerenaConfig:
    tool_timeout: float = 1


class _Task:
    def __init__(self, fn):
        self._fn = fn

    def result(self, timeout=None):
        return self._fn()


class _FakeManager:
    def __init__(self):
        self.restarts = 0
        self.failures = 0
        self.circuit_open = False

    def restart_language_server(self, language):
        self.restarts += 1

    def get_open_language_server_circuit_message(self):
        if self.circuit_open:
            return self.format_language_server_circuit_open_message(Language.PHP)
        return None

    def record_language_server_termination(self, language):
        self.failures += 1
        self.circuit_open = self.failures >= 2
        return self.circuit_open

    def reset_language_server_termination_failures(self, language=None):
        self.failures = 0

    @staticmethod
    def format_language_server_circuit_open_message(language):
        return f"language_server_unavailable: {language.value}"

    def save_all_caches(self):
        pass


class _FakeAgent:
    def __init__(self):
        self.serena_config = _SerenaConfig()
        self.manager = _FakeManager()

    def tool_is_active(self, name):
        return True

    def issue_task(self, task, name=None):
        return _Task(task)

    def get_language_server_manager_or_raise(self):
        return self.manager

    def get_language_server_manager(self):
        return self.manager

    def record_tool_usage(self, input_kwargs, tool_result, tool):
        pass


class _BrokenLSPTool(Tool, ToolMarkerDoesNotRequireActiveProject):
    def __init__(self, agent):
        super().__init__(agent)
        self.calls = 0

    def apply(self):
        self.calls += 1
        raise SolidLSPException(
            "documentSymbol failed",
            LanguageServerTerminatedException("stdout reader exited", Language.PHP),
        )


def test_lsp_circuit_breaker_opens_after_retry_failure_and_skips_future_restarts():
    agent = _FakeAgent()
    tool = _BrokenLSPTool(agent)

    result = tool.apply_ex(log_call=False)

    assert agent.manager.restarts == 1
    assert tool.calls == 2
    assert "language_server_unavailable" in result
    assert "php" in result

    result = tool.apply_ex(log_call=False)

    assert agent.manager.restarts == 1
    assert tool.calls == 3
    assert "language_server_unavailable" in result
