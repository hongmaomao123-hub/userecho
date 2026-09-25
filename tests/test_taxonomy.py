"""Check the fixed taxonomy contract against the authoritative PRD."""

import re
from pathlib import Path

import pytest
import yaml
from yaml.nodes import MappingNode, ScalarNode


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def taxonomy_text():
    return (ROOT / "config" / "taxonomy.yaml").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def topics(taxonomy_text):
    document = yaml.safe_load(taxonomy_text)
    assert isinstance(document, dict)
    assert isinstance(document["topics"], dict)
    return document["topics"]


@pytest.fixture(scope="module")
def raw_codes(taxonomy_text):
    # Inspect YAML nodes before dict construction can hide duplicate keys.
    document = yaml.compose(taxonomy_text, Loader=yaml.SafeLoader)
    assert isinstance(document, MappingNode)
    topic_nodes = [value for key, value in document.value if key.value == "topics"]
    assert len(topic_nodes) == 1
    assert isinstance(topic_nodes[0], MappingNode)
    keys = [key for key, _ in topic_nodes[0].value]
    assert all(isinstance(key, ScalarNode) and key.tag == "tag:yaml.org,2002:str"
               for key in keys)
    return [key.value for key in keys]


def test_yaml_parses(taxonomy_text):
    document = yaml.safe_load(taxonomy_text)
    assert isinstance(document, dict)
    assert document["version"] == "1.3"
    assert isinstance(document["topics"], dict)


def test_topic_codes_exactly_match_prd(topics):
    prd = (ROOT / "docs" / "PRD.md").read_text(encoding="utf-8")
    section = prd.split("### 3.1", 1)[1].split("### 3.2", 1)[0]
    table = section.split("| code |", 1)[1].split("\n\n", 1)[0]
    codes = re.findall(r"^\| ([a-z_]+) \|", table, flags=re.MULTILINE)
    assert len(codes) == len(set(codes)) == 10
    assert set(topics) == set(codes), "Missing or non-PRD topic codes"


def test_topic_codes_are_unique(raw_codes):
    assert len(raw_codes) == len(set(raw_codes))


def test_topics_have_exact_fixed_fields(topics):
    fields = {"name_zh", "definition", "include", "exclude", "confused_with"}
    for code, topic in topics.items():
        assert isinstance(topic, dict), code
        assert set(topic) == fields, code


def test_topic_text_fields_are_nonempty_strings(topics):
    for code, topic in topics.items():
        for field in ("name_zh", "definition"):
            assert isinstance(topic[field], str), (code, field)
            assert topic[field].strip(), (code, field)


@pytest.mark.parametrize("field", ["include", "exclude", "confused_with"])
def test_topic_list_fields_contain_strings(topics, field):
    for code, topic in topics.items():
        assert isinstance(topic[field], list), (code, field)
        assert all(isinstance(value, str) and value.strip() for value in topic[field]), (code, field)


def test_other_exists_exactly_once(raw_codes):
    assert raw_codes.count("other") == 1


def test_confused_with_references_existing_codes(topics):
    for code, topic in topics.items():
        assert set(topic["confused_with"]) <= set(topics), code


def test_confused_with_does_not_reference_self(topics):
    for code, topic in topics.items():
        assert code not in topic["confused_with"], code
