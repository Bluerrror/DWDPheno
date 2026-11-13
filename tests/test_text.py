import pytest

from dwdpheno._text import fold, matches, select_names, squash


@pytest.mark.parametrize("text, folded", [
    ("Göttingen", "goettingen"),
    ("Landkreis Kassel", "landkreis kassel"),
    ("Straße", "strasse"),
    ("ÄÖÜ äöü", "aeoeue aeoeue"),
    ("Halle (Saale)", "halle saale"),
    ("Apfel_fruehe_Reife", "apfel fruehe reife"),
    ("Zucker-Rübe", "zucker ruebe"),
    ("  Lübeck-Sankt   Jürgen ", "luebeck sankt juergen"),
    ("Besançon, Côte", "besancon cote"),
    (None, ""),
])
def test_fold(text, folded):
    assert fold(text) == folded


def test_squash():
    assert squash("Apfel, frühe Reife") == squash("Apfel_fruehe_Reife") == "apfelfruehereife"
    assert squash("Pflaume_fruehreifend") == squash("Pflaume, frühe Reife")
    assert squash("Pflaume_spaetreifend") == squash("Pflaume, späte Reife")
    assert squash("Birke (alle Arten)") == squash("Birke_alleArten")


def test_matches_is_token_wise():
    assert matches("Landkreis Kassel", "Kassel rural district Landkreis")
    assert matches("Kassel rural district", "Kassel rural district Landkreis")
    assert matches("Kassel", "Kassel urban district Kreisfreie Stadt")
    assert not matches("Landkreis Kassel", "Kassel urban district Kreisfreie Stadt")
    assert matches("goettingen", "Göttingen")
    assert matches("Göttingen", "Goettingen")
    assert matches("", "anything")


CANDS = [
    ["winter wheat", "Winterweizen", "Winterweizen"],
    ["spring wheat", "Sommerweizen", "Sommerweizen"],
    ["apple", "Apfel", "Apfel"],
    ["apple (early ripeness)", "Apfel, frühe Reife", "Apfel_fruehe_Reife"],
    ["ash", "Esche", "Esche"],
    ["rowan", "Eberesche", "Eberesche"],
    ["large leaved lime", "Sommer-Linde", "Sommer-Linde"],
    ["small leafed lime", "Winter-Linde", "Winter-Linde"],
    ["sugar beet", "Zucker-Rübe", "Zucker-Ruebe"],
]


@pytest.mark.parametrize("query, expected", [
    ("apple", [2]),                       # exact English name: only that crop
    ("Apfel", [2]),                       # exact German name
    ("Apfel_fruehe_Reife", [3]),          # exact token
    ("apple early", [3]),                 # word prefixes
    ("app", [2, 3]),
    ("wheat", [0, 1]),                    # winter + spring wheat
    ("Winter Wheat", [0]),
    ("ash", [4]),                         # not rowan (Eberesche)
    ("Linde", [6, 7]),
    ("lime", [6, 7]),
    ("Zucker-Rübe", [8]),
    ("zuckerruebe", []),                  # not a word prefix of "zucker ruebe"
    ("banana", []),
    ("", []),
])
def test_select_names(query, expected):
    assert select_names(query, CANDS) == expected
