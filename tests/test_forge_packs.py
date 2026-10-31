"""Invented pack fixtures only: no bank CSVs or generated content reads."""
import copy
import json
import random

import pytest

from forge.families import FamilyForge, load_families
from test_forge_families import FakeModels, FakeSandbox, source, write_rows


@pytest.mark.parametrize("count", [20, 50, 75, 100])
def test_family_sizes_come_from_the_source(tmp_path, count):
    path, _ = source(tmp_path, count=count)
    families = load_families(path)
    assert len(families[0].variants) == count
    models = FakeModels(tmp_path / "private")
    forge = FamilyForge(models, output=tmp_path / "public", funnel=tmp_path / "funnel.json",
                        sandbox=FakeSandbox())
    report = forge.run(families)
    artifact = json.loads((tmp_path / "public" / "family_1.json").read_text())
    assert report["source_variants"] == count and report["solvers_verified"] == 1
    assert artifact["verification"]["solver"]["variants_checked"] == count
    assert len(artifact["instances"]) == count and artifact["pack"] == "quant"


@pytest.mark.parametrize("pack,prefix", [("quant", "family"), ("ib", "ib"), ("consulting", "co"), ("software", "sw")])
def test_pack_namespaces_do_not_collide(tmp_path, pack, prefix):
    path, _ = source(tmp_path, count=50)
    models = FakeModels(tmp_path / pack)
    forge = FamilyForge(models, output=tmp_path / "public", funnel=tmp_path / f"{pack}.json",
                        sandbox=FakeSandbox(), pack=pack)
    report = forge.run(load_families(path))
    artifact = json.loads((tmp_path / "public" / ("family_1.json" if pack == "quant" else f"{prefix}_F001.json")).read_text())
    assert artifact["pack"] == report["pack"] == pack
    assert artifact["template_id"] == ("family_1" if pack == "quant" else f"{prefix}_F001")
    assert len(artifact["instances"]) == 50


def test_fewer_than_twenty_and_duplicate_variant_ids_still_fail(tmp_path):
    path, rows = source(tmp_path, count=19)
    with pytest.raises(ValueError):
        load_families(path)
    path, rows = source(tmp_path, count=50)
    rows[-1]["variant"] = rows[0]["variant"]
    write_rows(path, rows)
    with pytest.raises(ValueError):
        load_families(path)


def test_old_quant_checkpoint_and_finished_items_resume_without_spend(tmp_path):
    path, _ = source(tmp_path)
    families = load_families(path)
    models = FakeModels(tmp_path / "private")
    forge = FamilyForge(models, output=tmp_path / "public", funnel=tmp_path / "funnel.json", sandbox=FakeSandbox())
    forge.run(families)
    models.state.data["family_forge_settings"] = {"version": 1, "variants_per_family": 75,
        "exact_source_tolerance": 0, "repairs_per_family": 1, "typed_parameters": True}
    models.state.save()
    models.call = lambda *a, **k: pytest.fail("Finished quant family spent again")
    resumed = FamilyForge(models, output=tmp_path / "public", funnel=tmp_path / "funnel.json", sandbox=FakeSandbox())
    assert resumed.run(families)["misconceptions_verified"] == 1


def test_work_directory_cannot_be_reused_for_a_different_pack(tmp_path):
    models = FakeModels(tmp_path / "private")
    FamilyForge(models, output=tmp_path / "public", funnel=tmp_path / "funnel.json", pack="ib")
    with pytest.raises(ValueError):
        FamilyForge(models, output=tmp_path / "public", funnel=tmp_path / "funnel.json", pack="software")


def test_legacy_templates_default_to_quant_without_rewriting_files(tmp_path):
    from forge.bank import TemplateBank
    legacy = {"template_id": "legacy", "instances": [{"params": {"n": 1}, "answer": "1/2"}]}
    other = {"template_id": "sw_F001", "pack": "software", "instances": [{"params": {"n": 1}, "answer": "2"}]}
    (tmp_path / "legacy.json").write_text(json.dumps(legacy))
    (tmp_path / "software.json").write_text(json.dumps(other))
    before = (tmp_path / "legacy.json").read_bytes()
    quant = TemplateBank.load(tmp_path, pack="quant")
    assert quant.templates["legacy"]["pack"] == "quant" and "sw_F001" not in quant.templates
    assert (tmp_path / "legacy.json").read_bytes() == before


def test_software_twins_never_repeat_an_equal_answer_even_with_many_variants():
    from forge.bank import TemplateBank
    variants = [{"variant": str(i), "params": {"n": i}, "answer": str(i % 10)} for i in range(50)]
    template = {"template_id": "sw_F001", "pack": "software", "instances": variants}
    bank = TemplateBank([template], pack="software")
    for asked in variants:
        for seed in range(10):
            twin = bank.choose_twin("sw_F001", asked, random.Random(seed))
            assert twin["answer"] != asked["answer"] and twin["params"] != asked["params"]


def test_twin_equality_is_exact_and_no_different_answer_fails_closed():
    from forge.bank import TemplateBank, NoTwinAvailable
    variants = [{"params": {"n": 1}, "answer": "1/2"}, {"params": {"n": 2}, "answer": "0.5"},
                {"params": {"n": 3}, "answer": "2/4"}]
    bank = TemplateBank([{"template_id": "sw_F001", "pack": "software", "instances": variants}], pack="software")
    with pytest.raises(NoTwinAvailable):
        bank.choose_twin("sw_F001", variants[0], random.Random(1))


@pytest.mark.parametrize("span", ["26 percent", "twenty-six percent", "26%", "13/50", "0.26"])
def test_exact_consulting_percentage_matches_fraction_storage(span):
    from forge.bank import answer_matches
    assert answer_matches({"answer": "13/50", "tolerance": "0"}, span)


@pytest.mark.parametrize("span", ["25 percent", "27 percent", "26", "0.27"])
def test_exact_percentage_near_misses_are_not_accepted(span):
    from forge.bank import answer_matches
    assert not answer_matches({"answer": "13/50", "tolerance": "0"}, span)


def test_only_source_numerical_tolerance_is_applied():
    from forge.bank import answer_matches
    assert answer_matches({"answer": "13/50", "tolerance": "1/1000"}, "26.05 percent")
    assert not answer_matches({"answer": "13/50", "tolerance": "1/1000"}, "26.2 percent")


@pytest.mark.parametrize("pack,prefix", [("ib","ib"),("consulting","co"),("software","sw")])
def test_cli_exports_fifty_variant_sector_pack_with_fake_models(tmp_path, monkeypatch, capsys, pack, prefix):
    from forge import family_run
    from forge import models as model_module
    from test_forge_families import draft
    from types import SimpleNamespace
    path, _ = source(tmp_path, count=50)
    monkeypatch.setattr(family_run, "ROOT", tmp_path)
    class Backend:
        name, model, enforces_schema = "open_weights", "fake-author", False
        def complete(self, request):
            assert json.loads(request["messages"][-1]["content"])["pack"] == pack
            return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(draft())}}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 200}}
    monkeypatch.setattr(family_run, "get_backend", lambda name: Backend())
    monkeypatch.setattr(model_module, "get_backend", lambda name: SimpleNamespace(name="meta_api", model="fake-checker"))
    monkeypatch.setattr(family_run, "Sandbox", lambda *a, **k: FakeSandbox())
    monkeypatch.setenv("LLM_BACKEND", "open_weights")
    monkeypatch.setenv("BASETEN_API_KEY", "fake-test-key")
    work = tmp_path / "data" / "forge" / (prefix+"1")
    args = ["--csv", str(path), "--pack", pack, "--work-dir", str(work), "--mode", "live", "--budget-usd", "5"]
    assert family_run.main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["pack"] == pack and report["families_exported"] == report["solvers_verified"] == 1
    assert report["misconceptions_verified"] == 1
    assert not (tmp_path / "forge" / "funnel.json").exists()
    assert len(json.loads((tmp_path / "content" / "forge" / ("family_1.json" if pack == "quant" else f"{prefix}_F001.json")).read_text())["instances"]) == 50
    cost = report["cost_usd"]
    assert family_run.main([*args, "--mode", "replay"]) == 0
    assert json.loads(capsys.readouterr().out)["cost_usd"] == cost


@pytest.mark.parametrize("span,expected", [("100/3 percent","1/3"), ("one third percent","1/300"),
                                         ("minus twenty six percent","-13/50"), ("-26%","-13/50")])
def test_fractional_and_negative_percentage_spans_are_scaled_exactly(span, expected):
    from forge.bank import answer_matches
    assert answer_matches({"answer":expected,"tolerance":"0"},span)
    if expected.startswith("-"):
        assert not answer_matches({"answer":expected[1:],"tolerance":"0"},span)


@pytest.mark.parametrize("pack,prefix", [("ib","ib"),("consulting","co"),("software","sw")])
def test_targeted_recheck_uses_the_pack_namespace(tmp_path, pack, prefix):
    path, _ = source(tmp_path, count=50)
    models, sandbox = FakeModels(tmp_path / "private"), FakeSandbox()
    sandbox.offset = 1
    forge = FamilyForge(models, output=tmp_path / "public", funnel=tmp_path / "report.json", sandbox=sandbox, pack=pack)
    families = load_families(path)
    assert forge.run(families)["fallback_families"] == 1
    sandbox.offset = 0
    models.call = lambda *a, **k: pytest.fail("Cached pack recheck spent on a model")
    report = forge.run(families, recheck_families=["1"])
    assert report["recheck"]["verified"] == 1 and report["solvers_verified"] == 1
    assert json.loads((tmp_path / "public" / ("family_1.json" if pack == "quant" else f"{prefix}_F001.json")).read_text())["pack"] == pack
    assert not (tmp_path / "public" / "family_1.json").exists()


@pytest.mark.parametrize("pack,source_id,expected", [
    ("ib","IB01","ib_F001"), ("consulting","CO30","co_F030"), ("software","SW09","sw_F009")])
def test_sector_source_ids_export_as_f_numbers(tmp_path, pack, source_id, expected):
    path, rows = source(tmp_path, count=50)
    for row in rows:
        row["family_id"] = source_id
    write_rows(path, rows)
    models = FakeModels(tmp_path / "private")
    forge = FamilyForge(models, output=tmp_path / "public", funnel=tmp_path / "funnel.json",
                        sandbox=FakeSandbox(), pack=pack)
    assert forge.run(load_families(path))["families_exported"] == 1
    artifact = json.loads((tmp_path / "public" / (expected + ".json")).read_text())
    assert artifact["template_id"] == expected
    assert models.state.data["mapping"][expected]["family_id"] == source_id


def test_colliding_public_sector_ids_are_rejected_before_model_calls(tmp_path):
    from dataclasses import replace
    path, _ = source(tmp_path, count=50)
    families = load_families(path)
    aliases = [replace(families[0],family_id="IB01"),replace(families[0],family_id="F001")]
    models = FakeModels(tmp_path / "private")
    forge = FamilyForge(models, output=tmp_path / "public", funnel=tmp_path / "funnel.json",
                        sandbox=FakeSandbox(),pack="ib")
    with pytest.raises(ValueError):
        forge.run(aliases)
    assert not models.calls


@pytest.mark.parametrize("pack,prefix", [("software", "swf"), ("quant", "qx"), ("ib", "ibx"), ("quant_dev", "qd"), ("software", "swc")])
def test_a_new_batch_writes_its_own_prefix(tmp_path, pack, prefix):
    path, _ = source(tmp_path, count=50)
    forge = FamilyForge(FakeModels(tmp_path / "private"), output=tmp_path / "public", funnel=tmp_path / "funnel.json",
                        sandbox=FakeSandbox(), pack=pack, prefix=prefix)
    assert forge.run(load_families(path))["families_exported"] == 1
    artifact = json.loads((tmp_path / "public" / f"{prefix}_F001.json").read_text())
    assert artifact["template_id"] == f"{prefix}_F001" and artifact["pack"] == pack


@pytest.mark.parametrize("pack,prefix", [("ib", "sw"), ("software", "family"), ("quant", "Q"), ("software", "a" * 9)])
def test_a_prefix_can_never_be_another_packs(pack, prefix):
    from forge.packs import output_prefix
    with pytest.raises(ValueError):
        output_prefix(pack, prefix)


def test_family_run_refuses_to_overwrite_files_it_did_not_make(tmp_path, monkeypatch, capsys):
    from forge import family_run
    path, _ = source(tmp_path, count=50)
    monkeypatch.setattr(family_run, "ROOT", tmp_path)
    monkeypatch.setattr(family_run, "get_backend", lambda name: pytest.fail("no model before the overwrite check"))
    monkeypatch.setattr(family_run, "Models", lambda *a, **k: pytest.fail("no model before the overwrite check"))
    (tmp_path / "content" / "forge").mkdir(parents=True)
    (tmp_path / "content" / "forge" / "sw_F001.json").write_text("{}", encoding="utf-8")  # an earlier batch's family
    monkeypatch.setattr(family_run, "get_backend", lambda name: type("B", (), {"name": "open_weights"})())
    args = ["--csv", str(path), "--pack", "software", "--work-dir", str(tmp_path / "data" / "forge" / "sw9"), "--mode", "replay"]
    assert family_run.main(args) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "would_overwrite" and out["files"] == ["sw_F001"]
    assert (tmp_path / "content" / "forge" / "sw_F001.json").read_text(encoding="utf-8") == "{}"
    # The same batch under its own prefix goes ahead (here it stops later only for want of a model).
    monkeypatch.setattr(family_run, "Models", lambda *a, **k: (_ for _ in ()).throw(ValueError("stop here")))
    assert family_run.main([*args[:-2], "--prefix", "swf", "--mode", "replay", "--work-dir", str(tmp_path / "data" / "forge" / "swf1")]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "configuration_error"
