from lmreview.reviewer import prompt_template, rules_in_main
from lmreview.state import prompt_id


def test_rulecheck_owns_rules_in_production_prompt():
    pid = prompt_id()
    assert not rules_in_main(pid, f"{pid}+v0043@medium-rc")


def test_main_keeps_rules_without_rule_check():
    pid = prompt_id()
    assert rules_in_main(pid, f"{pid}+v0043@medium")


def test_directives_not_sent_and_dev_context_declared():
    text, ctx = prompt_template(prompt_id())
    assert "<!--" not in text.split("\n", 1)[0]
    assert ctx == ("vllm", "dev")


if __name__ == "__main__":
    for name, f in list(globals().items()):
        if name.startswith("test_"):
            f()
    print("ok")
