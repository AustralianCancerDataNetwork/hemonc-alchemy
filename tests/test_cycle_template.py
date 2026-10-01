"""`cycle_template` against a real imported variant."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
import sqlalchemy.orm as so

from hemonc_alchemy.model import Variants
from hemonc_alchemy.toolkit.analytics.treatment.scheduling import (
    cycle_block_templates,
    cycle_template,
)

pytestmark = pytest.mark.postgres

_SEVEN_PLUS_THREE_D_CUI = 129505
_BEACOPP_14_CUI = 129853
_DEGARELIX_MONOTHERAPY_CUI = 131601
_ELTROMBOPAG_MONOTHERAPY_CUI = 131885
_ANASTROZOLE_MONOTHERAPY_CUI = 129670
_A_CMF_CUI = 129540
_DEVCONTAINER_URL = "postgresql+psycopg://hemonc:hemonc@localhost:5432/hemonc_alchemy"


def _load_latest_variant(cui: int):
    """The highest-`version` row for `cui`, or skip if postgres/the row is unavailable."""
    try:
        engine = sa.create_engine(_DEVCONTAINER_URL, future=True)
        with engine.connect() as conn:
            conn.execute(sa.text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 -- any connection failure just skips
        pytest.skip(f"devcontainer PostgreSQL not reachable: {exc}")

    with so.Session(engine) as session:
        rows = session.execute(
            sa.select(Variants).where(Variants.variant_cui == cui)
        ).scalars().all()
        if not rows:
            pytest.skip(f"imported database has no variant_cui={cui}")
        yield max(rows, key=lambda variant: variant.version)
    engine.dispose()


@pytest.fixture
def variant_129505():
    yield from _load_latest_variant(_SEVEN_PLUS_THREE_D_CUI)


@pytest.fixture
def variant_129853():
    yield from _load_latest_variant(_BEACOPP_14_CUI)


@pytest.fixture
def variant_131601():
    yield from _load_latest_variant(_DEGARELIX_MONOTHERAPY_CUI)


@pytest.fixture
def variant_131885():
    yield from _load_latest_variant(_ELTROMBOPAG_MONOTHERAPY_CUI)


@pytest.fixture
def variant_129670():
    yield from _load_latest_variant(_ANASTROZOLE_MONOTHERAPY_CUI)


@pytest.fixture
def variant_129540():
    yield from _load_latest_variant(_A_CMF_CUI)


def test_seven_plus_three_d_cycle_template(variant_129505):
    template = cycle_template(variant_129505)

    assert template.id == "7+3d129505"
    assert template.common_name == "7+3d"
    assert template.cycle_len == 7
    assert template.diseases == {"Acute myeloid leukemia"}
    assert template.iv_drug == ["Cytarabine", "Daunorubicin"]
    assert template.po_drug == []
    assert template.endocrine_regimen is False
    assert template.supportive_regimen is False

    assert template.binary_iv["Cytarabine"].tolist() == [1, 0, 0, 0, 0, 0, 0]
    assert template.binary_iv["Daunorubicin"].tolist() == [1, 1, 1, 0, 0, 0, 0]
    assert template.binary_po.empty

    fuzzy = template.binary_fuzzy
    assert fuzzy["Cytarabine"].iloc[0] == pytest.approx(1.0)
    assert fuzzy["Cytarabine"].iloc[1] == pytest.approx(0.606531, abs=1e-6)
    assert fuzzy["Cytarabine"].iloc[5] == pytest.approx(0.1)
    assert fuzzy["Daunorubicin"].iloc[2] == pytest.approx(1.0)
    assert fuzzy["Daunorubicin"].iloc[3] == pytest.approx(0.606531, abs=1e-6)

    assert template.dose_iv.loc[0, "Cytarabine"] == "200;mg/m^2/day"
    assert template.dose_iv.loc[0, "Daunorubicin"] == "30;mg/m^2"


def test_beacopp_14_cycle_template(variant_129853):
    template = cycle_template(variant_129853)

    assert template.id == "BEACOPP-14129853"
    assert template.common_name == "BEACOPP-14"
    assert template.cycle_len == 14
    assert template.diseases == {"Classical Hodgkin lymphoma"}
    assert template.iv_drug == ["Bleomycin", "Cyclophosphamide", "Doxorubicin", "Etoposide", "Vincristine"]
    assert template.po_drug == ["Prednisone", "Procarbazine"]
    assert template.endocrine_regimen is False
    assert template.supportive_regimen is False

    assert template.binary_iv["Cyclophosphamide"].tolist() == [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    assert template.binary_iv["Etoposide"].tolist() == [1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    assert template.binary_iv["Bleomycin"].tolist() == [0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0]
    # PO drugs run days 1-7 only, per the live sigs; the cycle continues to day 14 undosed.
    assert template.binary_po["Prednisone"].tolist() == [1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0]
    assert template.binary_po["Procarbazine"].tolist() == [1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0]

    fuzzy = template.binary_fuzzy
    assert list(fuzzy.columns) == template.iv_drug  # decay is IV-only, matching RG_uniq's Binary_fuzzy
    assert fuzzy["Cyclophosphamide"].iloc[0] == pytest.approx(1.0)
    assert fuzzy["Cyclophosphamide"].iloc[1] == pytest.approx(0.606531, abs=1e-6)
    assert fuzzy["Etoposide"].iloc[3] == pytest.approx(0.606531, abs=1e-6)
    assert fuzzy["Bleomycin"].iloc[7] == pytest.approx(1.0)
    assert fuzzy["Bleomycin"].iloc[8] == pytest.approx(0.606531, abs=1e-6)

    assert template.dose_iv.loc[0, "Cyclophosphamide"] == "650;mg/m^2"
    assert template.dose_iv.loc[0, "Doxorubicin"] == "25;mg/m^2"
    assert template.dose_iv.loc[0, "Etoposide"] == "100;mg/m^2"
    assert template.dose_iv.loc[7, "Bleomycin"] == "10;units/m^2"
    assert template.dose_iv.loc[7, "Vincristine"] == "1.4;mg/m^2"

    assert template.dose_po.loc[0, "Prednisone"] == "80;mg/m^2"
    assert template.dose_po.loc[0, "Procarbazine"] == "100;mg/m^2"
    assert list(template.dose_po.index) == [0, 1, 2, 3, 4, 5, 6]  # RG_uniq's own Dose_PO is truncated the same way


def test_degarelix_monotherapy_cycle_template(variant_131601):
    template = cycle_template(variant_131601)

    assert template.id == "Degarelix monotherapy131601"
    assert template.common_name == "Degarelix monotherapy"
    assert template.cycle_len == 84
    assert template.diseases == {"Prostate cancer"}
    assert template.iv_drug == ["Degarelix"]
    assert template.po_drug == []
    # A GnRH antagonist: a real "Endocrine therapeutic" descendant, same bucket as
    # aromatase inhibitors now that GnRH and non-GnRH hormone therapy are merged.
    assert template.endocrine_regimen is True
    assert template.supportive_regimen is False

    assert template.binary_iv["Degarelix"].tolist().count(1) == 2
    assert template.binary_iv["Degarelix"].iloc[27] == 1
    assert template.binary_iv["Degarelix"].iloc[55] == 1

    assert template.dose_iv.loc[-1, "Degarelix"] == "240;mg"
    assert template.dose_iv.loc[27, "Degarelix"] == "80;mg"
    assert template.dose_iv.loc[55, "Degarelix"] == "80;mg"


def test_eltrombopag_monotherapy_cycle_template(variant_131885):
    template = cycle_template(variant_131885)

    assert template.id == "Eltrombopag monotherapy131885"
    assert template.common_name == "Eltrombopag monotherapy"
    assert template.cycle_len == 14
    assert template.diseases == {"Aplastic anemia"}
    assert template.iv_drug == []
    assert template.po_drug == ["Eltrombopag"]
    assert template.endocrine_regimen is False
    assert template.supportive_regimen is True  # a megakaryocyte growth factor, per drugs.main_class

    assert template.binary_po["Eltrombopag"].tolist() == [1] * 14
    assert template.dose_po.loc[0, "Eltrombopag"] == "50;mg"


def test_anastrozole_monotherapy_cycle_template(variant_129670):
    template = cycle_template(variant_129670)

    assert template.id == "Anastrozole monotherapy129670"
    assert template.common_name == "Anastrozole monotherapy"
    assert template.cycle_len == 84
    assert template.diseases == {"Breast cancer"}
    assert template.iv_drug == []
    assert template.po_drug == ["Anastrozole"]
    # An aromatase inhibitor: a real "Endocrine therapeutic" descendant, same bucket
    # as GnRH agonists/antagonists now that GnRH and non-GnRH hormone therapy are merged.
    assert template.endocrine_regimen is True
    assert template.supportive_regimen is False

    assert template.binary_po["Anastrozole"].tolist() == [1] * 84
    assert template.dose_po.loc[0, "Anastrozole"] == "1;mg"


def test_seven_plus_three_d_cycle_block_templates_match_cycle_template(variant_129505):
    """A single-block variant's `cycle_block_templates` reduces to `cycle_template`."""
    direct = cycle_template(variant_129505)
    blocks = cycle_block_templates(variant_129505)

    assert len(blocks) == 1
    assert blocks[0].repeat_count == 1
    block = blocks[0].template

    assert block.id == direct.id
    assert block.common_name == direct.common_name
    assert block.cycle_len == direct.cycle_len
    assert block.diseases == direct.diseases
    assert block.iv_drug == direct.iv_drug
    assert block.po_drug == direct.po_drug
    assert block.endocrine_regimen == direct.endocrine_regimen
    assert block.supportive_regimen == direct.supportive_regimen
    assert block.binary_iv.equals(direct.binary_iv)
    assert block.binary_po.equals(direct.binary_po)
    assert block.binary_fuzzy.equals(direct.binary_fuzzy)
    assert block.dose_iv.equals(direct.dose_iv)
    assert block.dose_po.equals(direct.dose_po)


def test_a_cmf_cycle_block_templates(variant_129540):
    """A-CMF (variant_cui=129540) has two distinct cycle schedules of 4 cycles each."""
    blocks = cycle_block_templates(variant_129540)

    assert len(blocks) == 2
    assert [block.repeat_count for block in blocks] == [4, 4]

    first, second = (block.template for block in blocks)

    # Block 1: the 21-day Doxorubicin-only schedule, matching RG_uniq row
    # ('338f31f4de149fb927be3a26cb66aa6c', '81dd8977cb022d97833ffd8670668830', 21).
    assert first.cycle_len == 21
    assert first.iv_drug == ["Doxorubicin"]
    assert first.po_drug == []
    assert first.binary_iv["Doxorubicin"].tolist() == [1] + [0] * 20
    assert first.dose_iv.loc[0, "Doxorubicin"] == "75;mg/m^2"

    # Block 2: the 28-day CMF schedule, matching RG_uniq row
    # ('61e6ea0eb783c052a2b26337b96d4171', '52cd36e20f58b3d2ae25d5fb13095bd1', 28).
    assert second.cycle_len == 28
    assert second.iv_drug == ["Cyclophosphamide", "Fluorouracil", "Methotrexate"]
    assert second.po_drug == []
    assert second.binary_iv["Cyclophosphamide"].tolist() == [1] + [0] * 6 + [1] + [0] * 20
    assert second.binary_iv["Fluorouracil"].tolist() == second.binary_iv["Cyclophosphamide"].tolist()
    assert second.binary_iv["Methotrexate"].tolist() == second.binary_iv["Cyclophosphamide"].tolist()
    # RG_uniq's own dose for this row is 500;mg/m^2 Cyclophosphamide -- this DB's live sig reads 600;mg/m^2.
    assert second.dose_iv.loc[0, "Cyclophosphamide"] == "600;mg/m^2"
    assert second.dose_iv.loc[7, "Cyclophosphamide"] == "600;mg/m^2"
    assert second.dose_iv.loc[0, "Fluorouracil"] == "600;mg/m^2"
    assert second.dose_iv.loc[0, "Methotrexate"] == "40;mg/m^2"

    for block in (first, second):
        assert block.diseases == {"Breast cancer"}
        assert block.endocrine_regimen is False
        assert block.supportive_regimen is False
        assert block.id == "A-CMF129540"
        assert block.common_name == "A-CMF"
