import hashlib

from retroperfect.hashing import hash_bytes, nes_ra_hash
from retroperfect.metadata import parse_no_intro_name


def test_nes_ra_hash_ignores_ines_header() -> None:
    payload = b"actual-rom-data"
    data = b"NES\x1a" + bytes(12) + payload
    assert nes_ra_hash(data) == hashlib.md5(payload).hexdigest()
    assert hash_bytes(data).md5 != nes_ra_hash(data)


def test_parse_no_intro_metadata() -> None:
    metadata = parse_no_intro_name("Example Game (Spain) (En,Es) (Rev 2) (Beta).nes")
    assert metadata.title == "Example Game"
    assert "Spain" in metadata.regions
    assert "English" in metadata.languages
    assert "Spanish" in metadata.languages
    assert metadata.revision == 2
    assert "Beta" in metadata.tags


def test_parse_more_no_intro_metadata_shapes() -> None:
    metadata = parse_no_intro_name("Example (Europe) (En,Fr,De,Es,It) (Rev A) (Virtual Console).nes")
    assert "Europe" in metadata.regions
    assert "Multi" in metadata.languages
    assert "Spanish" in metadata.languages
    assert metadata.revision == 1
    assert "Virtual Console" in metadata.tags


def test_parse_no_intro_v_revision_without_space() -> None:
    metadata = parse_no_intro_name("Family BASIC (Japan) (v2.1).nes")
    assert metadata.version == "2.1"
    assert metadata.revision == 1
