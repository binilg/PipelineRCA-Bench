from .naive_agent import NaiveEchoAgent  # noqa: F401
from .keyword_agent import KeywordHeuristicAgent  # noqa: F401

AGENTS = {
    "naive": NaiveEchoAgent,
    "keyword": KeywordHeuristicAgent,
}
