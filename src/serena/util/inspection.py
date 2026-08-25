import logging
import os
from collections.abc import Callable, Iterator
from typing import TypeVar

from serena.util.file_system import find_all_non_ignored_files
from solidlsp.ls_config import Language

T = TypeVar("T")

log = logging.getLogger(__name__)


def iter_subclasses(
    cls: type[T], recursive: bool = True, inclusion_predicate: Callable[[type[T]], bool] = lambda t: True
) -> Iterator[type[T]]:
    """Iterate over all subclasses of a class.

    :param cls: The class whose subclasses to iterate over.
    :param recursive: If True, also iterate over all subclasses of all subclasses.
    :param inclusion_predicate: a predicate function to decide whether to include a subclass in the result
    """
    for subclass in cls.__subclasses__():
        if inclusion_predicate(subclass):
            yield subclass
        if recursive:
            yield from iter_subclasses(subclass, recursive, inclusion_predicate)


def determine_programming_language_composition(repo_path: str) -> dict[Language, float]:
    """
    Determine the programming language composition of a repository.

    :param repo_path: Path to the repository to analyze

    :return: Dictionary mapping languages to percentages of files matching each language
    """
    all_files = find_all_non_ignored_files(repo_path)

    if not all_files:
        return {}

    # Count files for each language
    language_counts: dict[Language, int] = {}
    total_files = len(all_files)

    flow_present = os.path.exists(os.path.join(repo_path, ".flowconfig"))
    for language in Language.iter_all(include_experimental=False):
        if language == Language.JAVASCRIPT_FLOW and not flow_present:
            # Flow only participates when the repo actually uses Flow.
            continue
        matcher = language.get_source_fn_matcher()
        if flow_present and language in (Language.TYPESCRIPT, Language.TYPESCRIPT_VTS, Language.VUE):
            # With a .flowconfig present, *.js belongs to the Flow server —
            # neither tsserver nor the Vue LS can parse Flow syntax. Count the
            # JS-superset languages by their own file families only, so Flow
            # outranks them in the language ordering (per-file routing picks
            # the first matching server in that order).
            from solidlsp.ls_config import FilenameMatcher as _FM
            if language == Language.VUE:
                matcher = _FM("*.vue")
            else:
                matcher = _FM("*.ts", "*.tsx", "*.mts", "*.cts")
        count = 0

        for file_path in all_files:
            # Use just the filename for matching, not the full path
            filename = os.path.basename(file_path)
            if matcher.is_relevant_filename(filename):
                count += 1

        if count > 0:
            language_counts[language] = count

    # Convert counts to percentages
    language_percentages: dict[Language, float] = {}
    for language, count in language_counts.items():
        percentage = (count / total_files) * 100
        language_percentages[language] = round(percentage, 2)

    return language_percentages
