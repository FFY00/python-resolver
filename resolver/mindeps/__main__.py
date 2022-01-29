# SPDX-License-Identifier: MIT

import argparse
import operator
import os
import os.path
import pathlib
import tempfile

from typing import Iterable, Sequence, Set, List, Optional, Dict

import packaging.markers
import packaging.requirements
import resolvelib

import resolver.__main__
import resolver.archive
import resolver.mindeps


try:
    import importlib.metadata as importlib_metadata
except ImportError:
    import importlib_metadata  # type: ignore


_MARKER_KEYS = (
    'implementation_version',
    'platform_python_implementation',
    'implementation_name',
    'python_full_version',
    'platform_release',
    'platform_version',
    'platform_machine',
    'platform_system',
    'python_version',
    'sys_platform',
    'os_name',
    'python_implementation',
)


def _project_requirements() -> Sequence[str]:
    import build
    import pep517.wrappers

    builder = build.ProjectBuilder('.', runner=pep517.wrappers.quiet_subprocess_runner)
    with tempfile.TemporaryDirectory() as tmpdir:
        return importlib_metadata.PathDistribution(
            pathlib.Path(builder.metadata_path(tmpdir)),
        ).metadata.get_all('Requires-Dist', [])


def main_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'requirements',
        type=str,
        nargs='*',
        help='requirement strings',
    )
    parser.add_argument(
        '--verbose',
        '-v',
        action='store_true',
        help='enable verbose output',
    )
    parser.add_argument(
        '--write',
        '-w',
        type=str,
        help='write to file',
    )
    parser.add_argument(
        '--extras',
        '-e',
        type=str,
        default=argparse.SUPPRESS,
        nargs='*',
        help='project extras',
    )
    marker_args = parser.add_argument_group(
        title='marker arguments',
        description='values used to evaluate the project requirements',
    )
    for key in _MARKER_KEYS:
        marker_args.add_argument(
            f'--{key}',
            type=str,
            default=argparse.SUPPRESS,
        )
    return parser


class MinimumDependencyProvider(resolver.Provider):
    def sort_candidates(
        self,
        candidates: Iterable[resolver.Candidate],
    ) -> Sequence[resolver.Candidate]:
        return sorted(candidates, key=operator.attrgetter('version'), reverse=False)


def get_min_deps(
    reporter: resolvelib.BaseReporter,
    requirements: List[str],
    extras: Optional[Set[str]] = None,
    markers: Optional[Dict[str, str]] = None
) -> Dict[str, str]:
    package_resolver = resolvelib.Resolver(
        MinimumDependencyProvider(
            '/tmp/resolver-cache' if os.name == 'posix' else None
        ),
        reporter(),
    )

    requirements: Iterable[packaging.requirements.Requirement] = map(
        packaging.requirements.Requirement, requirements
    )

    extras = extras.copy() | {''}
    if markers is not None and any(marker in _MARKER_KEYS for marker in markers):
        marker_env = {
            k: v for k, v in markers.items()
            if k in _MARKER_KEYS
        }
    else:
        marker_env = packaging.markers.default_environment()

    resolver_requirements: Set[packaging.requirements.Requirement] = set()
    for requirement in list(requirements):
        for extra in extras:
            if not requirement.marker:
                resolver_requirements.add(requirement)
            elif requirement.marker.evaluate(marker_env | {'extra': extra}):
                requirement.marker = None
                resolver_requirements.add(requirement)

    result = package_resolver.resolve(resolver_requirements)

    pinned = {
        candidate.name: candidate.version
        for candidate in result.mapping.values()
    }

    return pinned


def task() -> None:  # noqa: C901
    parser = main_parser()
    args = parser.parse_args()

    if args.requirements:
        for bad_arg in _MARKER_KEYS + ('extras',):
            if bad_arg in args:
                resolver.__main__._error(f'Option --{bad_arg} not supported when specifying bare requirements')

    reporter = resolver.__main__.VerboseReporter if args.verbose else resolvelib.BaseReporter

    if args.verbose:
        print('\n--- Solution ---')

    pinned = get_min_deps(
        reporter=reporter,
        requirements=args.requirements or _project_requirements(),
        extras=set(vars(args).get('extras', {})),
        markers=vars(args)
    )
    for name, version in pinned.items():
        print(f'{name}=={str(version)}')

    if args.write:
        resolver.__main__.write_pinned(args.write, pinned)


def main() -> None:
    try:
        task()
    except KeyboardInterrupt:
        print('Exiting...')
    except resolvelib.resolvers.ResolutionImpossible:
        resolver.__main__._error('No matches found')
    except Exception as e:
        resolver.__main__._error(str(e))


def entrypoint() -> None:
    main()


if __name__ == '__main__':
    main()
