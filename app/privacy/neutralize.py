"""Deterministic removal of Thai gender and seniority style markers."""

import re

from pythainlp.tokenize import word_tokenize
from pythainlp.corpus import thai_words
from pythainlp.util import dict_trie

PARTICLES = frozenset({
    "ครับ", "ครับผม", "คับ", "ค้าบ", "ฮะ", "ฮ่ะ", "ค่ะ", "คะ", "ค่า",
    "จ้ะ", "จ๊ะ", "จ้า", "นะคะ", "นะค่ะ", "นะครับ", "นะคับ", "นะฮะ",
    "เจ้าค่ะ", "เจ้าคะ", "งับ", "ขอรับ",
})
PRONOUNS = frozenset({"ผม", "ดิฉัน", "หนู", "กระผม", "ฉัน", "เค้า", "ข้าพเจ้า"})
KIN_TERMS = frozenset({"พี่", "น้อง"})
MARKERS = PARTICLES | PRONOUNS | KIN_TERMS
_DICTIONARY = dict_trie(thai_words() | MARKERS)


def _tokens(text: str) -> list[str]:
    return word_tokenize(text, engine="newmm", custom_dict=_DICTIONARY, keep_whitespace=True)


def neutralize(text: str) -> str:
    # Token boundaries preserve words such as ค่าใช้จ่าย, คะแนน and คับแคบ.
    tokens = _tokens(text)
    cleaned = "".join(
        "ผู้ให้ความเห็น" if token in PRONOUNS else "" if token in MARKERS else token
        for token in tokens
    )
    return re.sub(r"\s+", " ", cleaned).strip()


def leak_markers(text: str) -> list[str]:
    """Return distinct markers, in their order of appearance."""
    return list(dict.fromkeys(t for t in _tokens(text) if t in MARKERS))
