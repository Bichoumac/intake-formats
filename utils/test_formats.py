import copy
import json
import os

import yaml

from helpers import sort_json_keys, YamlDumper, format_expected

constant_fields = {
    "sekoiaio": {
        "intake": {
            "coverage": None,
            "parsing_status": "success",
            "dialect": "test",
            "dialect_uuid": "00000000-0000-0000-0000-000000000000",
        }
    },
    "event": {"id": "00000000-0000-0000-0000-000000000000", "outcome": "success"},
    "ecs": {"version": "1.10.0"},
}

# Tests inside this file are actually parametrized depending on arguments
# See `pytest_generate_tests` in conftest.py for details


def pop_field(event: dict, dotted_field: str):
    """Remove a field from an event, also removing intermediate objects if needed"""
    parts = dotted_field.split(".")

    if parts[0] in event:
        if len(parts) == 1:
            event.pop(parts[0])
        else:
            pop_field(event[parts[0]], ".".join(parts[1:]))

            if event[parts[0]] == {}:
                event.pop(parts[0])


def build_fixed_expectation(parsed_message):
    """Build a new and improved expectation from the parsed message"""
    new_expectation = copy.deepcopy(parsed_message)

    pop_field(new_expectation, "sekoiaio.intake.coverage")
    pop_field(new_expectation, "sekoiaio.intake.parsing_status")
    pop_field(new_expectation, "sekoiaio.intake.parsing_duration_ms")
    pop_field(new_expectation, "sekoiaio.intake.dialect")
    pop_field(new_expectation, "sekoiaio.intake.dialect_uuid")
    pop_field(new_expectation, "event.id")
    pop_field(new_expectation, "event.outcome")
    pop_field(new_expectation, "ecs.version")

    return new_expectation


def test_intakes_produce_expected_messages(request, manager, intakes_root, test_path):
    test_fullpath = os.path.join(intakes_root, test_path)
    with open(test_fullpath) as f:
        testcase = json.load(f)

    parsed = manager.get_parsed_message(test_path)

    # Make tests simpler to write by removing some default values
    merge_dict(testcase["expected"], constant_fields)

    # Ignore the message field
    testcase["expected"]["message"] = parsed["message"]

    # Ignore the parsing_duration_ms which has never the same value
    pop_field(parsed, "sekoiaio.intake.parsing_duration_ms")

    # The order inside `related` is not guaranteed, sort it to make it consistent
    if "related" in parsed:
        for related_field in ["hosts", "ip", "user", "hash"]:
            if related_field in parsed["related"]:
                parsed["related"][related_field] = sorted(parsed["related"][related_field])

    pop_field(parsed, "sekoiaio.intake.parsing_duration_ms")

    expected = testcase["expected"]

    if request.config.getoption("fix_expectations") and parsed != expected:
        testcase["expected"] = build_fixed_expectation(parsed)
        testcase["expected"] = format_expected(testcase["expected"])

        with open(test_fullpath, "w") as out:
            json.dump(testcase, out, indent=2)

    expected_sorted = sort_json_keys(expected)
    parsed_sorted = sort_json_keys(parsed)

    assert parsed_sorted == expected_sorted


def test_intake_format_coverage(manager, module, intake_format):
    coverage = manager.get_coverage(module, intake_format)

    print(f"Coverage: {coverage['percent']}")
    print("Steps missing coverage:\n")

    for missing in coverage.get("missing", []):
        print(missing)

    assert coverage["percent"] >= 75


def prune_taxonomy(format_fields_path, taxonomy):
    """Remove unused keys from fields.yml"""

    # read the field and remove identified keys
    with open(file=format_fields_path, mode="r", encoding="utf-8") as f:
        fields: dict = yaml.safe_load(f)
        for missing_field in taxonomy["unused"]:
            fields.pop(missing_field)

    # write new file
    with open(file=format_fields_path, mode="w", encoding="utf-8") as f:
        updated_fields = yaml.dump(data=fields, Dumper=YamlDumper, sort_keys=True)
        f.write(updated_fields)

    print(f"{len(taxonomy['unused'])} removed from fields.yml")
    print("Please run the following commandline to ensure yaml is properly linted")
    print(f"npx prettier --write {format_fields_path}")


def test_intake_format_unused_fields(request, manager, format_fields_path, module, intake_format):
    taxonomy = manager.get_taxonomy(module, intake_format)
    number_of_unused_fields = len(taxonomy["unused"])

    if number_of_unused_fields > 0:
        print(f"Unused fields ({number_of_unused_fields}) in {format_fields_path}:\n {taxonomy['unused']}")

    # Remove each unused field from fields.yml
    if request.config.getoption("prune_taxonomy"):
        prune_taxonomy(format_fields_path, taxonomy)
    else:
        print("use --prune-taxonomy cleanup unused fields")

    assert number_of_unused_fields == 0


def test_intake_format_missing_fields(manager, module, intake_format):
    taxonomy = manager.get_taxonomy(module, intake_format)

    number_of_missing_fields = len(taxonomy["missing"])

    print(f"Missing fields ({number_of_missing_fields}):\n")

    for missing in taxonomy["missing"]:
        print(missing)

    assert number_of_missing_fields == 0


def merge_dict(dst, src):
    """
    Merge two dict without erasing intermediate nodes from `dst`
    """
    for key, value in src.items():
        if isinstance(value, dict):
            if key not in dst:
                dst[key] = {}
            merge_dict(dst[key], value)
        else:
            dst[key] = value
