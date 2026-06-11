import pytest

from serena.ls_manager import LanguageServerManager, LanguageServerManagerInitialisationError
from solidlsp.ls_config import Language


class _FakeLanguageServer:
    def __init__(self, language):
        self.language = language
        self.stopped = False

    def start(self):
        return None

    def is_running(self):
        return True

    def stop(self, **_kwargs):
        self.stopped = True

    def is_ignored_path(self, relative_path, ignore_unsupported_files=True):
        if not ignore_unsupported_files:
            return False
        return not self.language.get_source_fn_matcher().is_relevant_filename(relative_path)


class _Factory:
    def __init__(self, failures):
        self.failures = failures

    def create_language_server(self, language):
        if language in self.failures:
            raise RuntimeError(self.failures[language])
        return _FakeLanguageServer(language)


def test_mixed_language_startup_keeps_healthy_servers_and_reports_failed_language():
    manager = LanguageServerManager.from_languages(
        [Language.GO, Language.TERRAFORM],
        _Factory({Language.TERRAFORM: "terraform-ls missing"}),
        allow_partial=True,
    )

    assert manager.get_active_languages() == [Language.GO]
    assert manager.get_language_server("main.go").language == Language.GO

    with pytest.raises(LanguageServerManagerInitialisationError) as exc:
        manager.get_language_server("main.tf")

    assert "terraform" in str(exc.value)
    assert "terraform-ls missing" in str(exc.value)


def test_php_startup_failure_has_specialized_diagnostic():
    with pytest.raises(LanguageServerManagerInitialisationError) as exc:
        LanguageServerManager.from_languages(
            [Language.PHP],
            _Factory({Language.PHP: "intelephense exited"}),
            allow_partial=True,
        )

    msg = str(exc.value)
    assert "php_lsp_unavailable" in msg
    assert "PHP runtime" in msg
    assert "composer" in msg
    assert "intelephense exited" in msg
