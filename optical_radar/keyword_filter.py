from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from .models import Paper


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    escaped = re.escape(phrase.strip())
    return re.compile(rf"(?<!\w){escaped}(?!\w)", re.IGNORECASE)


class KeywordFilter:
    def __init__(self, keywords: dict[str, list[str]]) -> None:
        self.keywords = keywords
        self._patterns = {
            group: [(kw, _phrase_pattern(kw)) for kw in values]
            for group, values in keywords.items()
        }

    def match_with_locations(self, paper: Paper) -> dict[str, dict[str, list[str]]]:
        fields = {
            "title": paper.title or "",
            "abstract": paper.abstract or "",
            "metadata": " ".join([*(paper.categories or []), paper.primary_category or ""]),
        }
        matches: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        for group, patterns in self._patterns.items():
            for keyword, pattern in patterns:
                for location, text in fields.items():
                    if pattern.search(text):
                        matches[group][location].append(keyword)
        return {
            group: {location: values for location, values in locations.items()}
            for group, locations in matches.items()
        }

    def match(self, paper: Paper) -> dict[str, list[str]]:
        located = self.match_with_locations(paper)
        return self.flatten_location_matches(located)

    def flatten_location_matches(self, matches: dict[str, dict[str, list[str]]]) -> dict[str, list[str]]:
        flattened: dict[str, list[str]] = {}
        for group, locations in matches.items():
            seen: set[str] = set()
            values: list[str] = []
            for location in ["title", "abstract", "metadata"]:
                for keyword in locations.get(location, []):
                    key = keyword.lower()
                    if key not in seen:
                        seen.add(key)
                        values.append(keyword)
            if values:
                flattened[group] = values
        return flattened

    def match_locations_from_flat(self, matches: dict[str, list[str]]) -> dict[str, dict[str, list[str]]]:
        return {
            group: {"abstract": list(values or [])}
            for group, values in matches.items()
            if values
        }

    def location_counts(self, matches: dict[str, dict[str, list[str]]]) -> dict[str, dict[str, int]]:
        return {
            group: {location: len(values) for location, values in locations.items()}
            for group, locations in matches.items()
        }

    def flatten_matches(self, matches: dict[str, Any]) -> list[str]:
        if matches and all(isinstance(value, dict) for value in matches.values()):
            matches = self.flatten_location_matches(matches)
        seen: set[str] = set()
        flattened: list[str] = []
        for values in matches.values():
            for value in values:
                key = value.lower()
                if key not in seen:
                    seen.add(key)
                    flattened.append(value)
        return flattened

    def title_matches(self, paper: Paper) -> list[str]:
        title = paper.title or ""
        found: list[str] = []
        for group, patterns in self._patterns.items():
            if group == "exclude":
                continue
            for keyword, pattern in patterns:
                if pattern.search(title):
                    found.append(keyword)
        return found
