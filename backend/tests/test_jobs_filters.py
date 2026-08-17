"""GET /jobs filter params and /trends/sources build the SQL we expect.

These assert on the compiled statement rather than round-tripping a real
database (the suite has no Postgres) — enough to catch a filter silently
not being applied, which is the failure mode that matters here.
"""

from app.routes.jobs import _filtered_jobs_query


def _sql(**kwargs) -> str:
    params = {
        "location": None,
        "company": None,
        "source_type": None,
        "skill": None,
        "q": None,
        "since_days": None,
    }
    params.update(kwargs)
    return str(_filtered_jobs_query(**params).compile(compile_kwargs={"literal_binds": True}))


def test_no_filters_has_no_where():
    assert "WHERE" not in _sql()


def test_source_type_lowercased_and_exact():
    sql = _sql(source_type="Greenhouse")
    assert "source_type = 'greenhouse'" in sql


def test_skill_uses_array_containment():
    # @> is the operator the GIN index on skills serves; ANY() would not use it
    sql = _sql(skill="Python")
    assert "@>" in sql
    assert "python" in sql


def test_company_is_case_insensitive_exact():
    sql = _sql(company="Cohere")
    assert "lower(job_postings.company) = 'cohere'" in sql


def test_location_is_substring():
    sql = _sql(location="Toronto")
    assert "lower(job_postings.location)" in sql and "LIKE" in sql.upper()


def test_title_search_is_substring():
    sql = _sql(q="engineer")
    assert "lower(job_postings.title)" in sql and "LIKE" in sql.upper()


def test_since_days_adds_date_bound():
    sql = _sql(since_days=7)
    assert "date_scraped >=" in sql


def test_count_route_is_declared_before_the_id_route():
    """/jobs/count must not be swallowed by /jobs/{job_id}.

    FastAPI matches in declaration order, so moving count_jobs below get_job
    would make GET /jobs/count try to parse "count" as an int and 422.
    """
    from app.main import app

    paths = [r.path for r in app.routes if getattr(r, "path", "").startswith("/jobs")]
    assert paths.index("/jobs/count") < paths.index("/jobs/{job_id}")


def test_filters_combine():
    sql = _sql(source_type="lever", skill="rust", q="senior", since_days=30)
    for fragment in ("source_type = 'lever'", "@>", "lower(job_postings.title)", "date_scraped >="):
        assert fragment in sql
    assert sql.upper().count(" AND ") >= 3
