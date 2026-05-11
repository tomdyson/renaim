from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from .naming import slugify

LIGHT_STOPWORDS = {
    "a",
    "an",
    "and",
    "at",
    "in",
    "of",
    "on",
    "the",
}


@dataclass(frozen=True)
class HarmonizeGroup:
    slugs: tuple[str, ...]
    canonical: str
    count: int


def slug_tokens(slug: str) -> set[str]:
    return {token for token in slugify(slug).split("-") if token and token not in LIGHT_STOPWORDS}


def slug_similarity(left: str, right: str) -> float:
    left_tokens = slug_tokens(left)
    right_tokens = slug_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def choose_canonical(slugs: list[str]) -> str:
    counts = Counter(slugs)
    return sorted(counts, key=lambda slug: (-counts[slug], len(slug), slug))[0]


def harmonize_groups(slugs: list[str], threshold: float = 0.4, min_group_size: int = 2) -> list[HarmonizeGroup]:
    unique = sorted(set(slugify(slug) for slug in slugs))
    parent = {slug: slug for slug in unique}

    def find(slug: str) -> str:
        while parent[slug] != slug:
            parent[slug] = parent[parent[slug]]
            slug = parent[slug]
        return slug

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for index, left in enumerate(unique):
        for right in unique[index + 1 :]:
            if slug_similarity(left, right) >= threshold:
                union(left, right)

    components: dict[str, list[str]] = defaultdict(list)
    for slug in unique:
        components[find(slug)].append(slug)

    groups: list[HarmonizeGroup] = []
    for component in components.values():
        if len(component) < min_group_size:
            continue
        component_counts = [slug for slug in slugs if slugify(slug) in component]
        groups.append(
            HarmonizeGroup(
                slugs=tuple(sorted(component)),
                canonical=choose_canonical(component_counts),
                count=len(component_counts),
            )
        )

    return sorted(groups, key=lambda group: (-group.count, group.canonical))
