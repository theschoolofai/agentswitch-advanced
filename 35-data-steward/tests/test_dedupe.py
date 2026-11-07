import pytest

from data_steward import dedupe

TAGS = ("qa-run",)  # invented: the live tag list stays in local/


def party(pid, name, **fields):
    return {"id": pid, "name": name, "privacy_state": "normal", "company_id": "c1", "roles": [], **fields}


def item(iid, name, code, **fields):
    return {"id": iid, "name": name, "code": code, "company_id": "c1", "uom": "ea", "type": "product",
            "product_type": "goods", "variants": [], **fields}


def pairs(entity, rows, **kwargs):
    return {tuple(p["ids"]): p for p in dedupe.find_duplicates(entity, rows, test_tags=TAGS, **kwargs)["pairs"]}


def test_names_ignore_case_spacing_punctuation_order_and_legal_endings():
    assert dedupe.norm_name("Bluepine  Logistics Pvt. Ltd.") == dedupe.norm_name("bluepine logistics private limited")
    assert dedupe.norm_name("Chen, Wei") == dedupe.norm_name("Wei Chen")
    assert dedupe.norm_name("Halden & Roe") == dedupe.norm_name("Halden and Roe")
    assert dedupe.norm_name("Ltd") == "ltd"  # a name that is only a legal ending keeps it


def test_only_confirmed_test_tags_are_stripped():
    assert dedupe.strip_tag("[qa-run 7] Gristmill Foods", TAGS) == ("Gristmill Foods", True)
    assert dedupe.strip_tag("[North] Kestrel Outfitters", TAGS) == ("[North] Kestrel Outfitters", False)
    assert dedupe.norm_name("[North] Kestrel", TAGS) != dedupe.norm_name("[South] Kestrel", TAGS)


@pytest.mark.parametrize("raw, expected", [("+1 (555) 201-3344", "5552013344"), ("555.201.3344", "5552013344"),
                                           ("201-3344", ""), ("000-000-0000", ""), (None, "")])
def test_phone_normalization(raw, expected):
    assert dedupe.norm_phone(raw) == expected


def test_flag_reads_strings_and_ints():
    assert [dedupe.flag(v) for v in (True, 1, "true", "TRUE", False, 0, "false", None, "")] == [True] * 4 + [False] * 5


def test_same_email_and_name_is_proposed():
    rows = [party("p1", "Rivera Hardware", email="orders@rivera.example"),
            party("p2", "rivera  HARDWARE", email="Orders@Rivera.example")]
    p = pairs("party", rows)[("p1", "p2")]
    assert p["band"] == "propose" and set(p["signals"]) == {"email", "name"} and p["id"] == "party:p1:p2"


def test_empty_and_placeholder_values_never_match():
    rows = [party("p1", "Ivy Florist", email="N/A", phone="0000000000"),
            party("p2", "Copper Cafe", email="n/a", phone="000-000-0000"),
            party("p3", "Olsen Plumbing"), party("p4", "Marlow Electric")]
    assert pairs("party", rows) == {}


def test_a_value_shared_by_many_records_is_ignored():
    rows = [party(f"p{i}", f"Shop {chr(65 + i)}{chr(70 + i)}{chr(75 + i)}", phone="5550100100")
            for i in range(dedupe.SHARED_LIMIT + 1)]
    result = dedupe.find_duplicates("party", rows)
    assert result["pairs"] == [] and result["ignored_shared"] == {"phone": 1}


def test_strong_value_conflict_caps_at_review():
    rows = [party("p1", "Summit Dental", email="a@summit.example", phone="5552010001"),
            party("p2", "Summit Dental", email="b@summit.example", phone="5552010001")]
    p = pairs("party", rows)[("p1", "p2")]
    assert p["score"] == 1.0 and p["band"] == "review" and "email differs" in p["caps"]


def test_role_difference_caps_at_review_but_no_role_is_no_evidence():
    supplier = [{"role": "supplier", "active": True}]
    customer = [{"role": "customer", "active": True}]
    rows = [party("p1", "Tidewater Marine", email="s@tide.example", roles=customer),
            party("p2", "Tidewater Marine", email="s@tide.example", roles=supplier),
            party("p3", "Fernhill Nursery", email="f@fern.example", roles=[]),
            party("p4", "Fernhill Nursery", email="f@fern.example", roles=customer)]
    found = pairs("party", rows)
    assert found[("p1", "p2")]["band"] == "review" and found[("p1", "p2")]["caps"] == ["roles differ"]
    assert found[("p3", "p4")]["band"] == "propose"


def test_inactive_role_does_not_count():
    rows = [party("p1", "Acme", email="a@acme.example", roles=[{"role": "customer", "active": True}]),
            party("p2", "Acme", email="a@acme.example",
                  roles=[{"role": "customer", "active": True}, {"role": "supplier", "active": False}])]
    assert pairs("party", rows)[("p1", "p2")]["band"] == "propose"


def test_score_below_review_is_dropped_and_counted():
    rows = [party("p1", "Olsen Plumbing", phone="5552013344"), party("p2", "Marlow Electric", phone="5552013344")]
    result = dedupe.find_duplicates("party", rows)
    assert result["pairs"] == [] and result["dropped"] == 1  # a phone alone is below review


def test_a_one_letter_typo_counts_as_the_name():
    rows = [party("p1", "Brightwater Optics"), party("p2", "Brightwatr Optics")]
    assert pairs("party", rows)[("p1", "p2")]["band"] == "review"
    items = [item("i1", "Shrink Wrap Roll 500", "SW-500", category_id="pack"),
             item("i2", "Shrink Wrap Rol 500", "SWR-500", category_id="pack")]
    shrink = pairs("item", items)[("i1", "i2")]
    assert (shrink["score"], shrink["band"], shrink["caps"]) == (0.7, "review", ["code differs"])


@pytest.mark.parametrize("shared", [{"email": "family@whitcombe.example"}, {"phone": "5552013344"}])
def test_near_names_with_a_shared_contact_are_held_at_review(shared):
    # Two people a letter apart can share a household email or phone: a near name never proposes.
    rows = [party("p1", "Dana Whitcombe", **shared), party("p2", "Dane Whitcombe", **shared)]
    p = pairs("party", rows)[("p1", "p2")]
    assert p["score"] >= 0.9 and p["band"] == "review" and p["caps"] == ["names differ slightly"]
    exact = pairs("party", [party("p1", "Dana Whitcombe", **shared), party("p2", "Dana Whitcombe", **shared)])
    assert exact[("p1", "p2")]["band"] == "propose"  # an exact name with the same contact still proposes


def test_near_names_with_the_same_customer_code_still_propose():
    rows = [party("p1", "Dana Whitcombe", customer_code="C-1001"), party("p2", "Dane Whitcombe", customer_code="C-1001")]
    p = pairs("party", rows)[("p1", "p2")]
    assert (p["band"], p["caps"]) == ("propose", [])


@pytest.mark.parametrize("a, b, reason", [
    ({"allow_duplicate": "true"}, {}, "flagged as an allowed duplicate"),
    ({"company_id": "c1"}, {"company_id": "c2"}, "different companies"),
    ({"type": "individual"}, {"type": "organization"}, "individual and organisation"),
])
def test_party_exclusions_are_listed_with_a_reason(a, b, reason):
    rows = [party("p1", "Jordan Pike", email="j@pike.example", **a), party("p2", "Jordan Pike", email="j@pike.example", **b)]
    result = dedupe.find_duplicates("party", rows)
    assert result["pairs"] == [] and [e["reason"] for e in result["excluded"]] == [reason]


def test_a_missing_company_proves_nothing():
    rows = [party("p1", "Acme", email="a@acme.example", company_id=None), party("p2", "Acme", email="a@acme.example")]
    assert pairs("party", rows)[("p1", "p2")]["band"] == "propose"


def test_private_parties_are_withheld_before_grouping():
    rows = [party("p1", "Lena Ortiz", email="l@ortiz.example", privacy_state="restricted"),
            party("p2", "Lena Ortiz", email="l@ortiz.example"), party("p3", "No State", privacy_state=None)]
    result = dedupe.find_duplicates("party", rows)
    assert result["withheld_private"] == 2 and result["pairs"] == [] and result["excluded"] == []
    assert "p1" not in repr(result)


def test_tagged_pair_keeps_its_band_and_is_marked():
    rows = [party("p1", "[qa-run 1] Gristmill Foods"), party("p2", "[qa-run 2] Gristmill Foods"),
            party("p3", "Gristmill Foods")]
    found = pairs("party", rows)
    assert found[("p1", "p2")]["tagged"] and found[("p1", "p3")]["tagged"]
    assert found[("p1", "p2")]["band"] == "review"


def test_shared_tag_alone_adds_nothing():
    rows = [party("p1", "[qa-run 3] Northgate Tooling Inc"), party("p2", "[qa-run 3] Northgate Textiles LLC")]
    assert pairs("party", rows) == {}


def test_record_in_two_pairs_is_flagged_and_order_is_stable():
    rows = [party("p3", "Kite Co", email="k@kite.example"), party("p1", "Kite", email="k@kite.example"),
            party("p2", "Kite Company", email="k@kite.example"), party("p9", "Other", email="o@other.example")]
    first = dedupe.find_duplicates("party", rows)
    again = dedupe.find_duplicates("party", list(reversed(rows)))
    assert first["pairs"] == again["pairs"] and [p["id"] for p in first["pairs"]] == [
        "party:p1:p2", "party:p1:p3", "party:p2:p3"]
    assert all(p["shared_record"] for p in first["pairs"])


def test_items_same_code_are_proposed_and_code_sku_alias_counts_once():
    rows = [item("i1", "Hex Bolt M8 x 40", "HB-M8-40"), item("i2", "hex bolt m8 x 40", "hb-m8-40"),
            item("i3", "Wood Pallet", "PL-220", sku="PAL-220"), item("i4", "Wood Pallet", "PAL-220")]
    found = pairs("item", rows)
    assert found[("i1", "i2")]["band"] == "propose"
    assert found[("i3", "i4")]["signals"].count("code") == 1 and found[("i3", "i4")]["caps"] == []


def test_item_code_conflict_caps_at_review():
    rows = [item("i1", "Nitrile Gloves Large", "GL-1", category_id="k1"),
            item("i2", "Nitrile Gloves - Large", "GL-2", category_id="k1")]
    p = pairs("item", rows)[("i1", "i2")]
    assert p["band"] == "review" and p["caps"] == ["code differs"]


@pytest.mark.parametrize("a, b, reason", [
    ({"uom": "m"}, {"uom": "kg"}, "different units"),
    ({"product_type": "services"}, {}, "different kinds"),
])
def test_item_exclusions(a, b, reason):
    rows = [item("i1", "Copper Wire", "CW-1", **a), item("i2", "Copper Wire", "CW-1", **b)]
    assert [e["reason"] for e in dedupe.find_duplicates("item", rows)["excluded"]] == [reason]


def test_variant_of_another_item_is_excluded():
    # Scores as a review pair (same name and category, codes differ); the variant rule then excludes it.
    rows = [item("i1", "Safety Vest", "SV-100", category_id="k1", variants=[{"sku": "SV-100-XL"}]),
            item("i2", "Safety Vest", "SV-100-XL", category_id="k1")]
    assert [e["reason"] for e in dedupe.find_duplicates("item", rows)["excluded"]] == ["variant of the other item"]


def test_evaluate_counts_misses_and_wrong_proposals():
    rows = [party("p1", "Acme", email="a@acme.example"), party("p2", "Acme", email="a@acme.example"),
            party("p3", "Olsen Plumbing", phone="5552013344"), party("p4", "Marlow Electric", phone="5552013344")]
    result = dedupe.find_duplicates("party", rows)
    report = dedupe.evaluate(result, duplicates=[["p3", "p4"]], distinct=[["p1", "p2"]])
    assert report["missed"] == [("p3", "p4")] and report["wrong"] == [("propose", ("p1", "p2"))]
    assert report["bands"]["propose"] == {"wrong": 1}


def tuning_set():
    import json
    from pathlib import Path
    return json.loads((Path(__file__).parent / "data" / "dedupe_tuning.json").read_text())


@pytest.mark.parametrize("entity", ["party", "item"])
def test_tuning_set_labels_name_real_records(entity):
    data = tuning_set()
    ids = {r["id"] for r in data[entity]}
    labelled = [pid for kind in ("duplicates", "distinct") for pair in data["labels"][entity][kind] for pid in pair]
    assert set(labelled) <= ids


@pytest.mark.parametrize("entity", ["party", "item"])
def test_tuning_set_never_proposes_a_known_non_duplicate(entity):
    # Accuracy is measured, not asserted (step 7); proposing a known non-duplicate is a safety failure at any weights.
    data = tuning_set()
    result = dedupe.find_duplicates(entity, data[entity], test_tags=data["test_tags"])
    report = dedupe.evaluate(result, data["labels"][entity]["duplicates"], data["labels"][entity]["distinct"])
    assert [w for w in report["wrong"] if w[0] == "propose"] == []


# Regressions from the step 4 code review.

def test_item_same_code_but_different_skus_is_capped():
    rows = [item("i1", "Safety Glove", "G-1", sku="G-RED"), item("i2", "Safety Glove", "G-1", sku="G-BLUE")]
    p = pairs("item", rows)[("i1", "i2")]
    assert p["band"] == "review" and p["caps"] == ["sku differs"]


def test_item_sku_meets_the_other_items_code_even_with_different_names():
    rows = [item("i1", "Wood Pallet", "PL-220", sku="PAL-220"), item("i2", "Shipping Platform", "PAL-220")]
    p = pairs("item", rows)[("i1", "i2")]
    assert "code" in p["signals"] and p["caps"] == []


def test_matching_unit_of_measure_adds_a_little():
    with_uom = pairs("item", [item("i1", "Copper Wire", "CW-1", category_id="k"),
                              item("i2", "Copper Wire", "CW-2", category_id="k")])[("i1", "i2")]
    assert "uom" in with_uom["signals"]


@pytest.mark.parametrize("placeholder", ["N/A", "Unknown", "  tbd ", "-"])
def test_placeholder_names_are_no_evidence(placeholder):
    rows = [party("p1", placeholder, email="x@shared.example"), party("p2", placeholder, email="x@shared.example"),
            party("p3", placeholder), party("p4", placeholder)]
    found = pairs("party", rows)
    assert ("p3", "p4") not in found and found[("p1", "p2")]["signals"] == ["email"]


def test_placeholder_city_is_no_address_evidence():
    addr = [{"city": "N/A", "postal": "00000-1"}]
    rows = [party("p1", "Olsen Plumbing", email="o@olsen.example", addresses=addr),
            party("p2", "Olsen Plumbing", email="o@olsen.example", addresses=addr)]
    assert "city_postal" not in pairs("party", rows)[("p1", "p2")]["signals"]


@pytest.mark.parametrize("inactive", ["false", 0, "0"])
def test_role_active_flag_is_read_like_other_booleans(inactive):
    rows = [party("p1", "Acme", email="a@acme.example", roles=[{"role": "customer", "active": True}]),
            party("p2", "Acme", email="a@acme.example",
                  roles=[{"role": "customer", "active": True}, {"role": "supplier", "active": inactive}])]
    assert pairs("party", rows)[("p1", "p2")]["band"] == "propose"


@pytest.mark.parametrize("roles", [[None, 7, {"active": True}], [{"role": ["customer"], "active": True}], 7, "customer"])
def test_malformed_roles_do_not_crash_a_scored_pair(roles):
    # The pair shares an email, so scoring (and role parsing) actually runs.
    rows = [party("p1", "Acme", email="a@acme.example", roles=roles), party("p2", "Acme", email="a@acme.example")]
    assert ("p1", "p2") in pairs("party", rows)


def test_names_that_are_not_strings_do_not_crash():
    rows = [party("p1", 12345, email="a@acme.example"), party("p2", None, email="a@acme.example")]
    assert ("p1", "p2") in pairs("party", rows)


def test_party_type_comparison_ignores_case():
    rows = [party("p1", "Jordan Pike", email="j@pike.example", type="Individual"),
            party("p2", "Jordan Pike", email="j@pike.example", type="individual")]
    assert pairs("party", rows)[("p1", "p2")]["band"] == "propose"


def test_an_empty_test_tag_strips_nothing():
    assert dedupe.strip_tag("[North] Acme", ("", "qa-run")) == ("[North] Acme", False)


def test_a_very_common_grouping_key_is_skipped_and_counted():
    rows = [party(f"p{i}", "Unique Name", website="staff.example") for i in range(dedupe.BLOCK_LIMIT + 1)]
    result = dedupe.find_duplicates("party", rows)
    assert result["pairs"] == [] and result["skipped_blocks"] >= 1


def test_a_repeated_id_is_counted_once():
    rows = [party("p1", "Acme", email="a@acme.example"), party("p1", "Acme", email="a@acme.example")]
    result = dedupe.find_duplicates("party", rows)
    assert result["pairs"] == [] and result["repeated_ids"] == 1


def test_variant_match_checks_the_other_items_sku_too():
    rows = [item("i1", "Safety Vest", "SV-100", category_id="k1", variants=[{"sku": "SV-100-XL"}]),
            item("i2", "Safety Vest", "VEST-XL", sku="SV-100-XL", category_id="k1")]
    assert [e["reason"] for e in dedupe.find_duplicates("item", rows)["excluded"]] == ["variant of the other item"]


def test_names_in_other_scripts_still_meet_and_keep_their_marks():
    assert dedupe.norm_name("राम शर्मा") == dedupe.norm_name("शर्मा राम")
    assert dedupe.norm_name("राम") != dedupe.norm_name("रोम")
    assert dedupe.tokens("शर्मा") == ["शर्मा"]  # one word, not letters split at the virama
    assert dedupe.norm_name("José Núñez") == dedupe.norm_name("jose nunez")


def test_evaluate_reports_an_excluded_known_duplicate_apart_from_misses():
    rows = [party("p1", "Jordan Pike", email="j@pike.example", type="individual"),
            party("p2", "Jordan Pike", email="j@pike.example", type="organization")]
    report = dedupe.evaluate(dedupe.find_duplicates("party", rows), duplicates=[["p1", "p2"]], distinct=[])
    assert report["excluded"] == [("p1", "p2")] and report["missed"] == []


@pytest.mark.parametrize("a, b, caps", [
    (dict(code="G-1", sku="G-1"), dict(code="G-1", sku="G-BLUE"), ["sku differs"]),  # SKU repeating its code
    (dict(code="AAA", sku="BBB"), dict(code="BBB", sku="CCC"), ["code differs", "sku differs"]),  # a chain, not an alias
    (dict(code="PL-1", sku="PAL-1"), dict(code="PAL-1", sku="PL-1"), []),  # swapped fields
    (dict(code="PL-1", sku="PAL-1"), dict(code="PAL-1"), []),  # one record stored the SKU as its code
])
def test_code_and_sku_alias_rule(a, b, caps):
    rows = [item("i1", "Widget", a.pop("code"), **a), item("i2", "Widget", b.pop("code"), **b)]
    p = pairs("item", rows)[("i1", "i2")]
    assert p["caps"] == caps and p["band"] == ("propose" if not caps else "review")


def test_padded_unit_is_the_same_unit():
    rows = [item("i1", "Wire", "W1", uom="ea "), item("i2", "Wire", "W1", uom="EA")]
    result = dedupe.find_duplicates("item", rows)
    assert result["excluded"] == [] and result["pairs"][0]["band"] == "propose"


def test_shared_limit_counts_code_and_sku_together():
    n = dedupe.SHARED_LIMIT // 2 + 1
    rows = ([item(f"c{i}", f"Thing {i}", "SAME-1") for i in range(n)]
            + [item(f"s{i}", f"Other {i}", f"OWN-{i}", sku="SAME-1") for i in range(n)])
    assert dedupe.find_duplicates("item", rows)["ignored_shared"] == {"code": 1}


def test_a_widely_shared_value_still_counts_as_a_conflict():
    # G-RED is on too many records to prove identity, but A and B still disagree on SKU.
    others = [item(f"o{i}", f"Other {i}", f"OTH-{i}", sku="G-RED") for i in range(dedupe.SHARED_LIMIT)]
    rows = [item("i1", "Widget", "G-1", sku="G-RED"), item("i2", "Widget", "G-1", sku="G-BLUE"), *others]
    p = pairs("item", rows)[("i1", "i2")]
    assert p["band"] == "review" and p["caps"] == ["sku differs"]


def test_a_shared_inbox_still_counts_as_an_email_conflict():
    inbox = [party(f"o{i}", f"Staff {i}", email="desk@shared.example") for i in range(dedupe.SHARED_LIMIT)]
    rows = [party("p1", "Acme", email="desk@shared.example", phone="5552010001"),
            party("p2", "Acme", email="owner@acme.example", phone="5552010001"), *inbox]
    p = pairs("party", rows)[("p1", "p2")]
    assert p["band"] == "review" and p["caps"] == ["email differs"]


# Rules version 3: item name gaps found by the first held-back run (6 Nov).

def test_item_names_ignore_spacing_between_a_number_and_its_unit():
    assert dedupe.norm_item_name("Brass Elbow 20mm") == dedupe.norm_item_name("brass elbow 20 mm")
    assert dedupe.norm_item_name("Brass Elbow 20mm") != dedupe.norm_item_name("Brass Elbow 25mm")
    assert dedupe.norm_name("Unit 4B Traders") == "4b traders unit"  # party names are unchanged


def test_same_item_name_reaches_review_even_with_different_codes_and_no_category():
    p = pairs("item", [item("i1", "Site Cleaning Visit", "SCV-1", uom=None),
                       item("i2", "Site Cleaning Visit", "CLN-9", uom=None)])[("i1", "i2")]
    assert (p["score"], p["band"], p["caps"]) == (0.6, "review", ["code differs"])


def test_repeated_test_run_items_reach_review_and_are_marked_tagged():
    rows = [item("i1", "[qa-run 3] Demo Bracket", "QA-3"), item("i2", "[qa-run 4] Demo Bracket", "QA-4")]
    p = pairs("item", rows)[("i1", "i2")]
    assert p["band"] == "review" and p["tagged"]


def test_item_name_with_a_brand_in_front_is_a_near_name():
    rows = [item("i1", "Marrow Hose Reel Wall", "MR-HRW", category_id="k"),
            item("i2", "Hose Reel Wall", "HRW-1", category_id="k")]
    p = pairs("item", rows)[("i1", "i2")]
    assert "near_name" in p["signals"] and p["band"] == "review"
    # Half the live items have no category: a near name and a shared unit are enough for review (0.55 + 0.05).
    no_category = pairs("item", [item("i1", "Marrow Hose Reel Wall", "MR-HRW"), item("i2", "Hose Reel Wall", "HRW-1")])
    assert no_category[("i1", "i2")]["score"] == 0.6 and no_category[("i1", "i2")]["band"] == "review"
    no_unit = [item("i1", "Marrow Hose Reel Wall", "MR-HRW", uom=None), item("i2", "Hose Reel Wall", "HRW-1", uom=None)]
    assert ("i1", "i2") not in pairs("item", no_unit)  # a near name alone is dropped


def test_size_variants_a_letter_apart_go_to_review_not_propose():
    # The accepted cost of the near-name weight: a person rejects these.
    p = pairs("item", [item("i1", "Hex Bolt M6", "HB-M6"), item("i2", "Hex Bolt M8", "HB-M8")])[("i1", "i2")]
    assert p["signals"] == ["near_name", "uom"] and p["band"] == "review"


def test_a_test_tag_with_a_digit_is_stripped_before_numbers_are_split():
    assert dedupe.norm_item_name("[qa3 run 1] Hose Reel Wall", ("qa3",)) == dedupe.norm_item_name("Hose Reel Wall")
    assert dedupe.norm_item_name("[North2] Hose Reel", ("qa3",)) != dedupe.norm_item_name("Hose Reel")


@pytest.mark.parametrize("short, long_", [("Hose Reel", "Marrow Hose Reel"),            # shorter has two words
                                          ("Hose Reel Wall", "Hose Reel Wall 300mm")])  # added words are a size
def test_item_name_containment_needs_three_words_and_no_added_number(short, long_):
    rows = [item("i1", short, "A-1", category_id="k"), item("i2", long_, "B-2", category_id="k")]
    assert ("i1", "i2") not in pairs("item", rows)
