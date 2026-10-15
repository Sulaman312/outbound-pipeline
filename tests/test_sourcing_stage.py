from outbound.export import write_csv
from outbound.models import Stage
from outbound.sources import build_source
from outbound.sources.apollo import SEARCH_PATH as APOLLO
from outbound.sources.google_places import SEARCH_PATH as PLACES
from outbound.stages.sourcing import SourcingStage
from tests.conftest import FakeApi
from tests.test_sources import apollo_person, place


def run_stage(config, store, icp_id, country, responses, sources):
    api = FakeApi(responses)
    built = [build_source(n, config, store, live=True, transport=api) for n in sources]
    return SourcingStage(config, store, built).run(icp_id, country), api


def test_same_domain_from_two_sources_becomes_one_lead(config, store, keys):
    icp = config.icp("A")
    icp.sources["google_places"] = {
        "queries": ["software company"],
        "cities": {"US": ["Austin TX"]},
    }
    result, _ = run_stage(
        config,
        store,
        "A",
        "US",
        {
            APOLLO: [
                (
                    200,
                    {
                        "people": [
                            apollo_person("p1", "Acme", "acme.io"),
                            apollo_person("p2", "Beta Labs", "beta.dev"),
                        ],
                        "pagination": {"total_pages": 1},
                    },
                )
            ],
            PLACES: [
                (200, {"places": [place("g1", "Acme Software", "https://www.acme.io/contact")]})
            ],
        },
        ["apollo", "google_places"],
    )

    assert result.counts["new"] == 2 and result.counts["merged"] == 1
    leads = {lead.company.domain: lead for lead in store.leads(icp="A")}
    acme = leads["acme.io"]
    assert acme.sources == ["apollo", "google_places"]
    assert acme.company.phone == "020 1234"  # gap filled from Maps
    assert acme.company.name == "Acme"  # first value kept
    assert acme.contact.title == "Founder"
    assert acme.stage == Stage.SOURCED


def test_rerun_is_idempotent(config, store, keys):
    resp = lambda: {
        APOLLO: [
            (
                200,
                {
                    "people": [apollo_person("p1", "Acme", "acme.io")],
                    "pagination": {"total_pages": 1},
                },
            )
        ]
    }
    run_stage(config, store, "A", "US", resp(), ["apollo"])
    result, _ = run_stage(config, store, "A", "US", resp(), ["apollo"])
    assert result.counts["merged"] == 1
    assert len(list(store.leads())) == 1
    assert next(store.leads()).source_ids == {"apollo": ["p1"]}


def test_disqualified_and_suppressed_are_not_stored(config, store, keys):
    store.suppress("domain", "blocked.com", "asked to stop")
    result, _ = run_stage(
        config,
        store,
        "A",
        "US",
        {
            APOLLO: [
                (
                    200,
                    {
                        "people": [
                            apollo_person("p1", "Big Co", "big.com", employees=40),  # > max 10
                            apollo_person(
                                "p2", "DevOutsourcing Hub", "hub.com"
                            ),  # sells outsourcing
                            apollo_person("p3", "Blocked", "blocked.com"),  # suppressed
                            apollo_person("p4", "Good", "good.com"),
                        ],
                        "pagination": {"total_pages": 1},
                    },
                )
            ]
        },
        ["apollo"],
    )
    assert result.counts["disqualified"] == 2
    assert result.counts["suppressed"] == 1
    assert [lead.company.domain for lead in store.leads()] == ["good.com"]


def test_provider_failure_keeps_earlier_results(config, store, keys):
    config.icp("A").sources["apollo"]["max_pages"] = 2
    config.settings.http.max_retries = 0
    result, _ = run_stage(
        config,
        store,
        "A",
        "US",
        {
            APOLLO: [
                (
                    200,
                    {
                        "people": [apollo_person("p1", "Acme", "acme.io")],
                        "pagination": {"total_pages": 5},
                    },
                ),
                (500, {"error": "down"}),
            ]
        },
        ["apollo"],
    )
    assert "apollo" in result.errors
    assert [lead.company.domain for lead in store.leads()] == ["acme.io"]


def test_export_csv(config, store, keys, tmp_path):
    run_stage(
        config,
        store,
        "A",
        "US",
        {
            APOLLO: [
                (
                    200,
                    {
                        "people": [apollo_person("p1", "Acme", "acme.io")],
                        "pagination": {"total_pages": 1},
                    },
                )
            ]
        },
        ["apollo"],
    )
    out = tmp_path / "leads.csv"
    assert write_csv(store.leads(stage=Stage.SOURCED), out) == 1
    header, row = out.read_text().splitlines()
    assert header.startswith("lead_id,icp,country,stage,company_name,domain")
    assert ",acme.io," in row
