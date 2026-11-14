"""Deterministic operations on complete scoped CSV/TSV artifacts; no eval/codegen."""

import csv
import hashlib
import io
import json
import math
from collections import Counter

from annotation import AccessDenied, Evidence, ToolError
from cache import ExactCache


class TableProcessor:
    def __init__(self, store, cache: ExactCache | None = None, max_rows: int = 100000):
        self.store, self.cache, self.max_rows = store, cache, max_rows

    def _rows(self, identifier, case_id):
        self.store._scope(case_id)
        if identifier not in self.store.documents:
            raise AccessDenied()
        artifact = self.store.documents[identifier]
        delimiter = "\t" if artifact.media_type == "text/tab-separated-values" else ","
        reader = csv.DictReader(
            io.StringIO(artifact.text.removeprefix("\ufeff")), delimiter=delimiter
        )
        if not reader.fieldnames or len(reader.fieldnames) != len(
            set(reader.fieldnames)
        ):
            raise ToolError("Missing/duplicate table columns")
        rows = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ToolError("Malformed table row")
            rows.append(row)
            if len(rows) > self.max_rows:
                raise ToolError("Table row limit exceeded")
        return rows, reader.fieldnames

    def calculate(self, query, ids, *, case_id, timeout, specification=None):
        if not specification or not isinstance(specification, dict):
            raise ToolError("Provide a structured calculation specification")
        self.store._scope(case_id)
        if not ids or not all(i in self.store.documents for i in ids):
            raise AccessDenied()
        operation = specification.get("operation")
        arity = {
            "count_distinct": 1,
            "unmatched": 2,
            "baseline": 1,
            "join": 2,
            "cross_tab": 1,
        }
        if (
            not isinstance(operation, str)
            or operation not in arity
            or len(ids) != arity[operation]
        ):
            raise ToolError("Unsupported operation or incorrect table count")
        column_fields = {
            "count_distinct": ("column",),
            "unmatched": ("column",),
            "baseline": ("column",),
            "join": ("key",),
            "cross_tab": ("group", "label"),
        }
        if any(
            not isinstance(specification.get(name), str) or not specification[name]
            for name in column_fields[operation]
        ):
            raise ToolError("Calculation requires named columns")
        try:
            serialized = json.dumps(specification, sort_keys=True, allow_nan=False)
        except (ValueError, TypeError):
            raise ToolError("Invalid calculation parameters") from None
        hashes = tuple(
            hashlib.sha256(self.store.documents[i].text.encode()).hexdigest()
            for i in ids
        )
        key = ("table-v1", case_id, tuple(ids), hashes, serialized)
        cached = self.cache.get(key) if self.cache else None
        if cached is not None:
            return cached
        data = [self._rows(i, case_id) for i in ids]
        rows, columns = data[0]
        operation = specification.get("operation")
        required = {specification[name] for name in column_fields[operation]}
        if not required <= set(columns):
            raise ToolError("Unknown calculation columns")
        if operation == "count_distinct":
            column = specification["column"]
            result = {
                "distinct": len({r[column] for r in rows if r[column] != ""}),
                "rows": len(rows),
                "missing": sum(r[column] == "" for r in rows),
            }
        elif operation == "unmatched":
            if len(data) != 2 or specification["column"] not in data[1][1]:
                raise ToolError("Two tables with the declared column are required")
            column = specification["column"]
            known = {r[column] for r in data[1][0]}
            result = {
                "unmatched": sum(r[column] not in known for r in rows),
                "rows": len(rows),
            }
        elif operation == "baseline":
            column = specification["column"]
            lower, upper = specification.get("lower", -7), specification.get("upper", 0)
            if (
                not isinstance(lower, (int, float))
                or not isinstance(upper, (int, float))
                or not math.isfinite(lower)
                or not math.isfinite(upper)
                or lower > upper
            ):
                raise ToolError("Invalid numeric baseline window")
            counts = Counter(eligible=0, post_treatment=0, outside_window=0, unknown=0)
            for row in rows:
                try:
                    day = float(row[column])
                    if not float("-inf") < day < float("inf"):
                        raise ValueError()
                    label = (
                        "eligible"
                        if lower <= day <= upper
                        else "post_treatment" if day > 0 else "outside_window"
                    )
                except ValueError:
                    label = "unknown"
                counts[label] += 1
            result = dict(counts)
        elif operation == "join":
            if len(data) != 2 or specification["key"] not in data[1][1]:
                raise ToolError("Two tables with the exact declared key are required")
            key_column = specification["key"]
            filters = specification.get("filters", {})
            if (
                not isinstance(filters, dict)
                or any(not set(filters) <= set(cols) for _, cols in data)
                or not all(isinstance(value, str) for value in filters.values())
            ):
                raise ToolError("Unknown filter columns")
            filtered = [
                [r for r in records if all(r[k] == v for k, v in filters.items())]
                for records, _ in data
            ]
            left, right = [
                Counter(r[key_column] for r in records if r[key_column])
                for records in filtered
            ]
            shared = set(left) & set(right)
            result = {
                "verified_one_to_one": sum(left[k] == right[k] == 1 for k in shared),
                "ambiguous_keys": sorted(
                    k for k in shared if left[k] != 1 or right[k] != 1
                ),
                "left_only": len(set(left) - set(right)),
                "right_only": len(set(right) - set(left)),
            }
        elif operation == "cross_tab":
            group, label = specification["group"], specification["label"]
            counts = Counter(
                (r[group], r[label]) for r in rows if r[group] and r[label]
            )
            classes = {label for _, label in counts}
            groups = {g for g, _ in counts}
            result = {
                "cells": [
                    {"group": g, "label": v, "count": n}
                    for (g, v), n in sorted(counts.items())
                ],
                "perfect_confounding": len(classes) > 1
                and len(groups) > 1
                and all(len({v for g2, v in counts if g2 == g}) == 1 for g in groups),
                "missing": sum(not r[group] or not r[label] for r in rows),
            }
        else:
            raise ToolError("Unsupported deterministic operation")
        payload = {
            "operation": operation,
            "result": result,
            "input_ids": list(ids),
            "input_hashes": list(hashes),
            "parameters": specification,
        }
        evidence = (
            Evidence(
                "calculation:" + hashlib.sha256(repr(key).encode()).hexdigest()[:16],
                "complete-table calculation",
                json.dumps(payload, sort_keys=True),
                "table-v1",
            ),
        )
        if self.cache:
            self.cache.put(key, evidence, 900)
        return evidence
