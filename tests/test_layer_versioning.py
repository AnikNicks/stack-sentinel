from pulse import layer_versioning


def _layers(commit_sha="abc123", change_event=None):
    return {"repo_cicd": {"commit_sha": commit_sha, "change_event": change_event}}


def test_no_prior_snapshot_and_no_change_event_is_no_change():
    event = layer_versioning.detect_layer_change("repo_cicd", None, _layers())
    assert event.change_kind == "no_change"
    assert event.from_version is None
    assert event.to_version == "abc123"


def test_reversible_change_event_is_routine():
    curr = _layers("def456", {"type": "deploy", "description": "routine deploy", "reversible": True})
    event = layer_versioning.detect_layer_change("repo_cicd", _layers("abc123"), curr)
    assert event.change_kind == "routine_version_change"
    assert event.from_version == "abc123"
    assert event.to_version == "def456"


def test_non_reversible_change_event_is_destructive_regardless_of_layer():
    for layer, field in layer_versioning.LAYER_VERSION_FIELDS.items():
        curr_layers = {layer: {field: "v2", "change_event": {
            "type": "schema_migration", "description": "drop table", "reversible": False,
        }}}
        prev_layers = {layer: {field: "v1", "change_event": None}}
        event = layer_versioning.detect_layer_change(layer, prev_layers, curr_layers)
        assert event.change_kind == "destructive_change_candidate", f"layer {layer} should be destructive"


def test_unknown_layer_returns_none():
    assert layer_versioning.detect_layer_change("not_a_layer", None, {}) is None


def test_find_layer_changes_in_history_skips_no_change_cycles():
    entries = [
        {"metric_snapshot": {"layers": _layers("abc123")}},
        {"metric_snapshot": {"layers": _layers("abc123")}},  # no change
        {"metric_snapshot": {"layers": _layers("def456", {"type": "deploy", "description": "x", "reversible": True})}},
    ]
    found = layer_versioning.find_layer_changes_in_history("repo_cicd", entries)
    assert len(found) == 1
    _, curr_entry, event = found[0]
    assert event.change_kind == "routine_version_change"
    assert curr_entry is entries[2]
