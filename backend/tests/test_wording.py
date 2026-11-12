"""Sentences the product says to people."""

from app.core.wording import count_of, need


def test_a_count_and_its_noun_agree():
    assert count_of(1, "item") == "1 item"
    assert count_of(3, "item") == "3 items"
    assert count_of(0, "item") == "0 items"
    # A plural that is not "add an s" is given, not guessed.
    assert count_of(2, "shelf", "shelves") == "2 shelves"


def test_the_verb_follows_the_count():
    assert f"{count_of(1, 'product')} {need(1)} restocking" == "1 product needs restocking"
    assert f"{count_of(4, 'product')} {need(4)} restocking" == "4 products need restocking"
