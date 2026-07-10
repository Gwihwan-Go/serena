import json
from dataclasses import dataclass
from types import SimpleNamespace

from serena.tools import FindReferencingSymbolsTool


@dataclass
class FakeLocation:
    relative_path: str
    line: int
    column: int


class FakeSymbol:
    def __init__(self, name_path: str, kind: str, relative_path: str, line: int, column: int = 0) -> None:
        self._name_path = name_path
        self.symbol_kind_name = kind
        self.relative_path = relative_path
        self.line = line
        self.column = column
        self.location = FakeLocation(relative_path, line, column)
        self.name = name_path.rsplit("/", 1)[-1]

    def get_name_path(self) -> str:
        return self._name_path

    def to_dict(
        self,
        *,
        kind: bool = False,
        relative_path: bool = False,
        depth: int = 0,
        body: bool = False,
        body_location: bool = False,
    ) -> dict:
        result = {"name_path": self._name_path}
        if kind:
            result["kind"] = self.symbol_kind_name
        if relative_path:
            result["relative_path"] = self.relative_path
        if body_location:
            result["body_location"] = {"start_line": self.line, "end_line": self.line}
        return result


@dataclass
class FakeReference:
    symbol: FakeSymbol
    line: int
    character: int


class FakeRetriever:
    def __init__(self, targets: list[FakeSymbol], references: dict[str, list[FakeReference]], suggestions: list[dict]) -> None:
        self.targets = targets
        self.references = references
        self.suggestions = suggestions

    def find_reference_targets(self, name_path: str, *, relative_file_path: str | None = None) -> list[FakeSymbol]:
        return self.targets

    def suggest_similar_symbols(self, name_path_pattern: str, *, within_relative_path: str | None = None, exclude_symbols=None) -> list[dict]:
        excluded = {(symbol.get_name_path(), symbol.relative_path) for symbol in exclude_symbols or []}
        return [
            suggestion
            for suggestion in self.suggestions
            if (suggestion.get("name_path"), suggestion.get("relative_path")) not in excluded
        ]

    def find_referencing_symbols_by_location(self, symbol_location: FakeLocation, **kwargs) -> list[FakeReference]:
        return self.references.get(symbol_location.relative_path, [])


class FakeContent:
    def to_display_string(self) -> str:
        return "  10: use target()"


class FakeProject:
    def retrieve_content_around_line(self, **kwargs) -> FakeContent:
        return FakeContent()


class FakeAgent:
    serena_config = SimpleNamespace(default_max_tool_answer_chars=10000)

    def get_active_project_or_raise(self) -> FakeProject:
        return FakeProject()


def make_tool(retriever: FakeRetriever) -> FindReferencingSymbolsTool:
    tool = object.__new__(FindReferencingSymbolsTool)
    tool.create_language_server_symbol_retriever = lambda: retriever
    tool.agent = FakeAgent()
    return tool


def test_find_refs_not_found_returns_similar_workspace_symbols() -> None:
    suggestion = {
        "name_path": "ArithmeticPostAggregator/Ops/QUOTIENT",
        "kind": "EnumMember",
        "relative_path": "processing/src/main/java/org/apache/druid/query/aggregation/post/ArithmeticPostAggregator.java",
        "line": 91,
    }
    tool = make_tool(FakeRetriever(targets=[], references={}, suggestions=[suggestion]))

    result = tool.apply(name_path="quotient")

    assert "Reference lookup fallback: target not found" in result
    assert "Similar workspace symbols:" in result
    assert "ArithmeticPostAggregator/Ops/QUOTIENT (EnumMember)" in result
    assert "retry find_refs" in result
    assert "Backend " + "detail" not in result
    assert "fallback_reason=" not in result


def test_find_refs_zero_refs_returns_distinct_broadened_candidates() -> None:
    target = FakeSymbol("Widget/render", "Method", "pkg/widget.py", 4)
    suggestion = {
        "name_path": "Widget/renderAll",
        "kind": "Method",
        "relative_path": "pkg/widget.py",
        "line": 20,
    }
    self_ref = FakeReference(symbol=target, line=4, character=0)
    tool = make_tool(FakeRetriever(targets=[target], references={"pkg/widget.py": [self_ref]}, suggestions=[suggestion]))

    result = tool.apply(name_path="Widget/render")

    assert "Reference lookup fallback: no usage references" in result
    assert "Symbol 'Widget/render' resolved" in result
    assert "Resolved targets:" in result
    assert "Broadened candidate targets:" in result
    assert "Widget/renderAll (Method)" in result
    assert "reference_symbol_not_found" not in result
    assert "Backend " + "detail" not in result
    assert "fallback_reason=" not in result


def test_find_refs_multiple_targets_are_aggregated_and_deduplicated() -> None:
    target_one = FakeSymbol("useCssVars", "Function", "packages/runtime-dom/src/helpers/useCssVars.ts", 18)
    target_two = FakeSymbol("src/helpers/useCssVars", "File", "packages/runtime-dom/src/helpers/useCssVars.ts", 0)
    caller = FakeSymbol("compileScript", "Function", "packages/compiler-sfc/src/compileScript.ts", 749)
    shared_ref = FakeReference(symbol=caller, line=750, character=10)
    tool = make_tool(
        FakeRetriever(
            targets=[target_one, target_two],
            references={
                target_one.relative_path: [shared_ref],
                target_two.relative_path: [shared_ref],
            },
            suggestions=[],
        )
    )

    result = tool.apply(name_path="useCssVars", max_answer_chars=10000)

    payload = json.loads(result)
    refs = payload["packages/compiler-sfc/src/compileScript.ts"]["Function"]
    assert len(refs) == 1
    assert refs[0]["name_path"] == "compileScript"
    assert "Found multiple" not in result
