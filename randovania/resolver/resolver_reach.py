from __future__ import annotations

import itertools
import math
import typing
from collections import defaultdict

from randovania.game_description.db.resource_node import ResourceNode
from randovania.game_description.game_description import calculate_interesting_resources
from randovania.game_description.requirements import fast_as_set
from randovania.game_description.requirements.base import Requirement
from randovania.game_description.requirements.requirement_and import RequirementAnd
from randovania.game_description.requirements.resource_requirement import PositiveResourceRequirement
from randovania.game_description.resources.resource_type import ResourceType

if typing.TYPE_CHECKING:
    from collections.abc import Iterator

    from randovania.game_description.db.node import Node
    from randovania.game_description.requirements.requirement_list import RequirementList, SatisfiableRequirements
    from randovania.game_description.resources.resource_database import ResourceDatabase
    from randovania.resolver.logic import Logic
    from randovania.resolver.state import State


def _build_satisfiable_requirements(
    logic: Logic,
    all_nodes: tuple[Node | None, ...],
    resource_db: ResourceDatabase,
    requirements_by_node: dict[int, list[Requirement]],
) -> SatisfiableRequirements:
    def _for_node(node_index: int, reqs: list[Requirement]) -> frozenset[RequirementList]:
        additional = logic.get_additional_requirements(all_nodes[node_index]).alternatives

        set_param = set()
        for req in set(reqs):
            set_param.update(fast_as_set.fast_as_alternatives(req, resource_db))

        yield from (a.union(b) for a in set_param for b in additional)

    return frozenset(itertools.chain.from_iterable(_for_node(*it) for it in requirements_by_node.items()))


def _is_requirement_viable_as_additional(requirement: Requirement) -> bool:
    return not isinstance(requirement, PositiveResourceRequirement) or requirement.resource.resource_type not in (
        ResourceType.EVENT,
        ResourceType.NODE_IDENTIFIER,
    )


class ResolverReach:
    _node_indices: tuple[int, ...]
    _energy_at_node: dict[int, int]
    _path_to_node: dict[int, list[int]]
    _satisfiable_requirements: SatisfiableRequirements
    _satisfiable_requirements_for_additionals: SatisfiableRequirements
    _logic: Logic

    @property
    def nodes(self) -> Iterator[Node]:
        all_nodes = self._logic.game.region_list.all_nodes
        for index in self._node_indices:
            yield all_nodes[index]

    @property
    def satisfiable_requirements(self) -> SatisfiableRequirements:
        return self._satisfiable_requirements

    @property
    def satisfiable_requirements_for_additionals(self) -> SatisfiableRequirements:
        return self._satisfiable_requirements_for_additionals

    def path_to_node(self, node: Node) -> tuple[Node, ...]:
        all_nodes = self._logic.game.region_list.all_nodes
        return tuple(all_nodes[part] for part in self._path_to_node[node.node_index])

    def __init__(
        self,
        nodes: dict[int, int],
        path_to_node: dict[int, list[int]],
        requirements: SatisfiableRequirements,
        requirements_for_additionals: SatisfiableRequirements,
        logic: Logic,
    ):
        self._node_indices = tuple(nodes.keys())
        self._energy_at_node = nodes
        self._logic = logic
        self._path_to_node = path_to_node
        self._satisfiable_requirements = requirements
        self._satisfiable_requirements_for_additionals = requirements_for_additionals

    @classmethod
    def calculate_reach(cls, logic: Logic, initial_state: State) -> ResolverReach:
        all_nodes = logic.game.region_list.all_nodes
        checked_nodes: dict[int, int] = {}
        database = initial_state.resource_database
        context = initial_state.node_context()

        # Keys: nodes to check
        # Value: how much energy was available when visiting that node
        nodes_to_check: dict[int, int] = {initial_state.node.node_index: initial_state.energy}

        reach_nodes: dict[int, int] = {}
        requirements_by_node: dict[int, list[Requirement]] = defaultdict(list)
        requirements_excluding_leaving_by_node: dict[int, list[Requirement]] = defaultdict(list)

        path_to_node: dict[int, list[int]] = {
            initial_state.node.node_index: [],
        }

        while nodes_to_check:
            node_index = next(iter(nodes_to_check))
            node = all_nodes[node_index]
            energy = nodes_to_check.pop(node_index)

            if node.heal:
                energy = initial_state.maximum_energy

            checked_nodes[node_index] = energy
            if node_index != initial_state.node.node_index:
                reach_nodes[node_index] = energy

            requirement_to_leave = node.requirement_to_leave(context)

            for target_node, requirement in logic.game.region_list.potential_nodes_from(node, context):
                target_node_index = target_node.node_index

                if (
                    checked_nodes.get(target_node_index, -math.inf) >= energy
                    or nodes_to_check.get(target_node_index, -math.inf) >= energy
                ):
                    continue

                requirement_including_leaving = requirement
                if requirement_to_leave != Requirement.trivial():
                    requirement_including_leaving = RequirementAnd([requirement, requirement_to_leave])
                    if _is_requirement_viable_as_additional(requirement_to_leave):
                        requirement = RequirementAnd([requirement, requirement_to_leave])

                # Check if the normal requirements to reach that node is satisfied
                satisfied = requirement_including_leaving.satisfied(initial_state.resources, energy, database)
                if satisfied:
                    # If it is, check if we additional requirements figured out by backtracking is satisfied
                    satisfied = logic.get_additional_requirements(node).satisfied(
                        initial_state.resources, energy, initial_state.resource_database
                    )

                if satisfied:
                    nodes_to_check[target_node_index] = energy - requirement_including_leaving.damage(
                        initial_state.resources, database
                    )
                    path_to_node[target_node_index] = list(path_to_node[node_index])
                    path_to_node[target_node_index].append(node_index)

                elif target_node:
                    # If we can't go to this node, store the reason in order to build the satisfiable requirements.
                    # Note we ignore the 'additional requirements' here because it'll be added on the end.
                    requirements_by_node[target_node_index].append(requirement_including_leaving)
                    if not requirement.satisfied(initial_state.resources, energy, database):
                        requirements_excluding_leaving_by_node[target_node_index].append(requirement)

        # Discard satisfiable requirements of nodes reachable by other means
        for node_index in set(reach_nodes.keys()).intersection(requirements_by_node.keys()):
            requirements_by_node.pop(node_index)
        for node_index in set(reach_nodes.keys()).intersection(requirements_excluding_leaving_by_node.keys()):
            requirements_excluding_leaving_by_node.pop(node_index)

        if requirements_by_node:
            satisfiable_requirements = _build_satisfiable_requirements(
                logic, all_nodes, initial_state.resource_database, requirements_by_node
            )
            satisfiable_requirements_for_additionals = _build_satisfiable_requirements(
                logic, all_nodes, initial_state.resource_database, requirements_excluding_leaving_by_node
            )
        else:
            satisfiable_requirements = frozenset()
            satisfiable_requirements_for_additionals = frozenset()

        return ResolverReach(
            reach_nodes, path_to_node, satisfiable_requirements, satisfiable_requirements_for_additionals, logic
        )

    def possible_actions(self, state: State) -> Iterator[tuple[ResourceNode, int]]:
        for node in self.collectable_resource_nodes(state):
            additional_requirements = self._logic.get_additional_requirements(node)
            energy = self._energy_at_node[node.node_index]
            if additional_requirements.satisfied(state.resources, energy, state.resource_database):
                yield node, energy
            else:
                self._satisfiable_requirements_for_additionals = self._satisfiable_requirements_for_additionals.union(
                    additional_requirements.alternatives
                )
                self._logic.log_skip_action_missing_requirement(node, self._logic.game)

    def satisfiable_actions(
        self,
        state: State,
        victory_condition: Requirement,
        actions: typing.Iterable[tuple[ResourceNode, int]],
    ) -> Iterator[tuple[ResourceNode, int]]:
        interesting_resources = calculate_interesting_resources(
            self._satisfiable_requirements.union(victory_condition.as_set(state.resource_database).alternatives),
            state.resources,
            state.energy,
            state.resource_database,
        )

        # print(" > satisfiable actions, with {} interesting resources".format(len(interesting_resources)))
        for action, energy in actions:
            for resource, amount in action.resource_gain_on_collect(state.node_context()):
                if resource in interesting_resources:
                    yield action, energy
                    break

    def collectable_resource_nodes(self, state: State) -> Iterator[ResourceNode]:
        for node in self.nodes:
            if not node.is_resource_node:
                continue
            node = typing.cast(ResourceNode, node)
            if node.can_collect(state.node_context()):
                yield node
