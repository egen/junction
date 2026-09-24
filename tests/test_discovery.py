import io

import pytest
from rich.console import Console

from junction.discovery import (
    all_questions, build_platform_config, default_answers, load_answers, normalize_answer, run_discovery,
)

QUIET = Console(file=io.StringIO())


def test_questions_are_unique_and_start_with_platform():
    ids = [q["id"] for q in all_questions()]
    assert ids[:3] == ["agent", "cloud", "iac_tool"]
    assert len(ids) == len(set(ids)) == 16


def test_defaults_run_is_non_interactive():
    result = run_discovery(prefilled={"domain_name": "payments", "agent": "cursor"}, use_defaults=True, out=QUIET)
    assert result.answers["domain_name"] == "payments"
    assert result.answers["agent"] == "cursor"
    assert result.answers["jira_required"] is True
    assert len(result.phase_plan) == 7


def test_dead_and_single_cloud_questions_were_dropped():
    """Regression test: these AWS/ECS-only questions used to be asked but never
    fed any generator — pure friction. They must not come back."""
    ids = {q["id"] for q in all_questions()}
    assert ids.isdisjoint({
        "env_count", "service_count", "shared_services", "resource_type_tokens",
        "module_registry", "msk_cluster_shared", "kms_strategy", "nr_license_strategy",
    })


def test_non_question_keys_pass_through():
    envs = [{"name": "dev", "account_id": "123456789012"}]
    result = run_discovery(prefilled={"environments": envs}, use_defaults=True, out=QUIET)
    assert result.answers["environments"] == envs


def test_normalize_answer():
    by_id = {q["id"]: q for q in all_questions()}
    assert normalize_answer(by_id["jira_required"], "no") is False
    assert normalize_answer({"id": "x", "type": "int"}, "4") == 4
    assert normalize_answer(by_id["agent"], "claude-code") == "claude-code"
    assert normalize_answer(by_id["naming_pattern"], "simple").startswith("{app}")
    with pytest.raises(ValueError):
        normalize_answer(by_id["cloud"], "mars")


def test_load_answers_yaml(tmp_path):
    f = tmp_path / "a.yml"
    f.write_text("jira_required: 'yes'\nenv_names: [dev, prod]\nmodels: {builder: claude-fable-5-1}\n")
    answers = load_answers(f)
    assert answers == {"jira_required": True, "env_names": "dev,prod", "models": {"builder": "claude-fable-5-1"}}


def test_build_platform_config_risk_tiers():
    cfg = build_platform_config({**default_answers(), "env_names": "dev,stage,uat,prod", "cloud": "gcp"})
    assert [e.risk_tier for e in cfg.environments] == ["LOW", "MEDIUM", "MEDIUM", "HIGH"]
    assert cfg.compute_type == "gke"


def test_example_answers_file_answers_every_question():
    from pathlib import Path

    example = Path(__file__).resolve().parent.parent / "examples" / "discovery-answers.example.yml"
    answers = load_answers(example)
    assert {q["id"] for q in all_questions()} <= set(answers)
    assert answers["naming_pattern"].startswith("{domain}-{env}")
    cfg = build_platform_config(answers)
    assert [e.account_id for e in cfg.environments] == ["111111111111", "222222222222", "333333333333"]
