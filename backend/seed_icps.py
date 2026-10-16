"""ICPs the database starts with (schema version 2). Plain data, edited afterwards on the ICPs page.

- The 8 segments that used to live in config/segments.yaml, as inactive ICPs, so companies
  already saved under them still point at a real ICP.
- The 3 pilot ICPs from the launch plan (one per pilot campaign), active.
"""

from __future__ import annotations

from typing import Any

CLAY_TITLES = ["Founder", "Co-Founder", "Owner", "CEO", "President"]


def _segment(key: str, offer: str, name: str, keywords: list[str]) -> dict[str, Any]:
    return {
        "key": key,
        "name": name,
        "description": "Imported from config/segments.yaml (before M1).",
        "offer": offer,
        "country": "US",
        "active": False,
        "person_titles": CLAY_TITLES,
        "person_locations": [],
        "exclude_notes": "",
        "target_leads": 0,
        "sources": {
            "apollo": {
                "hq_locations": ["United States"],
                "employee_ranges": ["1,20"],
                "keywords": keywords,
            }
        },
    }


LEGACY_SEGMENTS: list[dict[str, Any]] = [
    _segment(
        "frontend_agencies",
        "frontend",
        "US web design and digital agencies, 1-20 staff",
        ["web design", "digital agency", "web development"],
    ),
    _segment(
        "frontend_saas",
        "frontend",
        "US SaaS and software startups, 1-20 staff",
        ["saas", "software"],
    ),
    _segment(
        "frontend_ecommerce",
        "frontend",
        "US e-commerce brands, 1-20 staff",
        ["ecommerce", "e-commerce", "shopify"],
    ),
    _segment(
        "ai_marketing_agencies",
        "ai_automation",
        "US marketing agencies, 1-20 staff",
        ["marketing agency", "digital marketing"],
    ),
    _segment(
        "ai_accounting",
        "ai_automation",
        "US accounting and bookkeeping firms, 1-20 staff",
        ["accounting", "bookkeeping"],
    ),
    _segment("ai_law", "ai_automation", "US law firms, 1-20 staff", ["law firm", "legal services"]),
    _segment(
        "ai_real_estate",
        "ai_automation",
        "US real estate agencies and brokerages, 1-20 staff",
        ["real estate agency", "real estate brokerage"],
    ),
    _segment(
        "ai_recruiting",
        "ai_automation",
        "US recruiting and staffing firms, 1-20 staff",
        ["recruiting", "staffing"],
    ),
]

_DEV_APOLLO = {
    "hq_locations": ["Texas", "New York"],
    "employee_ranges": ["1,10"],
    "keywords": ["software development", "saas", "web development"],
}
_DEV_PEOPLE = {
    "person_titles": ["Founder", "Co-Founder", "CEO", "CTO", "Owner"],
    "person_locations": ["Texas", "New York"],
    "exclude_notes": "IT outsourcing and staff augmentation firms",
}

PILOT_ICPS: list[dict[str, Any]] = [
    {
        "key": "dev_us_signal",
        "name": "Dev agencies and SaaS, TX + NY, hiring developers",
        "description": (
            "Campaign DEV_US_Signal_v1. Software, SaaS and dev agencies with an open developer "
            "job post in the last 60 days. Find companies for this ICP before dev_us_pain."
        ),
        "offer": "Full-stack developer outsourcing",
        "country": "US",
        "active": True,
        **_DEV_PEOPLE,
        "target_leads": 250,
        "sources": {
            "apollo": {
                **_DEV_APOLLO,
                "job_titles": ["developer", "engineer", "full stack"],
                "job_posted_within_days": 60,
            }
        },
    },
    {
        "key": "dev_us_pain",
        "name": "Dev agencies and SaaS, TX + NY, no hiring signal",
        "description": (
            "Campaign DEV_US_Pain_v1. Same companies as dev_us_signal without the job-post "
            "signal. Run dev_us_signal first: companies it already saved are skipped here."
        ),
        "offer": "Full-stack developer outsourcing",
        "country": "US",
        "active": True,
        **_DEV_PEOPLE,
        "target_leads": 250,
        "sources": {"apollo": dict(_DEV_APOLLO)},
    },
    {
        "key": "bpa_us_recruit",
        "name": "Staffing and recruiting agencies, TX + FL",
        "description": (
            "Campaign BPA_US_Recruit_CaseStudy_v1. The launch plan also allows 1-10 staff "
            'firms with at least 5 staff: add the range "5,10" to include them.'
        ),
        "offer": "Business process automation (AI sourcing and screening)",
        "country": "US",
        "active": True,
        "person_titles": [
            "Founder",
            "Owner",
            "CEO",
            "President",
            "Managing Director",
            "Director of Operations",
            "Head of Delivery",
        ],
        "person_locations": ["Texas", "Florida"],
        "exclude_notes": "Solo recruiters, firms over 200 staff, national chains' branch offices",
        "target_leads": 500,
        "sources": {
            "apollo": {
                "hq_locations": ["Texas", "Florida"],
                "employee_ranges": ["11,50"],
                "keywords": ["staffing", "recruiting"],
            }
        },
    },
]
