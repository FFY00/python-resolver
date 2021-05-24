# SPDX-License-Identifier: MIT

from __future__ import annotations

import functools
import operator
import os
import platform
import shutil
import tempfile
import typing
import urllib.request

from typing import Callable, Iterable, Iterator, Mapping, Optional, Sequence, Set, Union

import mousebender.simple
import packaging.requirements
import packaging.tags
import packaging.utils
import packaging.version
import resolvelib
import resolvelib.providers
import resolvelib.resolvers
import resolvelib.structs

import resolver.archive


__version__ = '0.0.2'


class Candidate():
    def __init__(
        self,
        name: str,
        version: packaging.version.Version,
        archive: resolver.archive.Archive,
        extras: Optional[Set[str]] = None,
    ):
        self._name = packaging.utils.canonicalize_name(name)
        self._version = version
        self._extras = extras or set()
        self._archive = archive

    def __repr__(self) -> str:
        return 'Candidate(name={}, version={}, extras=({}))'.format(
            self.name,
            self.version,
            ', '.join(self.extras),
        )

    def is_valid(self, supported_tags: Callable[[], Iterator[packaging.tags.Tag]]) -> bool:
        '''Delayed candidate validation because it requires fetching metadata and that is expensive.'''
        return all(
            extra in self.archive.metadata.get_all('Provides-Extra', [])
            for extra in self.extras
        ) and any(
            # XXX: Expensive! We should support passing filters to supported_tags, or maybe passing our iterable object
            tag in self.archive.tags
            for tag in supported_tags()
        )

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> packaging.version.Version:
        return self._version

    @property
    def extras(self) -> Set[str]:
        return self._extras

    @property
    def archive(self) -> resolver.archive.Archive:
        return self._archive

    @functools.cached_property
    def dependencies(self) -> Iterable[packaging.requirements.Requirement]:
        dependencies: Set[packaging.requirements.Requirement] = set()

        if self._extras:
            dependencies.add(packaging.requirements.Requirement(
                f'{self.name}=={str(self.version)}'
            ))

        for requirement_str in self.archive.metadata.get_all('Requires-Dist', []):
            requirement = packaging.requirements.Requirement(requirement_str)

            if not requirement.marker:
                # requirements without markers do not need to be evaluated
                if not self.extras:
                    # skip on extras as they are never an extra-only req
                    dependencies.add(requirement)
                continue

            for extra in self._extras:
                if (
                    requirement.marker.evaluate({'extra': extra})
                    and not requirement.marker.evaluate({'extra': ''})
                ):
                    # only inject requirements from the extra, but not the base package
                    dependencies.add(requirement)
                    continue

        return dependencies


class DependencyKey(typing.NamedTuple):
    name: str
    extras: Set[str]

    def __repr__(self) -> str:
        if not self.extras:
            return self.name
        return '{}[{}]'.format(self.name, ', '.join(sorted(self.extras)))

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, self.__class__)
            and self.name == other.name
            and self.extras == other.extras
        )


class Provider(resolvelib.AbstractProvider):  # type: ignore
    def __init__(
        self,
        cache_directory: Optional[str] = None,
        python_version: packaging.version.Version = packaging.version.Version(
            platform.python_version()
        ),
        package_index_url: str = 'https://pypi.org/simple/',
        supported_tags: Callable[[], Iterator[packaging.tags.Tag]] = packaging.tags.sys_tags,
    ) -> None:
        self._python_version = python_version
        self._package_index_url = package_index_url
        self._supported_tags = supported_tags
        self._cache = cache_directory if cache_directory else tempfile.mkdtemp(
            prefix='resolver-cache-',
        )
        self._remove_cache = cache_directory is None

        if self._cache:
            os.makedirs(self._cache, exist_ok=True)

    def __del__(self) -> None:
        if self._remove_cache:
            shutil.rmtree(self._cache)

    def identify(
        self,
        requirement_or_candidate: Union[
            packaging.requirements.Requirement,
            Candidate,
        ],
    ) -> DependencyKey:
        return DependencyKey(
            packaging.utils.canonicalize_name(requirement_or_candidate.name),
            requirement_or_candidate.extras,
        )

    def is_satisfied_by(
        self,
        requirement: packaging.requirements.Requirement,
        candidate: Candidate,
    ) -> bool:
        return (
            packaging.utils.canonicalize_name(requirement.name) == candidate.name
            and requirement.extras <= candidate.extras
            and candidate.version in requirement.specifier
        )

    def get_dependencies(
        self,
        candidate: Candidate,
    ) -> Iterable[packaging.requirements.Requirement]:
        return candidate.dependencies

    def get_preference(
        self,
        identifier: DependencyKey,
        resolutions: Mapping[DependencyKey, Candidate],
        candidates: Mapping[DependencyKey, Iterator[Candidate]],
        information: Mapping[DependencyKey, Iterator[
            resolvelib.resolvers.RequirementInformation[
                packaging.requirements.Requirement,
                Candidate,
            ]
        ]],
    ) -> resolvelib.providers.Preference:
        return 0

    def find_matches(
        self,
        identifier: DependencyKey,
        requirements: Mapping[DependencyKey, Iterator[packaging.requirements.Requirement]],
        incompatibilities: Mapping[DependencyKey, Iterator[Candidate]],
    ) -> resolvelib.structs.Matches:
        our_requirements = list(requirements[identifier])
        bad_versions = {c.version for c in incompatibilities[identifier]}

        candidates = (
            candidate
            for candidate in self._get_candidates(identifier.name, identifier.extras)
            if candidate.version not in bad_versions and all(
                candidate.version in r.specifier for r in our_requirements
            )
        )
        return functools.partial(self._validated_candidates_iter, identifier, self.sort_candidates(candidates))

    def _get_candidates(self, name: str, extras: Optional[Set[str]] = None) -> Iterator[Candidate]:
        url = mousebender.simple.create_project_url(self._package_index_url, name)
        with urllib.request.urlopen(url) as r:
            archives = mousebender.simple.parse_archive_links(r.read().decode())

        for archive_link in archives:
            if self._python_version not in archive_link.requires_python:
                continue

            try:
                archive = resolver.archive.Archive.from_archive_link(
                    archive_link,
                    self._cache,
                )
            except ValueError:
                continue

            try:
                candidate = Candidate(
                    name,
                    packaging.version.Version(archive.version),
                    archive,
                    extras or set(),
                )
            except packaging.version.InvalidVersion:
                continue

            yield candidate

    def _validated_candidates_iter(self, name: DependencyKey, candidates: Iterable[Candidate]) -> Iterator[Candidate]:
        for candidate in candidates:
            if candidate.is_valid(self._supported_tags):
                yield candidate

    def sort_candidates(self, candidates: Iterable[Candidate]) -> Sequence[Candidate]:
        '''Sort the candidates. Used by find_matches.'''
        return sorted(candidates, key=operator.attrgetter('version'), reverse=True)
