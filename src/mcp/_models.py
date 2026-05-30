"""Pydantic base models + shared types for every MCP tool.

The ``CaveatedResponse`` base is load-bearing for the consultation's
caveats-contract: every aggregated tool response inherits from it, so
the ``caveats: list[str]`` field is required at the schema layer. A
future contributor cannot accidentally return a response shape that
drops the field — Pydantic raises at validation time.

Schema-level enforcement is one half of the contract; per the
reviewer's Q4 push, behavior tests in each sub-arc's test module
assert the right caveat strings fire under their triggering
conditions (e.g. survivorship bias for universe queries, multiple-
comparisons warning when a heatmap grid exceeds 100 cells).
"""
from __future__ import annotations

from typing import Callable

from pydantic import BaseModel, Field, field_validator


class CaveatedResponse(BaseModel):
    """Base for every aggregated-data MCP tool response.

    ``caveats: list[str]`` is REQUIRED (not optional, not default-empty)
    so missing-field accidents fire at validation time. Empty list is
    valid — a tool may legitimately have no caveats for a given input
    — but the field must always be present.

    The validator also pins ``str``-element typing so a tool can't
    accidentally return ``caveats=[{"text": "..."}]`` (rich-text dicts
    leak structure assumptions across tool boundaries; flat strings
    are the canonical caveat shape).
    """
    caveats: list[str] = Field(
        ...,
        description=(
            "Honesty caveats the consumer Claude must surface to the "
            "operator. Empty list = nothing to flag; missing field = "
            "schema bug. Always check this field before presenting "
            "results."
        ),
    )

    @field_validator("caveats")
    @classmethod
    def _caveats_must_be_strings(cls, v: list[str]) -> list[str]:
        if not isinstance(v, list):
            raise ValueError("caveats must be a list")
        for i, item in enumerate(v):
            if not isinstance(item, str):
                raise ValueError(
                    f"caveats[{i}] must be a str, got {type(item).__name__}"
                )
        return v


class ToolEntry(BaseModel):
    """Registry entry for one MCP tool.

    Each sub-arc module (universe.py, spot_options.py, ...) exports a
    ``register_*()`` function returning a list of ToolEntry; the
    server's ``build_server()`` aggregates them into a single registry
    with one ``list_tools`` + ``call_tool`` handler.

    The impl receives an already-parsed input model instance and
    returns an output model instance — strongly typed in, strongly
    typed out. The server's call_tool wrapper does the dict-from-MCP
    → input model parsing and the output model → JSON serialization.
    """
    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    impl: Callable

    model_config = {"arbitrary_types_allowed": True}
