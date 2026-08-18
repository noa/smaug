"""
Tests for hourly masters student support.
"""

from decimal import Decimal

import pytest

from smaug.models import EmployeeType
from smaug.projections import (
    Assignment,
    PersonnelEntry,
    Rates,
    SalaryRecord,
    apply_hypotheticals,
    parse_hypothetical,
    project_monthly_costs,
)

# --- Fixtures ---


@pytest.fixture
def masters_rates():
    """Rates with masters-specific fields configured."""
    return Rates(
        idc=Decimal("0.55"),
        fringe={
            "faculty": Decimal("0.315"),
            "postdoc": Decimal("0.211"),
            "grad_student": Decimal("0.0"),
            "masters_student": Decimal("0.0825"),
            "staff": Decimal("0.315"),
        },
        tuition_per_semester=Decimal("6667"),
        insurance_annual=Decimal("4365"),
        tuition_months=[1, 9],
        masters_tuition_per_semester=Decimal("33335"),
        masters_hourly_default=Decimal("20"),
        masters_hours_per_week_default=Decimal("20"),
        masters_max_hours_per_week=Decimal("19.9"),
    )


@pytest.fixture
def masters_person():
    """A masters student assigned to QUASAR at 100%."""
    return PersonnelEntry(
        name="Kim, Minjae",
        person_type="masters_student",
        annual_salary=Decimal("20800"),  # $20/hr * 20 hrs/wk * 52 wks
        assignments=[Assignment(project="QUASAR", effort=Decimal("1.0"))],
        salaries=[SalaryRecord(amount=Decimal("20800"))],
        hourly_rate=Decimal("20"),
        hours_per_week=Decimal("20"),
        include_tuition=True,
        include_insurance=True,
    )


# --- EmployeeType enum ---


def test_masters_student_enum():
    """MASTERS_STUDENT exists in EmployeeType."""
    assert EmployeeType.MASTERS_STUDENT.value == "masters_student"
    # Round-trip from string
    assert EmployeeType("masters_student") == EmployeeType.MASTERS_STUDENT


# --- Hourly salary computation ---


def test_masters_annual_salary_from_hourly():
    """Annual salary = hourly_rate * hours_per_week * 52."""
    hourly = Decimal("20")
    hours = Decimal("20")
    expected = hourly * hours * 52  # $20,800
    assert expected == Decimal("20800")


def test_masters_annual_salary_custom_hours():
    """Custom hours_per_week changes the annual salary."""
    hourly = Decimal("25")
    hours = Decimal("15")
    expected = hourly * hours * 52  # $19,500
    assert expected == Decimal("19500")


# --- Cost projections ---


def test_masters_monthly_salary(masters_rates, masters_person):
    """Masters student monthly salary = annual / 12 * effort."""
    proj = project_monthly_costs("QUASAR", masters_rates, [masters_person], 2026, 3)
    expected_monthly = Decimal("20800") / 12  # ~$1,733.33
    assert abs(proj.direct_salary - expected_monthly) < Decimal("0.01")


def test_masters_fringe_rate(masters_rates, masters_person):
    """Masters student is FICA-exempt (0% fringe) in academic year (e.g. March) but subject to 8.25% in summer (e.g. July)."""
    # 1. Academic year month (March)
    proj_academic = project_monthly_costs("QUASAR", masters_rates, [masters_person], 2026, 3)
    assert proj_academic.fringe == Decimal("0.0")

    # 2. Summer month (July)
    proj_summer = project_monthly_costs("QUASAR", masters_rates, [masters_person], 2026, 7)
    expected_salary = Decimal("20800") / 12
    expected_fringe = expected_salary * Decimal("0.0825")
    assert abs(proj_summer.fringe - expected_fringe) < Decimal("0.01")


def test_masters_tuition_billed_in_semester_month(masters_rates, masters_person):
    """Tuition is billed in semester months (Jan, Sep) at masters rate."""
    # January is a tuition month
    proj = project_monthly_costs("QUASAR", masters_rates, [masters_person], 2026, 1)
    # At 100% effort, tuition should equal masters_tuition_per_semester
    assert proj.tuition == Decimal("33335")


def test_masters_no_tuition_in_regular_month(masters_rates, masters_person):
    """No tuition in non-billing months."""
    proj = project_monthly_costs(
        "QUASAR",
        masters_rates,
        [masters_person],
        2026,
        3,  # March
    )
    assert proj.tuition == Decimal("0")


def test_masters_insurance_billed_in_semester_month(masters_rates, masters_person):
    """Insurance billed in semester months, prorated by effort."""
    proj = project_monthly_costs(
        "QUASAR",
        masters_rates,
        [masters_person],
        2026,
        9,  # September
    )
    # insurance_annual / 2 * effort = 4365 / 2 * 1.0 = 2182.50
    assert proj.insurance == Decimal("4365") / 2


def test_masters_tuition_excluded_when_flag_false(masters_rates):
    """include_tuition=False suppresses tuition billing."""
    person = PersonnelEntry(
        name="Park, Soo",
        person_type="masters_student",
        annual_salary=Decimal("20800"),
        assignments=[Assignment(project="QUASAR", effort=Decimal("1.0"))],
        salaries=[SalaryRecord(amount=Decimal("20800"))],
        include_tuition=False,
        include_insurance=True,
    )
    proj = project_monthly_costs(
        "QUASAR",
        masters_rates,
        [person],
        2026,
        1,  # Tuition month
    )
    assert proj.tuition == Decimal("0")
    # Insurance should still be billed
    assert proj.insurance > Decimal("0")


def test_masters_insurance_excluded_when_flag_false(masters_rates):
    """include_insurance=False suppresses insurance billing."""
    person = PersonnelEntry(
        name="Park, Soo",
        person_type="masters_student",
        annual_salary=Decimal("20800"),
        assignments=[Assignment(project="QUASAR", effort=Decimal("1.0"))],
        salaries=[SalaryRecord(amount=Decimal("20800"))],
        include_tuition=True,
        include_insurance=False,
    )
    proj = project_monthly_costs(
        "QUASAR",
        masters_rates,
        [person],
        2026,
        9,  # Billing month
    )
    assert proj.insurance == Decimal("0")
    # Tuition should still be billed
    assert proj.tuition > Decimal("0")


def test_masters_effort_prorates_tuition(masters_rates):
    """Tuition is prorated by effort."""
    person = PersonnelEntry(
        name="Half, Time",
        person_type="masters_student",
        annual_salary=Decimal("10400"),  # half hours
        assignments=[Assignment(project="QUASAR", effort=Decimal("0.5"))],
        salaries=[SalaryRecord(amount=Decimal("10400"))],
        include_tuition=True,
        include_insurance=True,
    )
    proj = project_monthly_costs("QUASAR", masters_rates, [person], 2026, 1)
    assert proj.tuition == Decimal("33335") * Decimal("0.5")


def test_masters_uses_different_tuition_than_phd(masters_rates):
    """Masters tuition uses masters_tuition_per_semester, not tuition_per_semester."""
    # PhD student
    phd = PersonnelEntry(
        name="Grad, Student",
        person_type="grad_student",
        annual_salary=Decimal("50000"),
        assignments=[Assignment(project="QUASAR", effort=Decimal("1.0"))],
        salaries=[SalaryRecord(amount=Decimal("50000"))],
    )
    phd_proj = project_monthly_costs("QUASAR", masters_rates, [phd], 2026, 1)

    # Masters student
    ms = PersonnelEntry(
        name="Masters, Student",
        person_type="masters_student",
        annual_salary=Decimal("20800"),
        assignments=[Assignment(project="QUASAR", effort=Decimal("1.0"))],
        salaries=[SalaryRecord(amount=Decimal("20800"))],
        include_tuition=True,
        include_insurance=True,
    )
    ms_proj = project_monthly_costs("QUASAR", masters_rates, [ms], 2026, 1)

    # PhD uses tuition_per_semester ($6,667), masters uses masters_tuition_per_semester ($33,335)
    assert phd_proj.tuition == Decimal("6667")
    assert ms_proj.tuition == Decimal("33335")
    assert ms_proj.tuition > phd_proj.tuition


# --- Hypothetical parsing ---


def test_parse_hypothetical_masters():
    """'+masters@100%' parses to a masters_student addition."""
    hypo = parse_hypothetical("+masters@100%")
    assert hypo.is_addition is True
    assert hypo.person_type == "masters_student"
    assert hypo.effort == Decimal("1.0")


def test_parse_hypothetical_ms():
    """'+ms@50%' parses to a masters_student addition."""
    hypo = parse_hypothetical("+ms@50%")
    assert hypo.is_addition is True
    assert hypo.person_type == "masters_student"
    assert hypo.effort == Decimal("0.5")


def test_parse_hypothetical_masters_with_salary():
    """'+masters@100%:25000' specifies salary."""
    hypo = parse_hypothetical("+masters@100%:25000")
    assert hypo.is_addition is True
    assert hypo.person_type == "masters_student"
    assert hypo.salary == Decimal("25000")


def test_apply_hypothetical_masters_default_salary(masters_rates):
    """Hypothetical masters student gets default hourly salary if none given."""
    hypo = parse_hypothetical("+masters@100%")
    result = apply_hypotheticals([], [hypo], "QUASAR", masters_rates)
    assert len(result) == 1
    person = result[0]
    assert person.person_type == "masters_student"
    # Default: 20 * 20 * 52 = 20800
    assert person.annual_salary == Decimal("20") * Decimal("20") * 52


def test_apply_hypothetical_masters_custom_salary(masters_rates):
    """Hypothetical masters student uses specified salary."""
    hypo = parse_hypothetical("+masters@100%:25000")
    result = apply_hypotheticals([], [hypo], "QUASAR", masters_rates)
    assert result[0].annual_salary == Decimal("25000")


# --- Personnel config loading ---


def test_load_masters_from_yaml(tmp_path):
    """Loading a masters_student from personnel_config.yaml computes correct salary."""
    # Create rates.yaml
    rates_yaml = tmp_path / "rates.yaml"
    rates_yaml.write_text("""
idc_rate: 0.55
fringe_rates:
  masters_student: 0.0825
  grad_student: 0.0
  faculty: 0.315
  postdoc: 0.211
  staff: 0.315
grad_student_costs:
  stipend: 50000
  phd_tuition: 13334
  masters_tuition: 66670
  health_dental: 4365
tuition_billing:
  months: [1, 9]
  per_semester: 6667
  masters_per_semester: 33335
masters_hourly: 20.0
masters_hours_per_week: 20
masters_max_hours_per_week: 19.9
""")

    # Create personnel_config.yaml
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    config = projects_dir / "personnel_config.yaml"
    config.write_text("""
personnel:
  - name: "Kim, Minjae"
    type: masters_student
    hourly_rate: 22
    hours_per_week: 15
    assignments:
      - project: QUASAR
        effort: 1.0
""")

    from smaug.projections import load_personnel_config

    _rates, personnel = load_personnel_config(config)

    assert len(personnel) == 1
    p = personnel[0]
    assert p.person_type == "masters_student"
    assert p.hourly_rate == Decimal("22")
    assert p.hours_per_week == Decimal("15")
    # Annual salary = 22 * 15 * 52 = 17160
    assert p.annual_salary == Decimal("22") * Decimal("15") * 52


def test_load_masters_defaults_from_rates(tmp_path):
    """Masters student without hourly_rate/hours_per_week uses rates.yaml defaults."""
    rates_yaml = tmp_path / "rates.yaml"
    rates_yaml.write_text("""
idc_rate: 0.55
fringe_rates:
  masters_student: 0.0825
  grad_student: 0.0
grad_student_costs:
  stipend: 50000
  health_dental: 4365
tuition_billing:
  months: [1, 9]
  per_semester: 6667
  masters_per_semester: 33335
masters_hourly: 25.0
masters_hours_per_week: 19
""")

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    config = projects_dir / "personnel_config.yaml"
    config.write_text("""
personnel:
  - name: "Lee, Jun"
    type: masters_student
    assignments:
      - project: QUASAR
        effort: 1.0
""")

    from smaug.projections import load_personnel_config

    _rates, personnel = load_personnel_config(config)

    p = personnel[0]
    assert p.hourly_rate is None  # Not explicitly set
    assert p.hours_per_week is None  # Not explicitly set
    # Uses defaults: 25 * 19 * 52 = 24700
    assert p.annual_salary == Decimal("25") * Decimal("19") * 52


def test_masters_hours_cap_warning(tmp_path, caplog):
    """Loading a masters student with hours > cap logs a warning."""
    import logging

    rates_yaml = tmp_path / "rates.yaml"
    rates_yaml.write_text("""
idc_rate: 0.55
fringe_rates:
  masters_student: 0.0825
  grad_student: 0.0
grad_student_costs:
  stipend: 50000
  health_dental: 4365
tuition_billing:
  months: [1, 9]
  per_semester: 6667
  masters_per_semester: 33335
masters_hourly: 20
masters_hours_per_week: 20
masters_max_hours_per_week: 19.9
""")

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    config = projects_dir / "personnel_config.yaml"
    config.write_text("""
personnel:
  - name: "Over, Worked"
    type: masters_student
    hours_per_week: 25
    assignments:
      - project: QUASAR
        effort: 1.0
""")

    from smaug.projections import load_personnel_config

    with caplog.at_level(logging.WARNING):
        _rates, _personnel = load_personnel_config(config)

    assert any("exceeds JHU cap" in r.message for r in caplog.records)


def test_masters_proposal_fringe_prorated(masters_rates):
    """Proposal budget fringe rate for masters students is pro-rated to 3/12 of the annual rate (summer only)."""
    from smaug.proposal_budget import ProposalPerson, generate_proposal_budget

    rates_config = {
        "idc_rate": Decimal("0.55"),
        "fringe_rates": {
            "part_time": Decimal("0.08"),  # 8%
        },
        "grad_student_costs": {},
        "tuition_billing": {},
    }

    # Annual salary $20,000, 100% effort, 1 year
    person = ProposalPerson(
        label="Masters Student",
        person_type="part_time",
        effort=Decimal("1.0"),
        annual_salary=Decimal("20000"),
        student_type="masters",
        include_tuition=False,
    )

    budget = generate_proposal_budget([person], rates_config, num_years=1)

    # Expected fringe = 20000 * (0.08 * 3 / 12) = 20000 * 0.02 = 400
    assert budget.years[0].fringe == Decimal("400")
