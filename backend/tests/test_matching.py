"""The fingerprint rules, on their own. No database, no HTTP."""
from app.matching import canonical_url, fingerprint, normalize_text, posting_stem


def test_client_names_collapse_to_one_key():
    assert normalize_text("Acme Solutions Pvt Ltd") == normalize_text("ACME Solutions")


def test_tracking_parameters_are_dropped_but_job_ids_are_kept():
    assert canonical_url("https://www.acme.com/careers/eng?utm_source=x&ref=y") \
        == "acme.com/careers/eng"
    assert canonical_url("https://boards.io/list?jobid=884422&utm_campaign=spring") \
        == "boards.io/list?jobid=884422"


def test_parameter_order_does_not_make_a_second_job():
    one = canonical_url("https://boards.io/x?jobid=1&reqid=2")
    two = canonical_url("https://boards.io/x?reqid=2&jobid=1")
    assert one == two


def test_a_listing_and_its_own_apply_flow_are_one_posting():
    listing = "https://careers.acme.com/en-US/roles/48213-ar-specialist"
    applied = listing + "/apply/autofillWithResume"
    assert posting_stem(listing) == posting_stem(applied)


def test_apply_stripping_never_eats_the_part_that_names_the_job():
    # "/jobs" in the middle of a path must survive, or every posting at one
    # employer collapses into a single row.
    stem = posting_stem("https://careers.acme.com/jobs/48213/ar-specialist")
    assert "48213" in stem


def test_platform_ids_beat_the_link_they_arrived_in():
    a, tier = fingerprint("https://www.upwork.com/jobs/~017acdef99120abc44?ref=feed",
                          "RAG Engineer", "Northwind")
    b, _ = fingerprint("upwork.com/ab/proposals/~017acdef99120abc44", "", "")
    assert tier == "L1" and a == b


def test_the_same_numeric_id_on_two_sites_is_two_jobs():
    a, _ = fingerprint("https://example.com/job/backend-12345678", "", "")
    b, _ = fingerprint("https://different.com/job/backend-12345678", "", "")
    assert a != b


def test_a_row_with_no_link_still_has_an_identity():
    fp, tier = fingerprint("", "React Developer", "Northwind Digital")
    assert tier == "L3" and fp.startswith("ct:")


def test_a_row_with_nothing_typed_is_unusable():
    assert fingerprint("", "", "") == ("", "-")
