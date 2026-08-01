from metronome.costs.vendors import ALL, dagster, gcp, github, hex, snowflake


def test_all_contains_every_vendor_module_exactly_once():
    assert set(ALL) == {dagster, gcp, github, hex, snowflake}
    assert len(ALL) == len(set(ALL))
