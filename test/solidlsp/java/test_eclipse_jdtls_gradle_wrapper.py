from pathlib import Path

from solidlsp.language_servers.eclipse_jdtls import EclipseJDTLS, RuntimeDependencyPaths


def _jdtls_for_initialize_params(tmp_path: Path, custom_settings: dict | None = None) -> EclipseJDTLS:
    server = object.__new__(EclipseJDTLS)
    server._custom_settings = custom_settings or {}
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    server.runtime_dependency_paths = RuntimeDependencyPaths(
        gradle_path=str(runtime_dir / "gradle-8.14.2"),
        lombok_jar_path=str(runtime_dir / "lombok.jar"),
        jre_path=str(runtime_dir / "jre" / "bin" / "java"),
        jre_home_path=str(runtime_dir / "jre"),
        jdtls_launcher_jar_path=str(runtime_dir / "launcher.jar"),
        jdtls_readonly_config_path=str(runtime_dir / "config"),
        intellicode_jar_path=str(runtime_dir / "intellicode.jar"),
        intellisense_members_path=str(runtime_dir / "members"),
    )
    Path(server.runtime_dependency_paths.jre_home_path).mkdir(parents=True)
    return server


def _gradle_settings(params: dict) -> dict:
    return params["initializationOptions"]["settings"]["java"]["import"]["gradle"]


def test_gradle_wrapper_is_enabled_by_default_when_project_has_wrapper(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "gradle" / "wrapper").mkdir(parents=True)
    (repo / "gradle" / "wrapper" / "gradle-wrapper.properties").write_text(
        "distributionUrl=https\\://services.gradle.org/distributions/gradle-8.4-bin.zip\n",
        encoding="utf-8",
    )

    params = _jdtls_for_initialize_params(tmp_path)._get_initialize_params(str(repo))

    assert _gradle_settings(params)["wrapper"]["enabled"] is True


def test_explicit_gradle_wrapper_setting_is_respected(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "gradle" / "wrapper").mkdir(parents=True)
    (repo / "gradle" / "wrapper" / "gradle-wrapper.properties").write_text("", encoding="utf-8")

    params = _jdtls_for_initialize_params(tmp_path, {"gradle_wrapper_enabled": False})._get_initialize_params(str(repo))

    assert _gradle_settings(params)["wrapper"]["enabled"] is False
