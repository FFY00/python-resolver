# SPDX-License-Identifier: MIT

import operator

from typing import Iterable, Sequence

import resolver


class MinimumDependencyProvider(resolver.Provider):
    def sort_candidates(
        self,
        candidates: Iterable[resolver.Candidate],
    ) -> Sequence[resolver.Candidate]:
        return sorted(candidates, key=operator.attrgetter('version'), reverse=False)
