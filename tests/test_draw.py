import random

from draw import find_pairing


def two_cycles(pairing: dict[int, int]) -> list[tuple[int, int]]:
    return [(giver, receiver) for giver, receiver in pairing.items() if pairing.get(receiver) == giver]


def test_needs_three_people():
    assert find_pairing([], {}, random.Random(0)) is None
    assert find_pairing([1, 2], {}, random.Random(0)) is None


def test_everyone_gets_exactly_one_receiver():
    ids = list(range(1, 8))
    for seed in range(50):
        pairing = find_pairing(ids, {}, random.Random(seed))
        assert pairing is not None
        assert sorted(pairing) == ids
        assert sorted(pairing.values()) == ids


def test_nobody_draws_themselves_and_no_two_cycles():
    ids = list(range(1, 9))
    for seed in range(50):
        pairing = find_pairing(ids, {}, random.Random(seed))
        assert pairing is not None
        assert all(giver != receiver for giver, receiver in pairing.items())
        assert two_cycles(pairing) == []


def test_respects_exclusions():
    ids = [1, 2, 3, 4, 5]
    exclusions = {1: {2, 3}, 2: {1}}
    for seed in range(50):
        pairing = find_pairing(ids, exclusions, random.Random(seed))
        assert pairing is not None
        for giver, excluded in exclusions.items():
            assert pairing[giver] not in excluded


def test_impossible_when_someone_excluded_everybody():
    assert find_pairing([1, 2, 3], {1: {2, 3}}, random.Random(0)) is None


def test_impossible_when_the_only_option_is_a_two_cycle():
    # 1 and 2 can only take each other, and that leaves 3 and 4 as a 2-cycle too.
    exclusions = {1: {3, 4}, 2: {3, 4}}
    assert find_pairing([1, 2, 3, 4], exclusions, random.Random(0)) is None


def test_same_seed_same_pairing():
    ids = list(range(1, 7))
    assert find_pairing(ids, {}, random.Random(7)) == find_pairing(ids, {}, random.Random(7))


def test_three_people_always_a_single_cycle():
    for seed in range(20):
        pairing = find_pairing([1, 2, 3], {}, random.Random(seed))
        assert pairing is not None
        assert two_cycles(pairing) == []
        assert len(set(pairing.values())) == 3
