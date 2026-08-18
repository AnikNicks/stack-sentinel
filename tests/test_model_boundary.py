from pulse import model_boundary


def _entry(version="v2", model="model-a"):
    return {"agent_version": version, "model": model}


def test_no_boundary_when_nothing_changed():
    assert model_boundary.detect_boundary(_entry(), _entry()) is None


def test_version_boundary_when_only_version_changes():
    prev = _entry(version="v2", model="model-a")
    curr = _entry(version="v3", model="model-a")
    assert model_boundary.detect_boundary(prev, curr) == "version_boundary"


def test_model_boundary_when_only_model_changes():
    prev = _entry(version="v2", model="model-a")
    curr = _entry(version="v2", model="model-b")
    assert model_boundary.detect_boundary(prev, curr) == "model_boundary"


def test_compound_boundary_when_both_change():
    prev = _entry(version="v2", model="model-a")
    curr = _entry(version="v3", model="model-b")
    assert model_boundary.detect_boundary(prev, curr) == "compound_boundary"


def test_find_boundary_in_history_walks_consecutive_pairs():
    history = [
        _entry("v1", "model-a"),
        _entry("v1", "model-a"),   # no boundary
        _entry("v2", "model-a"),   # version_boundary
        _entry("v2", "model-b"),   # model_boundary
    ]
    found = model_boundary.find_boundary_in_history(history)
    kinds = [kind for _, _, kind in found]
    assert kinds == ["version_boundary", "model_boundary"]
