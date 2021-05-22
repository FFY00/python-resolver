# SPDX-License-Identifier: MIT

from __future__ import annotations

import functools
import operator
import os
import pathlib
import platform
import re
import shutil
import tempfile
import typing
import urllib.request
import zipfile

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


try:
    import importlib.metadata as importlib_metadata
except ImportError:
    import importlib_metadata  # type: ignore


if typing.TYPE_CHECKING:
    # PackageMetadata is not public - https://bugs.python.org/issue44210
    import importlib_metadata as _importlib_metadata


_WHEEL_NAME_REGEX = re.compile(
    r'(?P<distribution>.+)-(?P<version>.+)'
    r'(-(?P<build_tag>.+))?-(?P<python_tag>.+)'
    r'-(?P<abi_tag>.+)-(?P<platform_tag>.+).whl'
)


class Archive():
    def __init__(
        self,
        url: str,
        filename: str,
        cache_directory: str,
    ) -> None:
        self._url = url
        self._filename = filename
        self._cache = pathlib.Path(cache_directory)

    @staticmethod
    def from_archive_link(
        archive_link: mousebender.simple.ArchiveLink,
        cache_directory: str,
    ) -> Archive:
        # XXX: Add support for sdists
        if archive_link.filename.endswith('.whl'):
            return WheelArchive(archive_link.url, archive_link.filename, cache_directory)
        raise ValueError('Unsupported distribution')

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}({self._filename})'

    @functools.cached_property
    def file(self) -> pathlib.Path:
        path = self._cache / self._filename

        if path.exists() and not path.is_file():
            raise ValueError(f'Path `{os.fspath(path)}` exists and is not a file')

        if not path.is_file():
            with urllib.request.urlopen(self._url) as r, path.open('wb') as f:
                shutil.copyfileobj(r, f)

        return path

    @property
    def name(self) -> str:
        raise NotImplementedError

    @property
    def version(self) -> str:
        raise NotImplementedError

    @functools.cached_property
    def metadata(self) -> _importlib_metadata.PackageMetadata:
        raise NotImplementedError

    @functools.cached_property
    def tags(self) -> Iterable[packaging.tags.Tag]:
        raise NotImplementedError


class WheelArchive(Archive):
    def __init__(
        self,
        url: str,
        filename: str,
        cache_directory: str,
    ) -> None:
        super().__init__(url, filename, cache_directory)
        match = _WHEEL_NAME_REGEX.match(filename)
        if not match:
            raise ValueError('Invalid wheel name')
        self._wheel_info = match.groupdict()

    @property
    def name(self) -> str:
        return self._wheel_info['distribution']

    @property
    def version(self) -> str:
        return self._wheel_info['version']

    @property
    def _dist_info(self) -> zipfile.Path:
        return zipfile.Path(self.file) / '{}-{}.dist-info'.format(self.name, self.version)

    @functools.cached_property
    def metadata(self) -> _importlib_metadata.PackageMetadata:
        return importlib_metadata.PathDistribution(
            typing.cast(pathlib.Path, self._dist_info)
        ).metadata

    @functools.cached_property
    def tags(self) -> Iterable[packaging.tags.Tag]:
        '''
        # XXX: Using the metadata is expensive so let's generate from the wheel compressed tag, as per PEP 425
        m = email.message_from_bytes((self._dist_info / 'WHEEL').read_bytes())
        for tag in m.get_all('Tag', []):
            yield from packaging.tags.parse_tag(tag)
        '''
        return {
            packaging.tags.Tag(python, abi, plat)
            for python in self._wheel_info['python_tag'].split('.')
            for abi in self._wheel_info['abi_tag'].split('.')
            for plat in self._wheel_info['platform_tag'].split('.')
        }


class Candidate():
    def __init__(
        self,
        name: str,
        version: packaging.version.Version,
        archive: Archive,
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
    def archive(self) -> Archive:
        return self._archive

    @functools.cached_property
    def dependencies(self) -> Iterable[packaging.requirements.Requirement]:
        dependencies: Set[packaging.requirements.Requirement] = set()

        for requirement_str in self.archive.metadata.get_all('Requires-Dist', []):
            requirement = packaging.requirements.Requirement(requirement_str)

            if not requirement.marker:
                # requirements without markers do not need to be evaluated
                if not self.extras:
                    # skip on extras as they are never an extra-only req
                    dependencies.add(requirement)
                continue

            if self._extras:
                # inject base package as a dependency
                dependencies.add(packaging.requirements.Requirement(self.name))

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
        cache_directory: Optional[str],
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
        if packaging.utils.canonicalize_name(requirement.name) != candidate.name:
            return False
        return candidate.version in requirement.specifier

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
        return sum(1 for _ in candidates[identifier])

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
        return self.sort_candidates(candidates)

    def _get_candidates(self, name: str, extras: Optional[Set[str]] = None) -> Iterator[Candidate]:
        url = mousebender.simple.create_project_url(self._package_index_url, name)
        with urllib.request.urlopen(url) as r:
            archives = mousebender.simple.parse_archive_links(r.read().decode())

        for archive_link in archives:
            if self._python_version not in archive_link.requires_python:
                continue

            try:
                archive = Archive.from_archive_link(archive_link, self._cache)
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

            # XXX: Expensive! But currently required because resolvelib does not allow use to postone the validation
            # https://github.com/sarugaku/resolvelib/issues/79
            if not candidate.is_valid(self._supported_tags):
                continue

            yield candidate

    def sort_candidates(self, candidates: Iterable[Candidate]) -> Sequence[Candidate]:
        '''Sort the candidates. Used by find_matches.'''
        return sorted(candidates, key=operator.attrgetter('version'), reverse=True)
