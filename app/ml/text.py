"""Spanish text preprocessing for the classifier.

Deliberately dependency-free (no nltk, no spacy): the pipeline has to run the
same on any teammate's laptop, in CI and inside the container, without
downloading models first.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

# Rioplatense Spanish stopwords plus filler words that show up in every claim.
# fmt: off  (one word per line would make this unreadable)
STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "al",
        "algo",
        "alguna",
        "algunas",
        "alguno",
        "algunos",
        "ante",
        "antes",
        "aqui",
        "asi",
        "aun",
        "aunque",
        "cada",
        "como",
        "con",
        "contra",
        "cual",
        "cuales",
        "cuando",
        "de",
        "del",
        "desde",
        "donde",
        "dos",
        "el",
        "ella",
        "ellas",
        "ello",
        "ellos",
        "en",
        "entre",
        "era",
        "eran",
        "es",
        "esa",
        "esas",
        "ese",
        "eso",
        "esos",
        "esta",
        "estan",
        "estas",
        "este",
        "esto",
        "estos",
        "fue",
        "fueron",
        "ha",
        "hace",
        "hacen",
        "hacia",
        "han",
        "hasta",
        "hay",
        "la",
        "las",
        "le",
        "les",
        "lo",
        "los",
        "mas",
        "me",
        "mi",
        "mis",
        "mucho",
        "muy",
        "nada",
        "ni",
        "no",
        "nos",
        "nuestra",
        "nuestro",
        "o",
        "otra",
        "otras",
        "otro",
        "otros",
        "para",
        "pero",
        "poco",
        "por",
        "porque",
        "que",
        "quien",
        "se",
        "ser",
        "si",
        "sin",
        "sobre",
        "solo",
        "son",
        "su",
        "sus",
        "tambien",
        "tan",
        "tanto",
        "te",
        "tiene",
        "tienen",
        "toda",
        "todas",
        "todo",
        "todos",
        "tras",
        "un",
        "una",
        "unas",
        "uno",
        "unos",
        "ya",
        "yo",
        # Openers and boilerplate that carry no signal about the actual problem.
        "hola",
        "buenas",
        "buenos",
        "dias",
        "tardes",
        "noches",
        "favor",
        "gracias",
        "quisiera",
        "queria",
        "necesito",
        "reclamo",
        "denuncia",
        "vecino",
        "vecina",
        "calle",
        "numero",
        "altura",
        "zona",
    }
)
# fmt: on

_NO_ALFANUM = re.compile(r"[^a-z0-9\s]")
_ESPACIOS = re.compile(r"\s+")


def normalizar(texto: str) -> str:
    """Lowercase, accent-stripped, punctuation-free."""
    sin_tildes = unicodedata.normalize("NFKD", texto.lower())
    sin_tildes = "".join(c for c in sin_tildes if not unicodedata.combining(c))
    return _ESPACIOS.sub(" ", _NO_ALFANUM.sub(" ", sin_tildes)).strip()


# Below this length stripping an ending destroys the word ("gas" -> "ga").
LARGO_MINIMO_RAIZ = 4


def raiz(palabra: str) -> str:
    """Crude Spanish stemmer: plural, then gender/verb vowel.

    postes -> post, poste -> post; apagada -> apagad, apagado -> apagad;
    fugas -> fuga, fuga -> fuga (too short to strip further).
    """
    if len(palabra) > LARGO_MINIMO_RAIZ and palabra.endswith("es"):
        palabra = palabra[:-2]
    elif len(palabra) > LARGO_MINIMO_RAIZ and palabra.endswith("s"):
        palabra = palabra[:-1]
    if len(palabra) >= LARGO_MINIMO_RAIZ and palabra[-1] in "aoe":
        palabra = palabra[:-1]
    return palabra


def tokenizar(texto: str, *, con_bigramas: bool = True, con_raices: bool = False) -> list[str]:
    """Unigrams (stopwords removed) plus bigrams.

    Bigrams matter: "fuga gas" or "cable caido" carry far more signal about
    category and priority than either word on its own.

    `con_raices` stems every word first, so "apagada" and "apagado" count as
    the same term. Off by default: the urgency lexicon is matched against the
    plain words.
    """
    palabras = [
        palabra
        for palabra in normalizar(texto).split()
        if len(palabra) >= 3 and palabra not in STOPWORDS
    ]
    if con_raices:
        palabras = [raiz(palabra) for palabra in palabras]
    if not con_bigramas or len(palabras) < 2:
        return palabras

    bigramas = [f"{a}_{b}" for a, b in zip(palabras, palabras[1:], strict=False)]
    return palabras + bigramas


def contiene_alguno(tokens: Iterable[str], terminos: Iterable[str]) -> list[str]:
    """Lexicon terms present in the tokens (used to build the evidence list)."""
    tokens_set = set(tokens)
    return [t for t in terminos if t in tokens_set]
