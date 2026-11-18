"""Version strings with PEP 440 suffixes must not break dependency parsing.

Odoo 19 pins ``cbor2==5.4.2.post1 ; python_version < '3.11'``.
``string_to_tuple`` raised ``ValueError: invalid literal for int() with
base 10: 'post1'``; the odoo ``__after_compose`` hook failed and the image
was built without the project requirements.
"""

import pytest

from zodoo import iscompatible


@pytest.mark.parametrize(
    "version,expected",
    [
        ("1.0.0", (1, 0, 0)),
        ("2.5", (2, 5)),
        ("5.4.2.post1", (5, 4, 2)),
        ("3.0.0.post1", (3, 0, 0)),
        ("1.0rc1", (1, 0)),
        ("2.1.dev0", (2, 1)),
    ],
)
def test_string_to_tuple(version, expected):
    assert iscompatible.string_to_tuple(version) == expected


def test_post_release_pin_is_compatible():
    reqs = list(iscompatible.parse_requirements("cbor2==5.4.2.post1"))
    assert reqs == [("==", "5.4.2.post1")]
    assert iscompatible.string_to_tuple(reqs[0][1]) == (5, 4, 2)
