from lmreview.specificity import lint, names_in

COMMENTS = {
    "1": {"id": 1, "body": "Rename `num_groups` to `num_object_groups`; see `KVLayerGroupsManager`.",
          "path": "lmcache/v1/gpu_connector/sliding_window.py"},
}


def test_names_in_skips_plain_words():
    assert names_in("check the `result` and `num_groups`") == {"num_groups"}


def test_principle_naming_evidence_identifier_fails():
    e = {"kind": "principle", "evidence": [1], "when": "a diff adds num_groups", "expect": "rename it"}
    assert any("num_groups" in x for x in lint(e, COMMENTS))


def test_principle_naming_evidence_file_fails():
    e = {"kind": "principle", "evidence": [1], "when": "a change to sliding_window.py", "expect": "x"}
    assert lint(e, COMMENTS)


def test_principle_describing_a_class_passes():
    e = {"kind": "principle", "evidence": [1], "when": "a name says less than what it counts",
         "expect": "ask for a name that says what is counted"}
    assert lint(e, COMMENTS) == []


def test_pr_number_fails_for_any_kind():
    e = {"kind": "knowledge", "evidence": [1], "when": "like PR #3869", "expect": "x"}
    assert lint(e, COMMENTS)


def test_knowledge_may_name_project_code():
    e = {"kind": "knowledge", "evidence": [1], "when": "code needs KV group geometry",
         "expect": "KVLayerGroupsManager holds it"}
    assert lint(e, COMMENTS) == []
