#!/usr/bin/env python3
import copy
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
from report_integer_learning_replay import load_records, make_report, paired_bootstrap


def attempt(kind, objective, accepted=True, fallback=False, recovery_failed=False):
    optimal = accepted or recovery_failed
    qp = kind == "qp"
    return {
        "assignment": [0, 0, 0, 0, 0] if qp else ([] if kind == "miqp" else None),
        "kind": kind, "status": 2 if optimal else 11, "solve_attempted": True,
        "accepted": accepted, "fallback": fallback,
        "objective": objective if optimal else None,
        "raw_objective": objective if optimal else None,
        "residuals": {"valid": True, "bounds": 0., "constraints": 0., "integrality": 0., "objective": 0.}
        if optimal else None,
        "original_residuals": {"valid": True, "bounds": 0., "constraints": 0., "integrality": 0., "objective": 0.}
        if optimal and qp else None,
        "wall_seconds": .01, "backend_seconds": .005, "prepare_seconds": .001 if qp else 0.,
        "adapter_seconds": .004 if qp else .005, "error": "" if accepted else "assignment recovery failed",
    }


def method(name, objective, latency, *, fallback=False, success=True):
    kind = "original" if name == "original" else ("miqp" if fallback else "qp")
    attempts = [attempt(kind, objective, accepted=success, fallback=fallback, recovery_failed=not success)]
    proposed = [[0, 0, 0, 0, 0]] if kind == "qp" else []
    fallback_used = fallback
    fallback_reason = "model_missing" if fallback else ""
    if not success and kind == "qp":
        attempts.append(attempt("miqp", objective, accepted=False, fallback=True, recovery_failed=True))
        fallback_used, fallback_reason = True, "candidate_exhausted"
    return {"method": name, "proposed_assignments": proposed,
            "chosen_assignment": [0, 0, 0, 0, 0] if success else None,
            "history_available": name == "previous", "attempts": attempts,
            "fallback_used": fallback_used, "fallback_reason": fallback_reason,
            "timing": {"ranking_seconds": .001 if proposed else 0.,
                       "backend_seconds": sum(item["backend_seconds"] for item in attempts),
                       "prepare_seconds": sum(item["prepare_seconds"] for item in attempts),
                       "adapter_seconds": sum(item["adapter_seconds"] for item in attempts),
                       "fallback_seconds": .01 if fallback_used else 0., "total_seconds": latency}}


def row(scene, request, factor="0", original_objective=100., candidate_objective=102., candidate_success=True):
    latency = .012 if candidate_success else .022
    return {"schema_version": 1, "kind": "sando_integer_replay", "excluded": False,
            "scene_id": scene, "episode_id": "episode", "request_id": str(request),
            "factor_id": str(factor), "source_id": "source-sha", "config_id": "config-sha",
            "methods": {
                "original": method("original", original_objective, .010),
                "previous": method("previous", candidate_objective, latency, success=candidate_success),
                "bc": method("bc", candidate_objective, latency, success=candidate_success),
                "cost": method("cost", candidate_objective, .010, fallback=True),
                "closed_loop": method("closed_loop", candidate_objective, latency, success=candidate_success),
            }}


def main():
    records = [row("n50-d0-seed200", 1), row("n50-d0-seed201", 2, candidate_objective=103),
               row("n50-d0.65-seed200", 3, candidate_success=False)]
    report = make_report(records, seed=7)
    assert report["evidence"]["valid_instance_count"] == 3
    assert report["environments"]["static"]["methods"]["bc"]["latency_ms"]["p50"] == 12.
    bc = report["environments"]["static"]["methods"]["bc"]
    assert bc["paired_to_original"]["common_scene_count"] == 2
    assert bc["paired_to_original"]["objective_gap"]["both_success_instance_count"] == 2
    assert bc["paired_to_original"]["objective_gap"]["absolute_raw"]["n"] == 2
    assert bc["paired_to_original"]["objective_gap"]["scaled"]["n"] == 2
    assert report["environments"]["dynamic"]["methods"]["bc"]["successful_instance_count"] == 0
    assert report["environments"]["static"]["methods"]["cost"]["fallback"]["count"] == 2
    assert records[0]["methods"]["cost"]["attempts"][0]["assignment"] == []
    assert make_report([records[2]])["evidence"]["valid_instance_count"] == 1
    assert report["latency_scope"].startswith("frozen replay")
    assert paired_bootstrap([1., 3.], seed=7)["unit"] == "scene"

    def rejected(change, fragment):
        malformed = copy.deepcopy(records[0])
        change(malformed)
        result = make_report([malformed])
        assert result["evidence"]["valid_instance_count"] == 0
        assert fragment in result["evidence"]["exclusions"][0]["error"]

    rejected(lambda value: value["methods"]["bc"].update(attempts=[]), "nonempty")
    rejected(lambda value: value["methods"]["bc"]["attempts"][0].update(assignment=[1, 1, 1, 1, 1]),
             "follow proposed")
    rejected(lambda value: value["methods"]["bc"].update(fallback_used=True), "fallback path")
    rejected(lambda value: value["methods"]["bc"]["attempts"][0]["residuals"].pop("bounds"), "required")
    rejected(lambda value: value["methods"]["bc"]["attempts"][0]["residuals"].update(bounds=1.0),
             "residual tolerance")
    rejected(lambda value: value["methods"]["bc"]["attempts"][0].update(original_residuals=None),
             "accepted qp")
    rejected(lambda value: value["methods"]["bc"]["timing"].update(total_seconds=.001), "total_seconds")
    rejected(lambda value: value["methods"]["bc"]["timing"].update(backend_seconds=.004), "attempt total")
    exhausted = copy.deepcopy(records[2])
    exhausted["methods"]["bc"]["proposed_assignments"].append([1, 1, 1, 1, 1])
    exhaustion_report = make_report([exhausted])
    assert "candidate exhaustion" in exhaustion_report["evidence"]["exclusions"][0]["error"]

    def duplicate_acceptance(value):
        duplicate = copy.deepcopy(value["methods"]["bc"]["attempts"][0])
        duplicate["assignment"] = [1, 1, 1, 1, 1]
        value["methods"]["bc"]["proposed_assignments"].append(duplicate["assignment"])
        value["methods"]["bc"]["attempts"].append(duplicate)
        value["methods"]["bc"]["timing"].update(backend_seconds=.01, prepare_seconds=.002,
                                                adapter_seconds=.008, total_seconds=.021)

    rejected(duplicate_acceptance, "continue after acceptance")

    interrupted = copy.deepcopy(records[0])
    attempt_record = interrupted["methods"]["original"]["attempts"][0]
    attempt_record.update(status=11, accepted=False, objective=None, raw_objective=None, residuals=None,
                          original_residuals=None, error="interrupted")
    interrupted["methods"]["original"]["chosen_assignment"] = None
    assert make_report([interrupted])["evidence"]["valid_instance_count"] == 1

    different_factor = row("n50-d0-seed200", 1, factor="1")
    factor_report = make_report([records[0], different_factor])
    assert factor_report["evidence"]["valid_instance_count"] == 2
    assert factor_report["evidence"]["excluded_record_count"] == 0
    assert factor_report["environments"]["static"]["scene_count"] == 1
    accepted = factor_report["environments"]["static"]["methods"]["bc"]["accepted_residual_coverage"]
    assert accepted["checked"] == accepted["expected"] == 2
    assert accepted["violations"] == 0

    with tempfile.TemporaryDirectory() as directory:
        instances = Path(directory) / "instances.jsonl"
        identity_keys = ("scene_id", "episode_id", "request_id", "factor_id", "source_id", "config_id")
        expected_instances = [
            {key: records[0][key] for key in identity_keys},
            {key: different_factor[key] for key in identity_keys},
        ]
        instances.write_text("\n".join(json.dumps(value) for value in expected_instances) +
                             "\n", encoding="utf-8")
        covered = make_report([records[0], different_factor], instances=instances)
        coverage = covered["evidence"]["instance_coverage"]
        assert coverage["complete"] and coverage["input_instance_count"] == 2

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "replay.jsonl"
        path.write_text("\n".join([json.dumps(records[0]), json.dumps(records[0]), "{bad json"]
                         ) + "\n", encoding="utf-8")
        loaded = load_records(path)
        assert sum(item.get("excluded", False) for item in loaded) == 2
        assert any(item.get("error") == "duplicate_instance_id" for item in loaded)
    print("integer replay report tests passed")


if __name__ == "__main__":
    main()
