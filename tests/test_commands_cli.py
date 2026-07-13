"""The subcommand surface, driven through `main(argv)` in-process.

These assert exit codes and the shape of stdout/stderr. The persistence-across-processes
claims live in their own file; here the point is the command dispatch and its contracts.
"""

import json

import pytest

from gaveta.cli import main


def _capture(raw: str) -> int:
    return main([raw])


# --- ls ----------------------------------------------------------------------


def test_ls_shows_captures_newest_first(capsys: pytest.CaptureFixture[str]) -> None:
    _capture("oldest")
    _capture("newest")
    capsys.readouterr()

    assert main(["ls"]) == 0
    out = capsys.readouterr().out
    assert out.index("newest") < out.index("oldest")


def test_ls_on_an_empty_drawer_prints_nothing_and_exits_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["ls"]) == 0
    assert capsys.readouterr().out == ""


def test_ls_filters_by_type(capsys: pytest.CaptureFixture[str]) -> None:
    _capture("a note")
    capsys.readouterr()

    # No captures are `command` yet (classification is Stage 4), so the filter is empty.
    assert main(["ls", "command"]) == 0
    assert capsys.readouterr().out == ""


def test_ls_of_an_unknown_type_exits_two_with_the_valid_list(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["ls", "bogus"]) == 2

    err = capsys.readouterr().err
    assert "unknown type" in err
    assert "credential_ref" in err  # the valid list is shown


def test_ls_json_is_a_parseable_array(capsys: pytest.CaptureFixture[str]) -> None:
    _capture("x")
    capsys.readouterr()

    assert main(["ls", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["raw"] == "x"


# --- show --------------------------------------------------------------------


def test_show_prints_the_full_detail(capsys: pytest.CaptureFixture[str]) -> None:
    _capture("ssh -L 5432")
    capsys.readouterr()

    assert main(["show", "1"]) == 0
    out = capsys.readouterr().out
    assert "ssh -L 5432" in out
    assert "id" in out


def test_show_of_a_missing_id_exits_one_on_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["show", "999"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no item with id 999" in captured.err


def test_show_json_validates_against_the_item_view(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from gaveta.models import ItemView

    _capture("x")
    capsys.readouterr()

    main(["show", "1", "--json"])
    ItemView.model_validate_json(capsys.readouterr().out)


# --- rm ----------------------------------------------------------------------


def test_rm_removes_and_confirms(capsys: pytest.CaptureFixture[str]) -> None:
    _capture("goodbye")
    capsys.readouterr()

    assert main(["rm", "1"]) == 0
    assert "✓ removed · id 1" in capsys.readouterr().out


def test_rm_is_idempotent_with_a_differing_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Both calls exit 0; the second says `already absent` and the first does not.

    `gaveta rm 1 && gaveta rm 1` must not fail on the re-run.
    """
    _capture("goodbye")
    capsys.readouterr()

    assert main(["rm", "1"]) == 0
    first = capsys.readouterr().out
    assert main(["rm", "1"]) == 0
    second = capsys.readouterr().out

    assert "already absent" not in first
    assert "already absent" in second


def test_rm_of_a_never_existing_id_exits_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["rm", "999"]) == 0
    assert "already absent" in capsys.readouterr().out


# --- retag -------------------------------------------------------------------


def test_retag_reclassifies_and_prints_the_retagged_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A lone URL captured as a link retags to the same; the line says `retagged`."""
    _capture("https://sqlite.org/withoutrowid.html")
    capsys.readouterr()

    assert main(["retag", "1"]) == 0
    out = capsys.readouterr().out
    assert "✓ retagged · id 1 · link" in out
    assert "saved" not in out


def test_retag_is_idempotent_on_the_heuristic_path(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No Ollama in tests, so retag re-runs the deterministic heuristic: same fields."""
    _capture("just a plain note")
    capsys.readouterr()

    main(["show", "1", "--json"])
    before = json.loads(capsys.readouterr().out)
    assert main(["retag", "1"]) == 0
    capsys.readouterr()
    main(["show", "1", "--json"])
    after = json.loads(capsys.readouterr().out)

    assert after["type"] == before["type"] == "note"
    assert after["title"] == before["title"]
    assert after["content"] == before["content"]


def test_retag_touches_updated_at_but_not_created_at(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A reclassification is an update: updated_at moves, created_at holds."""
    _capture("una nota")
    capsys.readouterr()
    main(["show", "1", "--json"])
    before = json.loads(capsys.readouterr().out)

    assert main(["retag", "1"]) == 0
    capsys.readouterr()
    main(["show", "1", "--json"])
    after = json.loads(capsys.readouterr().out)

    assert after["created_at"] == before["created_at"]
    assert after["updated_at"] >= before["updated_at"]


def test_retag_of_a_missing_id_exits_one(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["retag", "999"]) == 1
    assert "no item with id 999" in capsys.readouterr().err


# --- export ------------------------------------------------------------------


def test_export_emits_a_valid_json_array(capsys: pytest.CaptureFixture[str]) -> None:
    _capture("one")
    _capture("two")
    capsys.readouterr()

    assert main(["export"]) == 0
    parsed = json.loads(capsys.readouterr().out)
    assert [item["raw"] for item in parsed] == ["one", "two"]


def test_export_of_an_empty_drawer_is_an_empty_array(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["export"]) == 0
    assert json.loads(capsys.readouterr().out) == []


# --- f (search) --------------------------------------------------------------


def test_f_finds_a_capture_by_keyword_and_exits_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The acceptance path: capture, then `f` returns the item (FTS5, no Ollama)."""
    _capture("para el tunel al rds de qa: ssh -L 5432:rds-qa:5432 jump")
    capsys.readouterr()

    assert main(["f", "tunel"]) == 0
    out = capsys.readouterr().out
    assert "tunel" in out or "rds" in out.lower()


def test_f_json_emits_an_array_of_hits(capsys: pytest.CaptureFixture[str]) -> None:
    _capture("ssh tunnel to the qa rds database")
    capsys.readouterr()

    assert main(["f", "tunnel", "--json"]) == 0
    out, err = capsys.readouterr()
    hits = json.loads(out)  # stdout is clean JSON even though a notice went to stderr
    assert hits and hits[0]["matched_on"] in ("keyword", "semantic", "both")


def test_f_no_match_exits_zero_with_a_stderr_notice(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Found nothing is not an error: exit 0, empty stdout, notice on stderr."""
    _capture("a note about coffee")
    capsys.readouterr()

    assert main(["f", "zzz-no-match"]) == 0
    out, err = capsys.readouterr()
    assert out == ""
    assert "no matches" in err


def test_f_signals_keyword_only_mode_on_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """This machine cannot load sqlite-vec, so `f` always warns it is keyword-only."""
    _capture("something findable")
    capsys.readouterr()

    main(["f", "findable"])
    assert "vector index unavailable" in capsys.readouterr().err


# --- reindex -----------------------------------------------------------------


def test_reindex_reports_a_count_and_exits_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """With no Ollama, nothing embeds, but reindex still succeeds and reports it."""
    _capture("one")
    _capture("two")
    capsys.readouterr()

    assert main(["reindex"]) == 0
    assert "reindexed" in capsys.readouterr().out


def test_reindex_is_idempotent_across_runs(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _capture("only item")
    capsys.readouterr()

    assert main(["reindex"]) == 0
    capsys.readouterr()
    assert main(["reindex"]) == 0  # a second run does not fail
