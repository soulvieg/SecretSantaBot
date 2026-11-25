import random


def find_pairing(
    ids: list[int],
    exclusions: dict[int, set[int]],
    rng: random.Random,
) -> dict[int, int] | None:
    """Pair every giver with a receiver.

    Constraints: nobody draws themselves, no 2-cycles (A->B and B->A) and
    nobody draws someone they excluded. Returns None when no valid pairing
    exists, so the caller can leave the circle untouched.
    """
    if len(ids) < 3:
        return None

    givers = list(ids)
    rng.shuffle(givers)
    assignment: dict[int, int] = {}
    taken: set[int] = set()

    def candidates(giver: int) -> list[int]:
        options = [
            receiver
            for receiver in ids
            if receiver != giver
            and receiver not in taken
            and receiver not in exclusions.get(giver, set())
            and assignment.get(receiver) != giver
        ]
        rng.shuffle(options)
        return options

    def solve(index: int) -> bool:
        if index == len(givers):
            return True
        giver = givers[index]
        for receiver in candidates(giver):
            assignment[giver] = receiver
            taken.add(receiver)
            if solve(index + 1):
                return True
            taken.discard(receiver)
            del assignment[giver]
        return False

    if solve(0):
        return dict(assignment)
    return None
