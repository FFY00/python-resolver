# SPDX-License-Identifier: MIT

import argparse
import os

from typing import Any, Set

import packaging.requirements
import resolvelib

import resolver


class VerboseReporter(resolvelib.BaseReporter):
    def starting(self) -> None:
        print('starting()')

    def starting_round(self, index: int) -> None:
        print(f'starting_round({index})')

    def ending_round(self, index: int, state: Any) -> None:
        print(f'ending_round({index}, ...)')

    def ending(self, state: Any) -> None:
        print('ending(...)')

    def adding_requirement(self, requirement: Any, parent: Any) -> None:
        print(f'  adding_requirement({requirement}, {parent})')

    def backtracking(self, candidate: Any) -> None:
        print(f'  backtracking({candidate})')

    def pinning(self, candidate: Any) -> None:
        print(f'  pinning({candidate})')


def main_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'requirements',
        type=str,
        nargs='+',
        help='requirement strings',
    )
    parser.add_argument(
        '--verbose',
        '-v',
        action='store_true',
        help='enable verbose output',
    )
    return parser


def task() -> None:
    parser = main_parser()
    args = parser.parse_args()

    reporter = VerboseReporter if args.verbose else resolvelib.BaseReporter
    package_resolver = resolvelib.Resolver(
        resolver.Provider('/tmp/resolver-cache' if os.name == 'posix' else None),
        reporter(),
    )
    result = package_resolver.resolve(
        packaging.requirements.Requirement(arg)
        for arg in args.requirements
    )

    seen: Set[str] = set()
    print('\n--- Pinned Candidates ---')
    for key, candidate in result.mapping.items():
        if key.name not in seen:
            print(f'{key.name}: {candidate.name} {candidate.version}')
            seen.add(key.name)

    print('\n--- Dependency Graph ---')
    for key in result.graph:
        targets = ', '.join(str(child) for child in result.graph.iter_children(key))
        print('{} -> {}'.format(key or '(root)', targets))


def main() -> None:
    try:
        task()
    except KeyboardInterrupt:
        print('Exiting...')


def entrypoint() -> None:
    main()


if __name__ == '__main__':
    main()
